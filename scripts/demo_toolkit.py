"""W1.5 live demo：DeepSeek 调转换后的 toolkit 工具（G1 评估清单）。

用法：python scripts/demo_toolkit.py [--mode OPERATIONS|CUSTOMER_SERVICE|UNSET]
依赖：PG 5434 在线 + DeepSeek key（.env）。
覆盖 G1 评估项：
  D1 明确请求→正确工具+参数
  D2 多工具组合→一次多 tool_call
  D3 工具报 NOT_FOUND→LLM 如实转述不编造
  D4 缺 SKU/订单号→LLM 反问不编造标识符
  D5 目录过滤（各模式工具清单）
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from copilot.agent.toolkit import build_toolkit, catalog_names
from copilot.context import UserContext

ROLE = {"OPERATIONS": "operations", "CUSTOMER_SERVICE": "customer_service", "UNSET": "operations"}


def llm():
    return ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        temperature=0.0, timeout=60, max_retries=1,
    )


def react_loop(model, tools, user_msg, max_iters=6):
    """手动 ReAct：LLM → tool_calls → 工具执行 → ToolMessage → 再决策。"""
    tool_by_name = {t.name: t for t in tools}
    msgs = [HumanMessage(content=user_msg)]
    trace = []
    for _ in range(max_iters):
        resp = model.bind_tools(tools).invoke(msgs)
        if not resp.tool_calls:
            return trace, str(resp.content or "")
        msgs.append(resp)
        for tc in resp.tool_calls:
            t = tool_by_name.get(tc["name"])
            if t is None:
                out = f"{{'error': '工具 {tc['name']} 不在当前目录'}}"
            else:
                out = str(t.invoke(dict(tc.get("args") or {})))
            trace.append({"tool": tc["name"], "args": tc.get("args"), "obs": out[:140]})
            msgs.append(ToolMessage(content=out, tool_call_id=tc["id"]))
    return trace, "MAX_ITER_REACHED"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="OPERATIONS",
                    choices=["OPERATIONS", "CUSTOMER_SERVICE", "UNSET"])
    args = ap.parse_args()
    mode = args.mode

    print(f"=== 目录过滤（{mode}）===")
    print(" ", catalog_names(mode))

    ctx = UserContext(user_id=1, role=ROLE[mode], store_id=1)
    tools = build_toolkit(mode, lambda: ctx)
    model = llm()

    cases = {
        "OPERATIONS": [
            ("D1 明确调用", "SKU_01_STOCKOUT_01 库存还剩多少"),
            ("D1 明确调用", "SKU_01_NORMAL_01 缺货风险怎么样"),
            ("D2 多工具组合", "SKU_01_STOCKOUT_01 有没有缺货风险，另外健康度怎么样"),
            ("D3 NOT_FOUND", "SKU_99_DOES_NOT_EXIST 库存多少"),
            ("D4 缺 SKU", "帮我看看那个商品的库存"),
        ],
        "CUSTOMER_SERVICE": [
            ("D1 明确调用", "ORD_01_000438 可以退货吗"),
            ("D2 多工具组合", "ORD_01_000438 能退货吗，另外物流到哪了"),
            ("D3 NOT_FOUND", "ORD_99_NOPE 物流到哪了"),
            ("D4 缺订单号", "帮我查一下那个订单的物流"),
        ],
        "UNSET": [
            ("D5 仅交集工具", "SKU_01_STOCKOUT_01 库存多少"),
            ("D4 缺 SKU", "查一下库存"),
        ],
    }
    for label, msg in cases[mode]:
        trace, final = react_loop(model, tools, msg)
        print("=" * 60)
        print(f"[{label}] {msg}")
        if not trace:
            print("  未调用工具")
        for t in trace:
            print(f"  -> {t['tool']}({t['args']})\n      obs: {t['obs']}")
        print(f"  最终回答: {final[:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
