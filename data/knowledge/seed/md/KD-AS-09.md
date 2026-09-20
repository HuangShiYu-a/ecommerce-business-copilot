---
doc_id: KD-AS-09
title: 特殊售后场景处理（赠品/套装/优惠分摊）
knowledge_type: after_sales
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

> 本文处理退货中的特殊场景（赠品 / 套装 / 优惠分摊）。商品**完好标准**以 KD-AS-03 为准，本文只补充特殊场景的分摊与返还口径，不重写 KD-AS-03。

## [special] 赠品退货口径

- 主商品退货时，随单赠送的赠品应一并退回；赠品缺失或已使用的，按赠品价值从退款中扣除。
- 赠品本身属法定不可退类目（参见 KD-AS-01 法定不适用情形）的，不作为主退货的阻碍，仅作赠品价值扣除。
- 赠品价值以订单中赠品成本口径记录为准。

## [special] 套装退货

- 套装整体退货：按套装备注的套装价整体退款。
- 套装部分退货：仅主件可单独退（引用 KD-AS-02 类目规则），赠件/配件须随主件；部分退款按套装分摊比例计算。

## [special] 优惠分摊退货

- 订单使用优惠（满减 / 券 / 会员折扣）后部分退货时，退款金额按**实付比例分摊**：单件应退金额 = 单件实付价（优惠前单价 × 分摊系数）。
- 分摊系数 = 订单实付总额 / 订单优惠前总额；禁止按优惠前单价全额退款（防止超退）。

## [special] 与既有规则的关系

- 退款时效、运费规则见 KD-AS-01（本文不重写）；完好标准与凭证简化见 KD-AS-03（本文引用）。
