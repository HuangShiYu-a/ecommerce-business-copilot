---
doc_id: KD-AS-02
title: 例外商品/不可退类目
knowledge_type: after_sales
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

## [non_returnable] 法定不可退类目

下列类目为法定排除，不支持七日无理由退货：`customized` 定作类（按消费者要求定制的商品）、`fresh` 食品/生鲜类（鲜活易腐）。

## [non_returnable] 平台补充不可退类目

下列类目为本平台补充的不可退情形：`beauty` 美妆/个护类（拆封后影响卫生安全）；`books` 中的音像制品（拆封后不可退，普通图书除外）；`apparel` 下的贴身衣物（标识 `apparel-intimate`，试穿/拆封后影响卫生，普通服饰除外）。

## [non_returnable] 有条件可退类目

`electronics` 数码/电子类拆封激活后价值贬损较大：退货需未激活且完好，或按激活后价值贬损情形由人工判定。
