"""S3.4 Scenario 绑定（P5）。

把 S2 §8.2 的 33 条黄金 SC 与生成数据绑定（稳定 ID），写入 data/scenarios/eval/scenarios.yaml。
- nature=data：引用完整解析（sku_ids / order_no / store_id）
- nature=runtime_eval：仅挂前置 ID，不断言进程（remarks 写明 harness 动作）
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import yaml

from .config import GeneratorConfig
from .master import RULES_DIR, load_yaml
from .transactions import _read_csv

SCENARIOS_PATH = Path(__file__).resolve().parent.parent / "scenarios" / "eval" / "scenarios.yaml"


def _first(rows, pred):
    for r in rows:
        if pred(r):
            return r
    return None


def _dt(v: str) -> datetime:
    return datetime.fromisoformat(v)


def _days_since(v: str, as_of: date) -> int:
    return (as_of - _dt(v).date()).days


def generate_scenarios(cfg: GeneratorConfig, canonical_dir: Path, output_root: Path) -> dict:
    as_of = date.fromisoformat(cfg.dataset.as_of_date)

    products = _read_csv(canonical_dir / "products.csv")
    skus = _read_csv(canonical_dir / "product_skus.csv")
    categories = _read_csv(canonical_dir / "product_categories.csv")
    orders = _read_csv(canonical_dir / "orders.csv")
    order_items = _read_csv(canonical_dir / "order_items.csv")
    after_sales = _read_csv(canonical_dir / "after_sales_requests.csv")
    sku_roles = _read_csv(output_root / cfg.profile.name / "sku_roles.csv")

    cats_def = load_yaml(RULES_DIR / "categories.yaml")["categories"]
    # 无条件可退类目（SC-CS08-001/002 eligible/ineligible 选择用）：
    # electronics 条件可退、beauty/books 平台特殊、customized/fresh 法定排除，均不纳入
    clean_returnable = {c["name"] for c in cats_def if c["code"] in ("apparel", "home", "baby")}

    sku_codes = {s["sku_code"] for s in skus}
    sku_by_id = {int(s["id"]): s for s in skus}
    # 排除 SKU：apparel-intimate（KD-AS-02 平台不可退）+ apparel-conflict-test（R5 冲突产品，
    # 其任意订单的资格查询都会命中 CONF 对 → 不得用作 eligible/ineligible 用例）
    excluded_sku_ids = set()
    for s in skus:
        attrs = json.loads(s["attributes"]) if s["attributes"] else {}
        if attrs.get("product_type") in ("apparel-intimate", "apparel-conflict-test"):
            excluded_sku_ids.add(int(s["id"]))
    prod_by_id = {int(p["id"]): p for p in products}
    cat_name_by_id = {int(c["id"]): c["name"] for c in categories}
    item_sku_by_order: dict[int, list[int]] = {}
    for it in order_items:
        item_sku_by_order.setdefault(int(it["order_id"]), []).append(int(it["sku_id"]))

    def category_of(order):
        ids = item_sku_by_order.get(int(order["id"]), [])
        if not ids:
            return None
        sku = sku_by_id.get(ids[0])
        prod = prod_by_id.get(int(sku["product_id"])) if sku else None
        return cat_name_by_id.get(int(prod["category_id"])) if prod else None

    def is_completed(o): return o["status"] == "COMPLETED"
    def has_delivered(o): return bool(o["delivered_at"])
    def has_signed(o): return bool(o["signed_at"])
    def has_pdd(o): return bool(o["promised_delivery_at"])

    def on_time(o):
        return is_completed(o) and has_pdd(o) and has_delivered(o) and has_signed(o) \
            and o["promised_delivery_at"] >= o["delivered_at"]

    def late(o):
        return is_completed(o) and has_pdd(o) and has_delivered(o) and has_signed(o) \
            and o["promised_delivery_at"] < o["delivered_at"]

    def missing_promised(o):
        return is_completed(o) and not has_pdd(o) and has_delivered(o) and has_signed(o)

    def delivered_not_signed(o):
        return is_completed(o) and has_delivered(o) and not has_signed(o)

    def overdue_shipped(o):
        return o["status"] == "SHIPPED" and has_pdd(o) and _dt(o["promised_delivery_at"]).date() < as_of

    def returnable(o):
        ids = item_sku_by_order.get(int(o["id"]), [])
        if ids and ids[0] in excluded_sku_ids:
            return False
        c = category_of(o)
        return c in clean_returnable

    def signed_within(o, days):
        return has_signed(o) and 0 <= _days_since(o["signed_at"], as_of) <= days

    def signed_older(o, days):
        return has_signed(o) and _days_since(o["signed_at"], as_of) > days

    order_on_time = _first(orders, on_time)
    order_late = _first(orders, late)
    order_missing_p = _first(orders, missing_promised)
    order_overdue = _first(orders, overdue_shipped)
    order_eligible = _first(orders, lambda o: on_time(o) and returnable(o) and signed_within(o, 6))
    order_ineligible = _first(orders, lambda o: is_completed(o) and returnable(o) and signed_older(o, 7))
    order_nsigned = _first(orders, delivered_not_signed)
    preexisting_as = _first(after_sales, lambda r: r["status"] in ("COMPLETED", "APPROVED"))
    preexisting_order_no = next(
        (o["order_no"] for o in orders if int(o["id"]) == int(preexisting_as["order_id"])),
        "")
    store2_order = _first(orders, lambda o: o["store_id"] == "2")
    conflict_order = next((o for o in orders if "CS0807" in o["order_no"]), None)

    required = {
        "on_time(NORMAL)": order_on_time, "late(ANOMALY)": order_late,
        "missing_promised": order_missing_p, "overdue_shipped": order_overdue,
        "eligible": order_eligible, "ineligible": order_ineligible,
        "delivered_not_signed": order_nsigned, "preexisting_after_sales": preexisting_as,
        "store2_order": store2_order, "conflict_order": conflict_order,
    }
    missing = [k for k, v in required.items() if v is None]
    if missing:
        raise RuntimeError(f"SC 绑定失败：找不到前置订单/数据 {missing}")

    def sc(scenario_id, workflow, nature, store_id, trigger, expected_route,
           expected_reason=None, sku_ids=None, order_no=None, description="",
           remarks="", expected_formal_result=None, input_scope=None):
        if sku_ids:
            unknown = [c for c in sku_ids if c not in sku_codes]
            if unknown:
                raise RuntimeError(f"{scenario_id}: 未知 sku_code {unknown}")
        return {
            "scenario_id": scenario_id, "workflow": workflow, "nature": nature,
            "description": description, "store_id": store_id,
            "sku_ids": sku_ids or [], "order_no": order_no or "",
            "input_scope": input_scope or {},
            "trigger_type": trigger, "expected_route": expected_route,
            "expected_reason": expected_reason,
            "expected_formal_result": expected_formal_result or {},
            "remarks": remarks,
        }

    scenarios = [
        # ---- CS-06 ----
        sc("SC-CS06-001", "CS-06", "data", "STORE_01", "ON_TIME_DELIVERY", "NORMAL",
           order_no=order_on_time["order_no"], description="按时送达、事件完整"),
        sc("SC-CS06-002", "CS-06", "data", "STORE_01", "PAST_PROMISED", "ANOMALY",
           order_no=order_late["order_no"], description="超 promised 未按时送达"),
        sc("SC-CS06-003", "CS-06", "data", "STORE_01", "MISSING_PROMISED_AT", "UNDETERMINED",
           expected_reason="MISSING_PROMISED_AT", order_no=order_missing_p["order_no"],
           description="缺 promised_delivery_at"),
        sc("SC-CS06-004", "CS-06", "runtime_eval", "STORE_01", "DELAY_THEN_KNOWLEDGE_DOWN", "ANOMALY",
           order_no=order_overdue["order_no"],
           description="数据可造延误单；评测 mock Knowledge 不可用仍出分析",
           remarks="runtime: mock search_business_knowledge 不可用，断言归 S4/harness"),
        # ---- CS-08-09 ----
        sc("SC-CS08-001", "CS-08", "data", "STORE_01", "WITHIN_WINDOW", "eligible",
           order_no=order_eligible["order_no"], description="可退类目、签收在窗口内"),
        sc("SC-CS08-002", "CS-08", "data", "STORE_01", "WINDOW_EXPIRED", "ineligible",
           order_no=order_ineligible["order_no"], description="可退类目、窗口已过"),
        sc("SC-CS08-003", "CS-08", "data", "STORE_01", "MISSING_SIGNED_AT", "undetermined",
           expected_reason="MISSING_SIGNED_AT", order_no=order_nsigned["order_no"],
           description="已送达未签收"),
        sc("SC-CS08-004", "CS-08", "runtime_eval", "STORE_01", "CONFIRM_CANCEL", "eligible",
           order_no=order_eligible["order_no"],
           description="前置 eligible；评测停在 Confirmation 取消",
           remarks="runtime: HITL Confirmation 取消，归 S4/harness"),
        sc("SC-CS08-005", "CS-08", "runtime_eval", "STORE_01", "APPROVAL_REJECT", "eligible",
           order_no=order_eligible["order_no"],
           description="前置 eligible；评测审批拒绝",
           remarks="runtime: HITL Approval 拒绝，归 S4/harness"),
        sc("SC-CS08-006", "CS-08", "data", "STORE_01", "PREEXISTING_AFTERSALES", None,
           order_no=preexisting_order_no, description="预置已成功售后作对照（无路由断言）",
           remarks="对照数据：该订单存在 after_sales_requests status=COMPLETED/APPROVED"),
        sc("SC-CS08-007", "CS-08", "runtime_eval", "STORE_01", "RULE_CONFLICT", "undetermined",
           expected_reason="RULE_CONFLICT", order_no=conflict_order["order_no"],
           description="conflict 产品签收在第 10 天；CONF-01(7日)/CONF-02(15日) 矛盾",
           remarks="runtime: R1-R5 消解服务在 S4/harness 断言 RULE_CONFLICT（resolution-service-dependent）"),
        # ---- OP-03 ----
        sc("SC-OP03-001", "OP-03", "data", "STORE_01", "SLOW_MOVING", "HAS_CANDIDATES",
           sku_ids=["SKU_01_SLOW_01"], description="R_SLOW 慢销候选"),
        sc("SC-OP03-002", "OP-03", "data", "STORE_01", "NO_SLOW_IN_SCOPE", "EMPTY",
           input_scope={"category": "beauty"}, description="beauty 类目内无慢销"),
        sc("SC-OP03-003", "OP-03", "data", "STORE_01", "SLOW_WITH_HEALTH", "HAS_CANDIDATES",
           sku_ids=["SKU_01_SLOW_HEALTHY_01"], description="慢销但健康；勿等同滞销风险等级"),
        sc("SC-OP03-004", "OP-03", "runtime_eval", "STORE_01", "PERF_QUERY_FAIL", "UNDETERMINED",
           expected_reason="PERF_QUERY_FAIL",
           remarks="runtime: 故障注入或数据不足二选一，归 S4/harness"),
        # ---- OP-04 ----
        sc("SC-OP04-001", "OP-04", "data", "STORE_01", "LOW_STOCK_HIGH_SALES", "HAS_RISK",
           sku_ids=["SKU_01_STOCKOUT_01"], input_scope={"horizon_days": 14}, description="R_STOCKOUT"),
        sc("SC-OP04-002", "OP-04", "data", "STORE_01", "HEALTHY_DOI", "NO_RISK",
           sku_ids=["SKU_01_NORMAL_01"], description="R_NORMAL 健康 DOI"),
        sc("SC-OP04-003", "OP-04", "data", "STORE_01", "MISSING_SALES_WINDOW", "UNDETERMINED",
           expected_reason="MISSING_SALES_WINDOW", sku_ids=["SKU_01_SPARSE_SALES_01"],
           description="R_SPARSE_SALES 销量窗不足"),
        sc("SC-OP04-004", "OP-04", "data", "STORE_01", "LOW_STOCK_HIGH_SALES", "HAS_RISK",
           sku_ids=["SKU_01_STOCKOUT_01"], description="同 001；metadata handoff_to OP-05",
           remarks="metadata: handoff_to=OP-05（移交为 WF 行为，非数据构造）"),
        # ---- OP-05 ----
        sc("SC-OP05-001", "OP-05", "data", "STORE_01", "RESTOCK_NEEDED", "HAS_RECO",
           sku_ids=["SKU_01_STOCKOUT_01"], description="R_STOCKOUT 需补货"),
        sc("SC-OP05-002", "OP-05", "data", "STORE_01", "STOCK_SUFFICIENT", "NO_RECO",
           sku_ids=["SKU_01_NORMAL_01"], description="R_NORMAL 无需补"),
        sc("SC-OP05-003", "OP-05", "data", "STORE_02", "MISSING_LEAD_TIME_CONFIG", "UNDETERMINED",
           expected_reason="MISSING_LEAD_TIME_CONFIG", sku_ids=["SKU_02_STOCKOUT_01"],
           description="STORE_02 缺 lead_time（缺配置测试店）"),
        sc("SC-OP05-004", "OP-05", "data", "STORE_01", "SKIP_PRESCREEN", "HAS_RECO",
           sku_ids=["SKU_01_STOCKOUT_01"], description="指定 SKU 直接算建议"),
        sc("SC-OP05-005", "OP-05", "runtime_eval", "STORE_01", "CONFIRM_ACCEPT", "HAS_RECO",
           sku_ids=["SKU_01_STOCKOUT_01"], description="前置 HAS_RECO；评测模拟 Confirmation 接受",
           remarks="runtime: HITL Confirmation 接受，归 S4/harness"),
        sc("SC-OP05-006", "OP-05", "runtime_eval", "STORE_01", "CONFIRM_REJECT", "HAS_RECO",
           sku_ids=["SKU_01_STOCKOUT_01"], description="前置 HAS_RECO；评测模拟拒绝",
           remarks="runtime: HITL Confirmation 拒绝，归 S4/harness"),
        # ---- OP-07 ----
        sc("SC-OP07-001", "OP-07", "data", "STORE_01", "FULL_CORE", None,
           sku_ids=["SKU_01_HEALTH_FULL_01"],
           expected_formal_result={"summary": "五核心齐，仅缺可选 traffic；核心完整度 high"},
           description="R_HEALTH_FULL；缺 traffic 不降核心完整度"),
        sc("SC-OP07-002", "OP-07", "data", "STORE_01", "MISSING_OPTIONAL", None,
           sku_ids=["SKU_01_HEALTH_FULL_01"],
           expected_formal_result={"summary": "可选维缺失已标注、核心未降级"},
           description="V1 可选仅 traffic 且恒缺（与 001 可同 SKU）"),
        sc("SC-OP07-003", "OP-07", "data", "STORE_01", "MISSING_CORE", None,
           sku_ids=["SKU_01_HEALTH_CORE_MISS_01"],
           expected_formal_result={"summary": "缺核心维（无 cost → margin 缺），完整度降级"},
           description="R_HEALTH_CORE_MISS"),
        # ---- OP-08 ----
        sc("SC-OP08-001", "OP-08", "data", "STORE_01", "DROP_OVER_THRESHOLD", "ANOMALY",
           sku_ids=["SKU_01_ANOMALY_DROP_01"], description="R_ANOMALY_DROP 达阈值"),
        sc("SC-OP08-002", "OP-08", "data", "STORE_01", "BELOW_THRESHOLD", "NORMAL",
           sku_ids=["SKU_01_NORMAL_01"], description="R_NORMAL 未达阈值"),
        sc("SC-OP08-003", "OP-08", "data", "STORE_02", "MISSING_ANOMALY_CONFIG", "UNDETERMINED",
           expected_reason="MISSING_ANOMALY_CONFIG", sku_ids=["SKU_02_ANOMALY_DROP_01"],
           description="STORE_02 缺异常阈值 key"),
        sc("SC-OP08-004", "OP-08", "data", "STORE_01", "DROP_WITH_PRICE_EVIDENCE", "ANOMALY",
           sku_ids=["SKU_01_PRICE_DROP_01"], description="R_PRICE_DROP 降价证据"),
        # ---- ISO ----
        sc("SC-ISO-001", "ISO", "data", "STORE_01", "CROSS_STORE", "NORMAL",
           order_no=store2_order["order_no"],
           expected_formal_result={"source_store": 2},
           description="STORE_01 上下文读 STORE_02 订单 → 读取放开，标注来源店（写操作仍限店）",
           remarks="方向 A：跨店读取放开，结果标注 source_store=2"),
    ]

    if len(scenarios) != 33:
        raise RuntimeError(f"SC 数量应为 33，实际 {len(scenarios)}")

    payload = {
        "dataset": {"seed": cfg.dataset.seed, "as_of_date": cfg.dataset.as_of_date,
                    "profile": cfg.profile.name},
        "scenarios": scenarios,
    }
    SCENARIOS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCENARIOS_PATH.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    n_data = sum(1 for s in scenarios if s["nature"] == "data")
    n_runtime = sum(1 for s in scenarios if s["nature"] == "runtime_eval")
    return {"total": len(scenarios), "data": n_data, "runtime_eval": n_runtime}
