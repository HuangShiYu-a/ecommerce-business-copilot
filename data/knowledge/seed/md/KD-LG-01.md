---
doc_id: KD-LG-01
title: 发货时效与物流异常处理
knowledge_type: logistics
layer: platform
platform: default
store_id: 0
status: ACTIVE
version: "1.0"
effective_from: "2026-01-01"
effective_to: null
source_type: internal_simulated
source_uri: null
scope:
  category_codes: []
  include_tags: []
  exclude_tags: []
---

## [delivery] 发货时效承诺

发货时效以订单承诺为准（承诺发货时间 `promised_ship_at`、承诺送达时间 `promised_delivery_at`）。常规订单应在承诺发货时间前完成发货。

## [delivery] 运单与轨迹

发货后生成运单与物流轨迹，轨迹事件按发生时间顺序记录；缺少关键轨迹事件时，时效无法判定。

## [delay] 延误认定

超过承诺送达时间仍未送达，认定为延误；物流轨迹停滞、长时间无进展，作为异常候选处理。

## [delay] 异常处理原则

确认延误后：告知消费者预计送达时间；提供补发、退货或退款选项；无法按时处理时升级人工客服跟进。
