# knowledge/seed — Knowledge 人工稿（S3.5 导入）

本目录是 Knowledge 轨（方案 A）的正文产出目录：由用户 Knowledge 窗口人工编写、人工审核，供 **S3.5 导入器** 消费写入 `knowledge_documents` / `knowledge_chunks`。

**上游契约（只读）：**
- [K3 元数据契约](../../docs/knowledge-seed-contract-v1.md) —— 字段语义 / 生命周期 / store_id 哨兵 / section 注册表 / scope / 治理
- [S2 V1.0.5 §9](../../docs/synthetic-data-design-v1.md) —— 10 篇清单与 conflict 构造约束
- [S2 V1.0.5 §6.1](../../docs/synthetic-data-design-v1.md) —— 8 类目 code
- Database §13.21 · RAG V1.0（§4/§5）· AGENTS §15

---

## 1. 目录布局

```text
data/knowledge/seed/
├── README.md          # 本约定（K5：文件格式 + 切块约定）
├── manifest.yaml      # 治理字段 + 多格式文档元数据（R1.2 扩展，K3 §6）
├── md/                # 一篇一文件：YAML front matter + Markdown 正文（12 篇）
│   ├── KD-AS-01.md    # 原 10 篇迁移至此（R1.1）
│   ├── KD-OP-03.md    # 新增 md（R1.2）
│   └── KD-AS-09.md
└── docs/              # 多格式文档（R1.2；元数据在 manifest.yaml）
    ├── pdf/   KD-AS-05.pdf, KD-LG-02.pdf, KD-LG-03.pdf, KD-INV-02.pdf
    ├── html/  KD-AS-06.html, KD-LG-04.html, KD-OP-02.html, KD-AS-07.html
    └── docx/  KD-CS-01.docx, KD-CS-02.docx, KD-AS-08.docx
```

**格式说明（R1.2）**：
- `md/`：md 正文，元数据在 **front matter**（导入器读 front matter）。
- `docs/`：PDF/HTML/DOCX，**元数据在 manifest.yaml**（`format/path/layer/effective/scope` 等，导入器读 manifest）；正文标题层级供结构感知切块（§7.1 切分细则）。
- 共 **23 篇**（12 md + 11 多格式）。

---

## 2. 每篇文件格式

一篇一个 `.md`：**YAML front matter（元数据）** + **Markdown 正文（按条款切 chunk）**。

```markdown
---
doc_id: KD-AS-01
title: 七日无理由退货底线
knowledge_type: after_sales
layer: legal
platform: default
store_id: 0
status: ACTIVE
version: "1.0"
effective_from: "2026-01-01"
effective_to: null
source_type: official
source_uri: "https://…（source_type=official 必填真实来源）"
scope:
  category_codes: []
  include_tags: []
  exclude_tags: []
---

## [return] 退货适用范围
（一条款 = 一个 chunk。本段写适用范围。）

## [return] 七日无理由规则
（本段写正规则。）
```

**front matter 字段清单**（语义见 K3 §1/§3/§5/§6，此处只列格式要点）：

| 字段 | 格式要求 |
|------|----------|
| `doc_id` | `KD-<域>-<NN>`，10 篇固定（K3 §8） |
| `knowledge_type` / `layer` / `platform` / `store_id` | 按 K3 §8 登记表逐字 |
| `effective_from` / `effective_to` | `"YYYY-MM-DD"`；`effective_to` 长期有效写 `null` |
| `version` | **必须引号** `"1.0"`，防 YAML 解析成浮点 |
| `scope` | 三键结构；KD-AS-04 `exclude_tags`、CONF 对 `include_tags`（K3 §5） |
| `source_type` / `source_uri` | KD-AS-01=official + 非空 URI；其余 internal_simulated（URI 可空） |
| 其余字段 | 按 K3 §8；新增字段需先在 K3 登记，禁止自由扩展 knowledge_type/layer |

---

## 3. 切块约定（K-B）

1. **一个 `## [section] 条款标题` = 一个 chunk 边界**；一意一段，一条款 ≈ 一 chunk（RAG §5）。
2. `[section]` 必须是 K3 §4 注册表内的键（如 `[return]`、`[non_returnable]`、`[delivery]`）。`chunk_index` 由导入器按出现顺序分配（1..n），**文件不写**。
3. **禁止**无脑定长截断把一条规则劈成两半；**禁止**整库单 chunk；chunk 尽量短（一段内自足）。
4. chunk 元数据**继承**文档（scope 复制进每 chunk 的 `metadata`，K3 §5/§9）；生命周期真相只存 document 列，chunk 不冗余。

---

## 4. 正文统一结构（模板）

按文档类型套用，每节一个 chunk（节标题即 `## [section] 标题`）：

```text
适用范围 → 正规则 → 例外 → 凭证/时效 → 冲突/升级说明
```

- **after_sales**：适用范围 / 七日窗口 / 例外类目 / 完好与凭证 / 冲突升级 —— 对齐 CS-08 资格判定顺序。
- **logistics**：发货时效承诺 / 异常处理规则 —— 对齐 CS-06。
- **operations / inventory**：维度说明与类目例外 / 备货文字政策（**无数值**）。

---

## 5. 生命周期与时钟

- 按 K3 §2：ACTIVE 篇 `effective_from ≤ as_of_date(2026-09-17)`、`effective_to` 为 `null` 或 `> as_of`；EXP 篇 `effective_to ≤ as_of` 且 `status=ACTIVE`（只触发时间分支）。
- **数值旋钮（lead_time / 阈值 / 权重）只进 StoreConfig，禁止写入任何正文**（S2 §7.5 / RAG §2.3）。

---

## 6. manifest.yaml

存放**非 DB 列**的治理/扩展字段（K3 §6），导入器忽略未知字段：

```yaml
# knowledge/seed manifest：非 DB 列的治理/扩展字段；K3 §6。
# source_type/source_uri 已在各篇 front matter，不重复。
documents:
  - doc_id: KD-AS-01
    source_title: "…（official 篇溯源标题）"
    retrieved_at: "2026-09-18"
    author: "user"
    reviewed_by: "user"
    notes: ""
```

---

## 7. 落盘自检（写每篇后对照 K3 §10）

1. 10 篇齐全，doc_id / type / layer / section 合法；
2. ACTIVE 在窗内；EXP `effective_to ≤ as_of`；
3. store_id 正确（全局 0 / STORE_01）；
4. KD-AS-04 `exclude apparel-conflict-test`，CONF 对 `include apparel-conflict-test`；
5. KD-AS-01 official + 非空 `source_uri`；
6. 正文无 Config 数值。

---

## 8. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0 | 2026-09-18 | K5 首版：文件格式（front matter + 正文）、切块约定（## [section] = chunk）、正文模板、manifest、自检清单；替换 S3.0 占位 |
