"""UI Workbench 启动入口（Phase 6）：ReAct 图工厂（默认）或 legacy（AGENT_BACKEND=legacy）。

运行：python web/main.py → http://127.0.0.1:8000
ReAct 默认：ReactGraphFactory（PostgresSaver，线程跨重启续跑）。
legacy 回退：AGENT_BACKEND=legacy 走 build_runtime_graph + run_agent。
"""
from __future__ import annotations

import os

from nicegui import ui

from web.app import build_page


def main():
    if os.getenv("AGENT_BACKEND") == "legacy":
        from copilot.agent.orchestrator import build_runtime_graph
        runtime = build_runtime_graph()
    else:
        from copilot.agent.graph_factory import ReactGraphFactory
        runtime = ReactGraphFactory()
    build_page(runtime)
    ui.run(host="127.0.0.1", port=8000, title="E-commerce Copilot")


if __name__ in {"__main__", "__mp_main__"}:
    main()
