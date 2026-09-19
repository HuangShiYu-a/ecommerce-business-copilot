# E-commerce Business Copilot — Knowledge Seed 增强计划（方案 A）

版本：V1.0 · 状态：计划（待评审）· 日期：2026-09-19

**文档定位**：Knowledge 种子库从「10 篇纯 md」增强为「**15-25 篇多格式**（PDF/HTML/DOCX/md）」，并改造 importer 支持**格式感知摄取**。目标：覆盖 RAG 摄取管线最真实的工程点（格式解析/结构切块/元数据治理），支撑检索评测与 CS-08。基于已确认的方案 A 与决策 D1-D8、D-A~D-D。

---

## 1. 定位与目标

- 知识种子从「合成文本资产」升级为「**多格式企业知识资产**」，贴近真实企业知识库（政策 PDF / 内部 SOP / 培训文档混杂）。
- importer 从「md-only」升级为「**格式识别 + 解析 + 统一结构切块**」。
- **不引入外部真实文档**（避免版权 + 与合成业务错位）；内容为合成业务知识，与 S2/S3 场景一致。
- 与 RAG 检索（阶段 3）衔接：文档就绪后编纂黄金问答（rag_gold.yaml，Spec-3）。

## 2. 文档清单（主体）

**现有 10 篇（md，迁移至 `seed/md/`，内容不动）**

| doc_id | 域 | layer | 说明 |
|---|---|---|---|
| KD-AS-01 | after_sales | legal | 七日无理由退货底线（法定不适用/完好/价款返还）|
| KD-AS-02 | after_sales | platform | 平台补充不可退类目 |
| KD-AS-03 | after_sales | platform | 完好标准 + 凭证简化 + 赠品 |
| KD-AS-04 | after_sales | store | electronics 耳机类店规（R3 载体，7 日窗口）|
| KD-LG-01 | logistics | store | 物流时效规则（无数值，以订单承诺为准）|
| KD-OP-01 | operations | store | 商品健康度五维（traffic 恒缺 / margin 口径）|
| KD-INV-01 | inventory | store | 备货原则 + 补货确认流程 |
| KD-AS-EXP-01 | after_sales | store | 已过期夹具（effective_to=2026-08-31，R1 时间分支）|
| KD-AS-CONF-01/02 | after_sales | store | 冲突对（7 日/15 日，R5，scope=apparel-conflict-test）|

**新增 13 篇（多格式 + 少量 md）**

| doc_id | 格式 | 域 | layer | 生效 | 核心规则 | 防冲突 |
|---|---|---|---|---|---|---|
| KD-AS-05 | PDF | after_sales | platform | 2026-01-01~ | 退货退款流程总则（申请入口/审核/到账时效）| 不重写 AS-01 运费规则，只引用 |
| KD-LG-02 | PDF | logistics | store | ~2026-08-31 | **物流时效承诺 v1.0（过期，R1 版本链 A）**| 与 LG-03 同 family |
| KD-LG-03 | PDF | logistics | store | 2026-09-01~ | **物流时效承诺 v2.0（现行，R1 版本链 B）**| 与 LG-02 同 family |
| KD-INV-02 | PDF | inventory | platform | 2026-01-01~ | 库存分类/盘点周期/数据口径 | 不重写 INV-01 备货原则 |
| KD-AS-06 | HTML | after_sales | store | 2026-01-01~ | 售后处理 SOP（接待→核实→判定→处理→回访）| 只走流程，不重写资格规则 |
| KD-LG-04 | HTML | logistics | store | 2026-01-01~ | 物流异常处理 SOP（延误/滞留/丢件）| 引用 LG-01，不重写时效 |
| KD-OP-02 | HTML | operations | store | 2026-01-01~ | 运营巡检 SOP（库存→销量→异常→健康度）| 引用 OP-01 |
| KD-AS-07 | HTML | after_sales | store | 2026-01-01~ | 退款审核 SOP（金额/凭证核实）| 引用 AS-03 |
| KD-CS-01 | DOCX | customer_service | store | 2026-01-01~ | 客服话术手册（退货/物流常见问答）| 话术，不重写政策 |
| KD-CS-02 | DOCX | customer_service | store | 2026-01-01~ | 工单操作手册（创建/流转/升级）| 新域 |
| KD-AS-08 | DOCX | after_sales | platform | 2026-01-01~ | 售后质检培训（服务评分标准）| 新内容 |
| KD-OP-03 | md | operations | store | 2026-01-01~ | 滞销商品处理规则（支持 OP-03）| 新内容，不重写 OP-01 |
| KD-AS-09 | md | after_sales | platform | 2026-01-01~ | 特殊售后场景（赠品/套装/优惠分摊退货）| 引用 AS-03 |

**格式分布**：PDF 4 · HTML 4 · DOCX 3 · md 12（现有 10 + 新增 2）→ 总计 **23 篇**（符合 15-25）。

**新增 `customer_service` 域**：新增知识类型，扩展 knowledge_type 枚举（DB VARCHAR，无需迁移）。

## 3. 版本对设计（R1 演示）

- **KD-LG-02（v1.0，effective_to=2026-08-31，已过期）** 与 **KD-LG-03（v2.0，effective_from=2026-09-01，现行）** 组成**版本对**（`family: KD-LG`）。
- R1「仅当前有效文档参与判定」：检索时按生效日期过滤，v1.0 不得命中；v2.0 命中。
- 与 KD-AS-EXP-01（单篇过期）互补：版本对演示**同主题的版本链**检索。

## 4. 防冲突机制

1. **单一事实来源**：每条规则只在一篇文档定义，其他文档**引用不重写**（引用格式：`参见 KD-AS-01`）。
2. **保留唯一冲突对**：KD-AS-CONF-01/02（7 日/15 日）为 R5 演示的刻意冲突；其余文档与其无关联、互不冲突。
3. **生成后脚本校验**：抽取每篇规则关键词交叉比对，断言除 CONF 对外无矛盾（见 §8）。

### 4.1 内容边界细则（防冲突的写作红线）

| 主题 | 现有文档 | 新增文档 | 写作红线 |
|---|---|---|---|
| 物流时效 | KD-LG-01（无数值，时效以订单承诺为准）| KD-LG-02/03 时效承诺政策 | **不写具体时效数值**（如"3 天达"）；只写承诺框架（分级/变更/异常责任/查询方式），具体时效引用 LG-01 |
| 退货退款 | KD-AS-01（法定 7 日内返还价款）| KD-AS-05 退款流程总则 | 只写流程性内容（申请入口/审核步骤/到账路径）；法定 7 日规则**引用 AS-01 不重述**，避免"审核通过后 X 日到账"与法定时效矛盾 |
| 滞销 | KD-OP-01（健康度五维含慢销维度）| KD-OP-03 滞销处理规则 | 只写**处理流程/动作**（标记滞销、调价/清仓/下架）；滞销**判定标准**由 calc + OP-01 承担，引用不重写 |

## 5. 元数据规范（manifest 扩展）

新增文档无 YAML frontmatter → **manifest.yaml 集中声明元数据**（D2）：

```yaml
documents:
  - doc_id: KD-AS-05
    format: pdf                     # pdf | html | docx | md
    path: docs/pdf/KD-AS-05.pdf     # 相对 seed/
    title: 退货退款政策总则
    knowledge_type: after_sales
    layer: platform
    platform: default
    store_id: 0
    status: ACTIVE
    version: "1.0"
    effective_from: "2026-01-01"
    effective_to: null
    family: null                    # 版本对填 family（如 KD-LG）
    scope: { category_codes: [], include_tags: [], exclude_tags: [] }
    notes: 防冲突声明（引用哪些文档/不重写哪些）
```

- 现有 md 文档**保留 frontmatter**（importer 读 frontmatter）；新增文档元数据走 manifest。
- section 标签（新格式）：**标题层级归一化 slug**，不做手工 `[tag]`（D5）；layer 由 manifest 声明。

## 6. 目录结构（D-A）

```
data/knowledge/seed/
├── md/                      # 现有 10 篇迁移 + 新增 2 篇 md
│   ├── KD-AS-01.md … KD-OP-01.md, KD-AS-EXP-01.md, KD-AS-CONF-01/02.md
│   ├── KD-OP-03.md          # 新增
│   └── KD-AS-09.md          # 新增
├── docs/
│   ├── pdf/   KD-AS-05.pdf, KD-LG-02.pdf, KD-LG-03.pdf, KD-INV-02.pdf
│   ├── html/  KD-AS-06.html, KD-LG-04.html, KD-OP-02.html, KD-AS-07.html
│   └── docx/  KD-CS-01.docx, KD-CS-02.docx, KD-AS-08.docx
└── manifest.yaml            # 扩展：声明全部新增文档元数据
```

**迁移连带**：importer 读取路径、test_importer 路径引用、README 同步更新。

## 7. importer 改造范围（D8 / D-D）

- 新增依赖：`pypdf` / `python-docx` / `beautifulsoup4`。
- `data/generator/importer.py`：加**格式识别**（扩展名/文件头）→ 分发到解析器 → 统一结构块。
- 新增 `data/generator/parsers.py`：
  - `parse_pdf`：pypdf 提取文本 + 标题识别（字号/行模式）；标题不可靠时退化段落级切块 + manifest 声明章节。
  - `parse_html`：BeautifulSoup 按 h1-h3/p/table 提结构块。
  - `parse_docx`：python-docx 按 Heading 样式/段落/表格提结构块。
- **统一结构块** → 按标题边界切 chunk（泛化 `## [section]`）→ 输出与现有 canonical（knowledge_documents/chunks CSV）**完全兼容**。
- **md 路径不回归**：现有 10 篇 md 解析逻辑不变（frontmatter + `## [section]`），测试全过。

## 8. 校验与评测衔接

- **防冲突校验脚本**：遍历所有文档 → 抽规则关键词 → 交叉比对 → 断言仅 CONF 对冲突。
- **validate 扩展**：新增格式解析完整性检查（每篇至少产出一个 chunk；元数据齐全）。
- **rag_gold.yaml**（Spec-3 语料）：文档就绪后编纂黄金问答，覆盖 R1 版本链 / R3 店规 / R5 冲突等。

## 9. 实施步骤与验证

| 步骤 | 内容 | 验证 |
|---|---|---|
| S1 | 建 `seed/md/`、`seed/docs/{pdf,html,docx}`，迁移现有 10 篇 md | 迁移后 importer 全量测试通过 |
| S2 | 扩展 manifest.yaml + 新增 13 篇文档内容（含版本对）| 防冲突脚本通过 |
| S3 | 新增 `parsers.py` + 扩展 importer（格式层）| 23 篇全部产出 chunk；md 不回归 |
| S4 | 更新 test_importer / README / validate | 全量测试通过 |
| S5 | 产出 canonical + 导入 PG | DB 知识表行数 = 23 篇 |

> 注：S1-S5 属**数据侧任务**（S3 知识导入扩展），可与 Runtime 阶段 1 并行。
