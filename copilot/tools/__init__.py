"""Tool 实现（导入即注册到 TOOLS）。"""
from __future__ import annotations

from .check_return_eligibility import CheckReturnEligibility
from .create_return_request import CreateReturnRequest
from .fulfillment_delay import AnalyzeFulfillmentDelay
from .get_order import GetOrder
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
           "QueryProductPerformance", "AnalyzeFulfillmentDelay", "GetShippingStatus",
           "CheckReturnEligibility", "CreateReturnRequest", "GetOrder"]
