"""运行时配置（P2-1：支持环境变量覆盖，缺省回落本地 dev 值）。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# 分析时钟（S2 §0）：数据截至该日；所有销量窗/DOI/补货相对此日计算，不用真实 now()
AS_OF_DATE = os.getenv("AS_OF_DATE", "2026-09-17")

# Docker PG（db/docker-compose.yml）：端口 5434；可用环境变量 DB_DSN 覆盖（如指向测试库）
DB_DSN = os.getenv("DB_DSN", "postgresql://ec:ec_secret@localhost:5434/ec_copilot")
