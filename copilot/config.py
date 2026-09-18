"""运行时配置。"""
from __future__ import annotations

# 分析时钟（S2 §0）：数据截至该日；所有销量窗/DOI/补货相对此日计算，不用真实 now()
AS_OF_DATE = "2026-09-17"

# Docker PG（db/docker-compose.yml）：端口 5434
DB_DSN = "postgresql://ec:ec_secret@localhost:5434/ec_copilot"
