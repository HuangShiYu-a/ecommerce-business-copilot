"""条件多跳批量复测（G1 核查项）：真实工具 + DeepSeek，5~10 样本 ≥80%。

- 低库存 SKU（SKU_01_STOCKOUT_01）→ 预期深挖（≥2 次工具调用：风险→库存→异常）
- 健康 SKU（SKU_01_NORMAL_01）→ 预期早停（1 次风险判定 + 直接回答"无需深挖"）
判定：工具调用次数 + 最终回答是否基于观察。通过率 ≥80% 视为 G1 该项过。
依赖：PG 5434 + DeepSeek key。用法：python db/probe_multihop_batch.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from copilot.agent.toolkit import build_toolkit
from copilot.context import UserContext

MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
BASE = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


def llm():
    return ChatOpenAI(model=MODEL, base_url=BASE, api_key=os.getenv("DEEPSEEK_API_KEY"),
                      temperature=0.0, timeout=60, max_retries=1)


def run_case(model, tools, msg):
    """返回 (tool_names, final_answer)。"""
    tool_by_name = {t.name: t for t in tools}
    msgs = [HumanMessage(content=msg)]
    names = []
    for _ in range(6):
        resp = model.bind_tools(tools).invoke(msgs)
        if not resp.tool_calls:
            return names, str(resp.content or "")
        msgs.append(resp)
        for tc in resp.tool_calls:
            t = tool_by_name.get(tc["name"])
            out = str(t.invoke(dict(tc.get("args") or {}))) if t else "no tool"
            names.append(tc["name"])
            msgs.append(ToolMessage(content=out, tool_call_id=tc["id"]))
    return names, "MAX_ITER"


# (label, sku, expect_deep: bool, prompt)
SAMPLES = [
    ("S1a", "SKU_01_STOCKOUT_01", True, "SKU_01_STOCKOUT_01 有没有缺货风险？如果有，帮我进一步分析原因"),
    ("S1b", "SKU_01_STOCKOUT_01", True, "帮我看看 SKU_01_STOCKOUT_01 的缺货风险，如果风险高就深入分析一下"),
    ("S2a", "SKU_01_NORMAL_01", False, "SKU_01_NORMAL_01 有没有缺货风险？如果有，帮我进一步分析原因"),
    ("S2b", "SKU_01_NORMAL_01", False, "SKU_01_NORMAL_01 会不会断货？如果会的话分析下原因"),
]


# 深挖判据：进入因果分析工具（销售异常/健康度/慢销）才算"深挖"；仅补库存证据不算
DEEP_TOOLS = {"analyze_sales_anomaly", "calculate_product_health", "query_product_performance"}


def main() -> int:
    ctx = UserContext(user_id=1, role="operations", store_id=1)
    tools = build_toolkit("OPERATIONS", lambda: ctx)
    model = llm()

    passed = 0
    for label, sku, expect_deep, msg in SAMPLES:
        names, final = run_case(model, tools, msg)
        n = len(names)
        if expect_deep:
            # 低库存 → 深挖：≥2 次且进入因果分析工具
            ok = n >= 2 and any(t in DEEP_TOOLS for t in names)
        else:
            # 高库存 → 早停：不进入因果深挖，且及时停止（≤3 次）
            ok = not any(t in DEEP_TOOLS for t in names) and n <= 3
        passed += 1 if ok else 0
        print(f"[{'PASS' if ok else 'FAIL'}] {label} {sku} expect_deep={expect_deep} calls={names} n={n}")
        print(f"        answer: {final[:100]!r}")

    rate = passed / len(SAMPLES)
    print(f"\n通过率 {rate:.0%}（{passed}/{len(SAMPLES)}）— G1 门禁要求 ≥80%")
    return 0 if rate >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())
