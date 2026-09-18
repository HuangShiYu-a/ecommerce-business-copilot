---
doc_id: KD-OP-01
title: 健康维度说明与类目例外
knowledge_type: operations
layer: store
platform: default
store_id: STORE_01
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

## [health_dimensions] 核心维度说明

商品健康度由五个核心维度衡量：销量、库存、毛利、退货、反馈。各维度的权重由配置决定，本说明仅描述维度含义，不含具体权重。

## [health_dimensions] 可选维度说明

`traffic`（流量）为可选维度，当前数据源未提供。缺失该维度不影响核心维度判定，仅作标注。

## [health_dimensions] 毛利口径说明

毛利以成本价近似：毛利 = 售价 − 成本价（`cost_price`）。无成本价的商品，毛利维度视为缺失。

## [health_dimensions] 类目例外

`fresh` 食品/生鲜类保质期敏感，退货与评价异常需人工复核；`baby` 母婴/玩具类涉及安全，反馈与退货异常优先人工复核；`customized` 定作类与 `fresh` 类不适用常规毛利维度评价。
