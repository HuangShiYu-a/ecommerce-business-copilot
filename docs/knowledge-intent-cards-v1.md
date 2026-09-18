# E-commerce Business Copilot — Knowledge 意图卡 V1.0（K6 第一步）

> 文档性质：**意图卡草稿**——每篇正文的「业务意图」供用户拍板；拍板后据此成稿正文（`data/knowledge/seed/KD-*.md`）  
> 版本：V1.0  
> 状态：Draft（待用户拍板各【你拍板】点）  
> 上游（只读）：S2 V1.0.5（§6.1 类目 / §9 清单与构造约束）· [K3](./knowledge-seed-contract-v1.md)（元数据）· [K5](../data/knowledge/seed/README.md)（格式/切块）· RAG V1.0 · Business V1.1 §1.6  
> 规则：数值只进 StoreConfig；禁止 AI 自造标 official（除 KD-AS-01 由 K4 忠实溯源）；内容不得违反 Frozen 契约

---

## 1. KD-AS-01 七日无理由退货底线

- **元数据**：`after_sales` / `legal` / store_id=`0` / section=`return` / scope=全局 / `source_type=official`
- **服务**：CS-08（legal 层，R4 权威最高层；作为底线不得被店规压过）
- **规则要点（正文由 K4 单独实施，此处仅确认意图）**：
  - 网络购买商品自签收次日起 7 日内可无理由退货；
  - 法定排除：定作（customized）、鲜活易腐（fresh）、在线下载/拆封的音像制品与数字化商品（books 音像）、报纸期刊；
  - 经确认可不退的补充情形、运费规则——以法规忠实摘记为准；
  - 附「非法律意见」声明 + `source_uri`。
- **【你拍板】**：无（正文单独 K4；此处确认依据 = 消保法 §25 + 七日暂行办法）。

---

## 2. KD-AS-02 例外商品/不可退类目

- **元数据**：`after_sales` / `platform` / store_id=`0` / section=`non_returnable` / scope=全局 / `source_type=internal_simulated`
- **服务**：CS-08 ineligible（R2 排除）、KD-AS-04 引用
- **规则要点（草稿）**：
  - **法定不可退（平台转述底线）**：`customized` 定作类、`fresh` 鲜活易腐类；
  - **平台补充不可退（模拟规则，Business §1.6 授权）**：`beauty` 美妆/个护（拆封影响卫生安全）、`books` 音像制品（拆封后不可退；**普通图书可退**）；
  - **贴身衣物（用户 2026-09-18 采纳）**：`apparel` 下贴身衣物（product-type tag `apparel-intimate`，K3 §5 注册）平台列为不可退（卫生考虑）；**普通服饰可退**；
  - **特殊条款**：`electronics` 拆封激活后价值贬损较大——可退但须**未激活/完好**（与 KD-AS-03 联动）。
- **【已拍板】**：① 平台补充不可退 = `beauty` + `books`音像 + `apparel`贴身衣物；② `electronics` 有条件可退；③ 贴身衣物经 K3 §5 注册 tag 并同步 S3 P2 造数。

---

## 3. KD-AS-03 完好要求与凭证

- **元数据**：`after_sales` / `platform` / store_id=`0` / section=`condition` / scope=全局 / `source_type=internal_simulated`
- **服务**：CS-08 资格输入（完好/凭证判定）
- **规则要点（草稿）**：
  - **完好标准**：商品、配件、赠品齐全；标签、包装未损毁；未经使用/洗涤/穿着（服装类）；未经拆封（美妆/数码类，见 KD-AS-02 特殊条款）；
  - **凭证**：订单号系统可查 + 退货商品与原订单一致；赠品未返还按价值扣除（可简化）；
  - **不适用**：customized/fresh 本就不可退，不适用完好条款。
- **【你拍板】**：① 完好标准明细是否采纳？② 凭证要求是否简化为「订单可查 + 商品完好」？③ 赠品是否要求一并退回？

---

## 4. KD-AS-04 店铺补充售后政策（STORE_01）

- **元数据**：`after_sales` / `store` / store_id=`STORE_01` / section=`return` / scope=全类目 **exclude `apparel-conflict-test`** / `source_type=internal_simulated`
- **服务**：CS-08/09 资格主规则（STORE_01）；**R3 特异性载体**
- **规则要点（草稿）**：
  - **店铺默认窗口**：签收后 **7 日内**可退（与平台/法定一致，简单不冲突）——【你拍板】也可选 15 日（更宽，测 R4「店规比平台宽 OK」）；
  - **特殊类目店规（R3 载体）**：`electronics` 下「耳机类」签收后 7 日内可退（凭完好）——比平台一般条款**更具体** → R3 命中；
  - **店铺补充**：无理由退货运费由消费者承担；`home` 大件支持上门取件；赠品需一并退回；
  - **scope 互斥**：exclude `apparel-conflict-test`（K3 §5），不影响 SC-CS08-007。
- **【你拍板】**：① 默认窗口 7 日 or 15 日？② 「耳机类」具体规则措辞？③ 补充政策（运费/取件/赠品）是否采纳？

---

## 5. KD-LG-01 发货时效与物流异常处理

- **元数据**：`logistics` / `platform` / store_id=`0` / section=`delivery`+`delay` / scope=全局 / `source_type=internal_simulated`
- **服务**：CS-06（NORMAL / ANOMALY / UNDETERMINED 判定后的规则支撑）
- **规则要点（草稿）**：
  - **delivery**：发货时效以**订单承诺**（`promised_ship_at`/`promised_delivery_at`，业务数据）为准；发货后生成运单与轨迹；**不写固定小时数**（避免与 Config 冲突）；
  - **delay**：超过承诺送达时间未送达 = 延误；轨迹停滞、无进展 = 异常候选；**不写「停滞 N 天」数值**（异常阈值属 Config/计算，RAG 禁止正文写数字）；
  - **处理原则**：确认延误→告知预计→提供补发/退货/退款选项→升级人工（文字规则）。
- **【你拍板】**：① 是否接受「不写任何数值、时效以订单承诺为准」的写法（最干净，避免 Config 冲突）？② 异常处理选项（补发/退货）与升级话术原则是否采纳？

---

## 6. KD-OP-01 健康维度说明与类目例外

- **元数据**：`operations` / `store` / store_id=`STORE_01` / section=`health_dimensions` / scope=STORE_01 / `source_type=internal_simulated`
- **服务**：OP-07（健康分**文字说明**；权重在 StoreConfig）
- **规则要点（草稿）**：
  - **五核心维说明**（sales / inventory / margin / return / feedback）+ 可选 `traffic` 恒缺失说明（DB-G01，缺可选不降核心）——**只写维度含义，不写权重**；
  - **margin 口径**：以成本价近似毛利（`selling_price − cost_price`），对应「利润」维；
  - **类目例外**：`fresh` 保质期敏感——退货/评价异常需**人工复核**；`baby` 安全类——反馈/退货异常**优先人工复核**；`customized`/`fresh` 无常规毛利评价基础。
- **【你拍板】**：① 类目例外范围是否 = fresh（人工复核）+ baby（优先人工）？② 措辞是否采纳？

---

## 7. KD-INV-01 库存/备货文字政策

- **元数据**：`inventory` / `store` / store_id=`STORE_01` / section=`replenishment_policy` / scope=STORE_01 / `source_type=internal_simulated`
- **服务**：OP-04/05 补货建议的**文字解释**（可选）
- **规则要点（草稿）**：
  - 畅销品维持安全库存、慢销/积压品谨慎补货、临期/保质期敏感品控量——**不写天数/数值**（数值在 StoreConfig）；
  - 超阈值补货需运营确认（文字流程规则）。
- **【你拍板】**：措辞是否采纳？

---

## 8. KD-AS-EXP-01 已过期夹具

- **元数据**：`after_sales` / `platform` / store_id=`0` / section=`return` / scope=全局 / `effective_to=2026-08-31`（≤ as_of）/ `source_type=internal_simulated`
- **服务**：生命周期过滤测试（R1）
- **内容（夹具，自拟即可）**：旧版平台政策——「所有退货须在签收后 **3 日内**申请」；已过期，检索应排除。
- **【你拍板】**：① 这条过期规则内容是否合理（3 日窗口）？② 过期原因（旧版被新版替代）是否在正文标注一句？

---

## 9. KD-AS-CONF-01 冲突对 A（签收 7 日内可退）

- **元数据**：`after_sales` / `store` / store_id=`STORE_01` / section=`return` / scope=`[apparel]`+include `apparel-conflict-test` / `source_type=internal_simulated`
- **服务**：SC-CS08-007（R5）
- **内容（构造已定，S2 §9 + K3 §5）**：适用 `apparel-conflict-test` 商品的退货窗口 = **签收后 7 日内**。
- **【你拍板】**：无（构造已定；正文只需按窗口成文）。

---

## 10. KD-AS-CONF-02 冲突对 B（签收 15 日内可退）

- **元数据**：`after_sales` / `store` / store_id=`STORE_01` / section=`return` / scope=`[apparel]`+include `apparel-conflict-test` / `source_type=internal_simulated`
- **服务**：SC-CS08-007（R5）
- **内容（构造已定）**：适用 `apparel-conflict-test` 商品的退货窗口 = **签收后 15 日内**。
- **【你拍板】**：无（构造已定）。

---

## 汇总：需要你拍板的决策点

| 文档 | 决策点 | 状态 |
|------|--------|------|
| KD-AS-02 | 平台不可退清单 | ✅ 已拍板（beauty + books音像 + apparel贴身衣物；electronics 有条件可退） |
| KD-AS-03 | 完好标准明细；凭证简化；赠品 | ✅ 已拍板（按推荐） |
| KD-AS-04 | 店窗口 7 日；耳机类措辞；补充政策 | ✅ 已拍板（按推荐） |
| KD-LG-01 | 无数值写法；异常处理选项 | ✅ 已拍板（按推荐） |
| KD-OP-01 | 类目例外范围；措辞 | ✅ 已拍板（按推荐） |
| KD-INV-01 | 措辞 | ✅ 已拍板（按推荐） |
| KD-AS-EXP-01 | 过期规则内容 | ✅ 已拍板（按推荐） |

拍板后我据此成稿 10 篇正文，落盘 `data/knowledge/seed/KD-*.md`（KD-AS-01 除外，留给 K4）。
