"""Tool 实现（导入即注册到 TOOLS）。"""
from __future__ import annotations

from .fulfillment_delay import AnalyzeFulfillmentDelay
from .inventory import GetInventory
from .knowledge import SearchBusinessKnowledge
from .product_health import CalculateProductHealth
from .product_performance import QueryProductPerformance
from .restock import CalculateRestockRecommendation
from .sales_anomaly import AnalyzeSalesAnomaly
from .shipping_status import GetShippingStatus
from .stockout import AnalyzeStockoutRisk

__all__ = ["GetInventory", "AnalyzeStockoutRisk", "CalculateRestockRecommendation",
           "SearchBusinessKnowledge", "CalculateProductHealth", "AnalyzeSalesAnomaly",
           "QueryProductPerformance", "AnalyzeFulfillmentDelay", "GetShippingStatus"]
