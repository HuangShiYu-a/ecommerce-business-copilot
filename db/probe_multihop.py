"""DeepSeek 条件多跳 ReAct spike（临时脚本，验证方案 B 成立性的最大未知数）。

模拟真实 ReAct 循环（无 LangGraph，纯 bind_tools 手动循环）：
  LLM 看 3 个工具 → 调工具 → 拿结果(observation) → 再决策 → 直到不调工具输出答案。

两个场景：
  S1 条件多跳正例：低库存 → 决定继续深挖原因 → 调销售异常 → 综合回答
  S2 条件早停：库存充足 → 无需深挖 → 直接回答（验证"条件性"而非无脑多跳）
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, r"D:\E-commerce Business Copilot")
from dotenv import load_dotenv
load_dotenv(Path(r"D:\E-commerce Business Copilot\.env"))

from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    temperature=0.0, timeout=60, max_retries=1,
)

# 镜像真实工具 schema + 描述
TOOLS = [
    {"type": "function", "function": {
        "name": "get_inventory",
        "description": "查询 SKU 当前可用库存与安全库存阈值。返回可用库存和安全库存。",
        "parameters": {"type": "object",
                       "properties": {"sku_code": {"type": "string"}},
                       "required": ["sku_code"]}}},
    {"type": "function", "function": {
        "name": "analyze_sales_anomaly",
        "description": "分析 SKU 最近 7 天销量相对基线是否异常（骤降或暴涨），返回异常方向与变化率。",
        "parameters": {"type": "object",
                       "properties": {"sku_code": {"type": "string"}},
                       "required": ["sku_code"]}}},
    {"type": "function", "function": {
        "name": "analyze_stockout_risk",
        "description": "按日均销量与可用库存估算 SKU 的缺货风险等级（HIGH/MEDIUM/LOW），返回预计几天后缺货。",
        "parameters": {"type": "object",
                       "properties": {"sku_code": {"type": "string"}},
                       "required": ["sku_code"]}}},
]

# 确定性 mock 数据（模拟工具返回）
MOCK = {
    "get_inventory": {
        "SKU_01_STOCKOUT_01": {"sku_code": "SKU_01_STOCKOUT_01", "available_qty": 8, "safety_stock": 20},
        "SKU_01_NORMAL_01":   {"sku_code": "SKU_01_NORMAL_01", "available_qty": 150, "safety_stock": 20},
    },
    "analyze_sales_anomaly": {
        "SKU_01_STOCKOUT_01": {"sku_code": "SKU_01_STOCKOUT_01", "is_anomaly": True, "direction": "rise", "change_pct": 38},
        "SKU_01_NORMAL_01":   {"sku_code": "SKU_01_NORMAL_01", "is_anomaly": False, "direction": "flat", "change_pct": 2},
    },
    "analyze_stockout_risk": {
        "SKU_01_STOCKOUT_01": {"sku_code": "SKU_01_STOCKOUT_01", "risk_level": "HIGH", "days_until_stockout": 5},
        "SKU_01_NORMAL_01":   {"sku_code": "SKU_01_NORMAL_01", "risk_level": "LOW", "days_until_stockout": 90},
    },
}


def run_tool(name, args):
    sku = args.get("sku_code")
    data = MOCK.get(name, {}).get(sku, {"error": "NOT_FOUND"})
    return str(data)


def react_loop(user_msg, max_iters=6):
    """手动 ReAct 循环：LLM → tool_calls → mock 执行 → ToolMessage → 再决策。"""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    msgs = [HumanMessage(content=user_msg)]
    trace = []
    for i in range(max_iters):
        resp = llm.bind_tools(TOOLS).invoke(msgs)
        if not resp.tool_calls:
            return trace, str(resp.content or "")
        for tc in resp.tool_calls:
            out = run_tool(tc["name"], tc["args"])
            trace.append({"step": i, "tool": tc["name"], "args": tc["args"], "obs": out})
        msgs.append(resp)   # 直接复用带 tool_calls 的 AIMessage
        for tc in resp.tool_calls:
            msgs.append(ToolMessage(content=run_tool(tc["name"], tc["args"]), tool_call_id=tc["id"]))
    return trace, "MAX_ITER_REACHED"


CASES = [
    ("S1 条件多跳", "SKU_01_STOCKOUT_01 有没有缺货风险？如果有，帮我进一步分析原因"),
    ("S2 条件早停", "SKU_01_NORMAL_01 有没有缺货风险？如果有，帮我进一步分析原因"),
]

for label, msg in CASES:
    print("=" * 60)
    print(f"[{label}] 输入: {msg}")
    trace, final = react_loop(msg)
    if trace:
        for t in trace:
            print(f"  步骤{t['step']} → {t['tool']}({t['args']}) → 观察: {t['obs']}")
    else:
        print("  未调用任何工具")
    print(f"  最终回答: {final[:200]}")
