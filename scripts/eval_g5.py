"""G5 live 评估：记忆生效 + 黄金问答生成式答案 grounding（W5.1/W5.2/W5.3）。

1) 记忆：用户说『默认看7天』→ 新会话缺货风险查询的 analyze_stockout_risk 应带 forecast_days=7
2) 黄金问答：rag_gold 抽样 → 生成式答案含关键事实（grounding，非空谈）
依赖：PG + DeepSeek。退出码 0=全过。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import yaml
from langgraph.checkpoint.memory import InMemorySaver

from copilot.agent.react import build_react_graph, run_agent_react
from copilot.runtime.store import clear_memory

GOLD = yaml.safe_load((ROOT / "data" / "eval-cases" / "rag_gold_v1.yaml").read_text(encoding="utf-8"))  # Correctness 冻结版；M4 走 rag_gold.yaml

# 黄金问答 grounding 关键词（源自 rag_gold 期望文档的关键事实）
GOLD_KEYWORDS = {
    "rg-001": "七日无理由退货底线",
    "rg-005": "例外商品/不可退类目",
    "rg-006": "滞销商品处理规则",
}
GOLD_KWS = {
    "rg-001": ["7", "七日", "7日"],
    "rg-005": ["不可退", "贴身", "内衣"],
    "rg-006": ["滞销"],
}


def collect_calls(msgs):
    calls = []
    for m in msgs:
        for tc in getattr(m, "tool_calls", None) or []:
            calls.append((tc.get("name"), dict(tc.get("args") or {})))
    return calls


def main() -> int:
    results: dict[str, bool] = {}
    sess = {"session_id": "g5", "user_id": 1, "workspace_mode": "OPERATIONS", "store_id": 1}

    # ---- 1) 记忆生效 ----
    clear_memory(1)
    g1 = build_react_graph(model=None, mode="OPERATIONS", checkpointer=InMemorySaver())
    run_agent_react(g1, "M1", sess, "我默认看 7 天")          # 写入 default_horizon=7
    g2 = build_react_graph(model=None, mode="OPERATIONS", checkpointer=InMemorySaver())
    out = run_agent_react(g2, "M2", sess, "SKU_01_STOCKOUT_01 缺货风险怎么样")
    args = [a for name, a in collect_calls(out["state"]["messages"]) if name == "analyze_stockout_risk"]
    forecast = args[0].get("forecast_days") if args else None
    results["记忆生效"] = forecast == 7
    print(f"[{'PASS' if results['记忆生效'] else 'FAIL'}] 记忆生效 forecast_days={forecast} (期望 7) calls={[(n, a.get('forecast_days')) for n, a in collect_calls(out['state']['messages'])]}")

    # ---- 2) 黄金问答生成式答案 grounding ----
    g3 = build_react_graph(model=None, mode="OPERATIONS", checkpointer=InMemorySaver())
    grounding_ok = []
    for case in GOLD["cases"]:
        cid = case["id"]
        if cid not in GOLD_KEYWORDS:
            continue
        out = run_agent_react(g3, f"G-{cid}", sess, case["query"])
        ans = out["response"]["message"]
        kws = GOLD_KWS[cid]
        hit = any(k in ans for k in kws)
        grounding_ok.append((cid, hit))
        print(f"[{'PASS' if hit else 'FAIL'}] {cid} {case['query']!r}")
        print(f"        answer: {ans[:110]!r}")
    results["黄金问答grounding"] = bool(grounding_ok) and all(h for _, h in grounding_ok)

    clear_memory(1)
    ok = all(results.values())
    print(f"\n结果: {sum(results.values())}/2")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
