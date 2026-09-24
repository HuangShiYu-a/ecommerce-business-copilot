"""UI Workbench 启动入口（Phase 6）：ReAct 图工厂（默认）或 legacy（AGENT_BACKEND=legacy）。

运行（仓库根目录）：
  python -m web.main        # 推荐（以模块运行，仓库根自动进 sys.path）
  python web/main.py        # 亦可用（下方 sys.path 注入保证 web 包可导入）
→ http://127.0.0.1:8000
ReAct 默认：ReactGraphFactory（PostgresSaver，线程跨重启续跑）。
legacy 回退：AGENT_BACKEND=legacy 走 build_runtime_graph + run_agent。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # 直接运行脚本时保证仓库根在 sys.path

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
