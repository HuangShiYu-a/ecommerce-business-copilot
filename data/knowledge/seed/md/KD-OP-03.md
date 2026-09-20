---
doc_id: KD-OP-03
title: 滞销商品处理规则
knowledge_type: operations
layer: platform
platform: default
store_id: 0
status: ACTIVE
version: "1.0"
effective_from: "2026-01-01"
effective_to: null
source_type: internal
scope:
  category_codes: []
  include_tags: []
  exclude_tags: []
---

> 本文定义滞销商品的**处理流程**（标记后 → 分析 → 处理动作 → 复盘）。滞销**判定标准**（阈值/窗口）以商品健康度计算（OP-01 §health_dimensions）与确定性计算服务为准，本文不重写。

## [slow_moving] 滞销标记后的处理流程

1. **确认判定**：运营人员以商品健康度分析结果为滞销候选后，复核销量窗口与库存数据，确认进入处理流程。
2. **原因分析**：区分「真滞销」（需求萎缩）与「伪滞销」（断货/价格异常/类目错配导致暂时低销），伪滞销不进入清仓，先修复上架状态。
3. **处理动作（按严重度递进）**：
   - 轻度滞销：调整陈列权重 / 加入组合促销（引用 KD-OP-01 促销口径）；
   - 中度滞销：限时降价（调价动作需经补货/价格规则确认，见 KD-INV-01 确认流程）；
   - 重度滞销：下架或清仓，清仓价不得低于成本价下限（口径见 KD-OP-01 margin）。
4. **复盘**：处理 14 天后评估销量/库存变化，未改善则升级为下架候选。

## [slow_moving] 处理边界

- 食品/生鲜（fresh）与母婴（baby）类目因效期/安全约束，滞销处理**不适用**无下限清仓，须人工审核（引用 KD-OP-01 类目例外）。
- 滞销处理为**运营建议**，实际调价/下架为写操作，须经人工确认后执行。
