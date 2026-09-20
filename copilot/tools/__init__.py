"""Tool 实现（导入即注册到 TOOLS）。"""
from __future__ import annotations

from .inventory import GetInventory
from .knowledge import SearchBusinessKnowledge
from .restock import CalculateRestockRecommendation
from .stockout import AnalyzeStockoutRisk

__all__ = ["GetInventory", "AnalyzeStockoutRisk", "CalculateRestockRecommendation",
           "SearchBusinessKnowledge"]
