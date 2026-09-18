"""S3.6 校验骨架（P7）。

对生成的 canonical 数据做数据层校验（S2 §11 清单），输出 validate_report.json。
- 不运行 Tool/Calculation（真实路由验证归 S4）
- Movement 平衡跳过（策略 B 未生成）
- 夹具容错：KD-AS-EXP-01 / KD-AS-CONF-01/02 是故意构造的 eval 夹具，不判数据错误、不误判 DB-G13
- 过门：无 P0 级失败
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import yaml

from .config import GeneratorConfig
from .scenarios import SCENARIOS_PATH
from .transactions import _read_csv

VALID_ORDER_STATUS = {"PENDING_PAYMENT", "PAID", "PROCESSING", "SHIPPED", "COMPLETED", "CANCELLED", "CLOSED"}
VALID_SALES = {"PAID", "PROCESSING", "SHIPPED", "COMPLETED"}
VALID_RETURN = {"APPROVED", "PROCESSING", "COMPLETED"}

EXPECTED_TABLES = [
    "stores", "staff_users", "warehouses", "product_categories", "products", "product_skus",
    "store_configs",
    "customers", "customer_addresses", "orders", "order_items", "shipments", "shipment_events",
    "inventory", "after_sales_requests", "customer_feedback", "price_history",
    "campaigns", "campaign_products", "knowledge_documents", "knowledge_chunks",
]


def _ck(cid, name, level, passed, issues):
    return {"id": cid, "name": name, "level": level, "passed": bool(passed),
            "issues": [str(i) for i in issues][:5]}


def _load(canonical_dir: Path) -> dict:
    data = {}
    for t in EXPECTED_TABLES:
        data[t] = _read_csv(canonical_dir / f"{t}.csv")
    return data


def validate_all(cfg: GeneratorConfig, canonical_dir: Path, output_root: Path) -> dict:
    data = _load(canonical_dir)
    as_of = date.fromisoformat(cfg.dataset.as_of_date)

    checks = []
    checks.append(_schema_fk(data))
    checks.append(_s12a_status(data))
    checks.append(_time_order(data))
    checks.append(_after_sales_qty(data))
    checks.append(_derived_after_delivery(data))
    checks.append(_price_history(data, as_of))
    checks.append(_role_narrative(data, output_root, cfg.profile.name))
    checks.append(_sales_shape(data, as_of, output_root, cfg.profile.name))
    checks.append(_sc_preconditions(data, output_root, cfg.profile.name))
    checks.append(_op07_core_dims(data, output_root, cfg.profile.name))
    checks.append(_knowledge_lifecycle(data, as_of))
    checks.append(_isolation(data))
    checks.append(_fixture_tolerance(data))
    checks.append(_scope_mutual_exclusion(data))

    p0_failures = [c["id"] for c in checks if not c["passed"] and c["level"] == "P0"]
    report = {
        "profile": cfg.profile.name,
        "as_of_date": cfg.dataset.as_of_date,
        "checks": checks,
        "p0_failures": p0_failures,
        "gate": "PASS" if not p0_failures else "FAIL",
    }
    report_path = output_root / cfg.profile.name / "validate_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _schema_fk(d) -> dict:
    issues = []
    for t in EXPECTED_TABLES:
        if not d[t]:
            issues.append(f"表 {t} 为空")
    stores = {int(r["id"]) for r in d["stores"]}
    for t in ["staff_users", "warehouses", "products", "product_skus", "customers",
              "customer_addresses", "orders", "order_items", "inventory",
              "after_sales_requests", "customer_feedback", "price_history",
              "campaigns", "store_configs"]:
        for r in d[t]:
            if int(r["store_id"]) not in stores:
                issues.append(f"{t} store_id={r['store_id']} 无对应店铺")
    cat_store = {int(r["id"]): int(r["store_id"]) for r in d["product_categories"]}
    for p in d["products"]:
        if int(p["category_id"]) not in cat_store:
            issues.append(f"products {p['product_code']} category_id 无效")
        elif cat_store[int(p["category_id"])] != int(p["store_id"]):
            issues.append(f"products {p['product_code']} 类目跨店")
    prod_store = {int(r["id"]): int(r["store_id"]) for r in d["products"]}
    for s in d["product_skus"]:
        if int(s["product_id"]) not in prod_store:
            issues.append(f"product_skus {s['sku_code']} product_id 无效")
        elif prod_store[int(s["product_id"])] != int(s["store_id"]):
            issues.append(f"product_skus {s['sku_code']} 跨店")
    order_ids = {int(r["id"]) for r in d["orders"]}
    for it in d["order_items"]:
        if int(it["order_id"]) not in order_ids:
            issues.append(f"order_items {it['id']} order_id 无效")
    sku_ids = {int(r["id"]) for r in d["product_skus"]}
    for it in d["order_items"]:
        if int(it["sku_id"]) not in sku_ids:
            issues.append(f"order_items {it['id']} sku_id 无效")
    doc_ids = {int(r["id"]) for r in d["knowledge_documents"]}
    for c in d["knowledge_chunks"]:
        if int(c["document_id"]) not in doc_ids:
            issues.append(f"knowledge_chunks {c['id']} document_id 无效")
    return _ck("schema_fk", "Schema / FK 自洽", "P0", not issues, issues)


def _s12a_status(d) -> dict:
    issues = []
    statuses = {o["status"] for o in d["orders"]}
    if not statuses <= VALID_ORDER_STATUS:
        issues.append(f"未知订单状态 {statuses - VALID_ORDER_STATUS}")
    n_valid = sum(1 for o in d["orders"] if o["status"] in VALID_SALES)
    if n_valid == 0:
        issues.append("无有效销售订单")
    if not any(o["status"] in ("CANCELLED", "PENDING_PAYMENT") for o in d["orders"]):
        issues.append("缺少被排除状态订单（CANCELLED/PENDING_PAYMENT）")
    return _ck("s12a_status", "§12A 订单状态", "P0", not issues, issues)


def _time_order(d) -> dict:
    issues = []
    for o in d["orders"]:
        if o["status"] != "COMPLETED":
            continue
        try:
            ordered = datetime.fromisoformat(o["ordered_at"])
            paid = datetime.fromisoformat(o["paid_at"])
            shipped = datetime.fromisoformat(o["shipped_at"])
            delivered = datetime.fromisoformat(o["delivered_at"])
            if not o["signed_at"]:  # 已送达未签收（SC-CS08-003 边界）
                if not (ordered <= paid <= shipped <= delivered):
                    issues.append(f"订单 {o['order_no']} 时间序异常（未签收）")
                continue
            signed = datetime.fromisoformat(o["signed_at"])
            if not (ordered <= paid <= shipped <= delivered <= signed):
                issues.append(f"订单 {o['order_no']} 时间序异常")
        except ValueError as e:
            issues.append(f"订单 {o['order_no']} 时间解析失败: {e}")
    return _ck("time_order", "订单时间序一致", "P0", not issues, issues)


def _after_sales_qty(d) -> dict:
    issues = []
    item_qty = {int(it["id"]): int(it["quantity"]) for it in d["order_items"]}
    for r in d["after_sales_requests"]:
        if r["type"] != "RETURN":
            issues.append(f"售后 {r['request_no']} type={r['type']} 非 RETURN")
        if int(r["quantity"]) <= 0:
            issues.append(f"售后 {r['request_no']} quantity<=0")
        if int(r["order_item_id"]) not in item_qty:
            issues.append(f"售后 {r['request_no']} order_item_id 无效")
        elif int(r["quantity"]) > item_qty[int(r["order_item_id"])]:
            issues.append(f"售后 {r['request_no']} quantity 超过购买量")
        if r["status"] not in VALID_RETURN | {"REJECTED", "CANCELLED", "PENDING"}:
            issues.append(f"售后 {r['request_no']} 状态非法")
    if not any(r["status"] in VALID_RETURN for r in d["after_sales_requests"]):
        issues.append("无有效退货（支撑退货率）")
    return _ck("after_sales_qty", "售后 quantity 与状态", "P0", not issues, issues)


def _derived_after_delivery(d) -> dict:
    issues = []
    order_delivered = {int(o["id"]): o["delivered_at"] for o in d["orders"]}
    for r in d["after_sales_requests"]:
        delivered = order_delivered.get(int(r["order_id"]), "")
        if delivered and r["created_at"] and datetime.fromisoformat(r["created_at"]) < datetime.fromisoformat(delivered):
            issues.append(f"售后 {r['request_no']} created < delivered")
    for f in d["customer_feedback"]:
        delivered = order_delivered.get(int(f["order_id"]), "")
        if delivered and f["created_at"] and datetime.fromisoformat(f["created_at"]) < datetime.fromisoformat(delivered):
            issues.append(f"反馈 {f['id']} created < delivered")
    return _ck("derived_after_delivery", "售后/反馈 ≥ 送达", "P0", not issues, issues)


def _price_history(d, as_of) -> dict:
    issues = []
    sku_price = {int(s["id"]): float(s["selling_price"]) for s in d["product_skus"]}
    for r in d["price_history"]:
        sid = int(r["sku_id"])
        if sid not in sku_price:
            issues.append(f"价格史 sku_id={sid} 无效")
            continue
        if abs(float(r["new_price"]) - sku_price[sid]) > 1e-6:
            issues.append(f"价格史 sku_id={sid} 最新价≠现价")
        if float(r["old_price"]) <= float(r["new_price"]):
            issues.append(f"价格史 sku_id={sid} old≤new")
        if datetime.fromisoformat(r["effective_at"]).date() >= as_of:
            issues.append(f"价格史 sku_id={sid} effective_at 在 as_of 后")
    return _ck("price_history", "价格史一致（最新价=现价）", "P0", not issues, issues)


def _role_narrative(d, output_root, profile) -> dict:
    issues = []
    sku_roles = _read_csv(output_root / profile / "sku_roles.csv")
    role_of = {r["sku_code"]: r["role_id"] for r in sku_roles}
    sku_code_by_id = {int(s["id"]): s["sku_code"] for s in d["product_skus"]}
    valid_ids = {int(o["id"]) for o in d["orders"] if o["status"] in VALID_SALES}
    units = {}
    for it in d["order_items"]:
        if int(it["order_id"]) not in valid_ids:
            continue
        code = sku_code_by_id.get(int(it["sku_id"]))
        if code:
            units[code] = units.get(code, 0) + int(it["quantity"])

    def avg(role):
        vals = [units.get(c, 0) for c, r in role_of.items() if r == role]
        return sum(vals) / len(vals) if vals else 0.0

    if not (avg("R_HOT") > avg("R_NORMAL") > avg("R_SLOW")):
        issues.append(f"角色销量叙事不成立 (HOT={avg('R_HOT'):.0f} NORMAL={avg('R_NORMAL'):.0f} SLOW={avg('R_SLOW'):.0f})")

    inv = {int(r["sku_id"]): int(r["available_qty"]) for r in d["inventory"]}
    stockout_avail = [inv[int(s["id"])] for s in d["product_skus"]
                      if role_of.get(s["sku_code"]) == "R_STOCKOUT"]
    slow_avail = [inv[int(s["id"])] for s in d["product_skus"]
                  if role_of.get(s["sku_code"]) == "R_SLOW"]
    if stockout_avail and max(stockout_avail) > 3:
        issues.append("R_STOCKOUT 库存不够低")
    if slow_avail and min(slow_avail) < 100:
        issues.append("R_SLOW 库存不够高")
    return _ck("role_narrative", "角色叙事可辨", "P1", not issues, issues)


def _sales_shape(d, as_of, output_root, profile) -> dict:
    """销量形状（P1）：R_ANOMALY_DROP / R_PRICE_DROP 近 7 天较前 7 天应明显下降（SC-OP08 ANOMALY 前置）。"""
    issues = []
    sku_roles = _read_csv(output_root / profile / "sku_roles.csv")
    role_of = {r["sku_code"]: r["role_id"] for r in sku_roles}
    sku_code_by_id = {int(s["id"]): s["sku_code"] for s in d["product_skus"]}
    valid_ids = {int(o["id"]) for o in d["orders"] if o["status"] in VALID_SALES}
    order_date = {int(o["id"]): datetime.fromisoformat(o["ordered_at"]).date() for o in d["orders"]}

    def last_vs_prior(sku_code):
        sid = next((sid for sid, code in sku_code_by_id.items() if code == sku_code), None)
        if sid is None:
            return None
        last = prior = 0
        for it in d["order_items"]:
            if int(it["sku_id"]) != sid or int(it["order_id"]) not in valid_ids:
                continue
            od = order_date.get(int(it["order_id"]))
            if od is None:
                continue
            age = (as_of - od).days
            if 0 <= age < 7:
                last += int(it["quantity"])
            elif 7 <= age < 14:
                prior += int(it["quantity"])
        return last, prior

    for sku_code, role in role_of.items():
        if role not in ("R_ANOMALY_DROP", "R_PRICE_DROP"):
            continue
        r = last_vs_prior(sku_code)
        if r is None:
            issues.append(f"{sku_code} 无对应 SKU")
            continue
        last, prior = r
        if prior > 0 and last >= prior * 0.8:
            issues.append(f"{sku_code} 近7天({last}) 未较前7天({prior}) 下降≥20%")
    return _ck("sales_shape", "销量形状（骤降/降价后下降）", "P1", not issues, issues)


def _sc_preconditions(d, output_root, profile) -> dict:
    issues = []
    sku_codes = {s["sku_code"] for s in d["product_skus"]}
    order_nos = {o["order_no"] for o in d["orders"]}
    if SCENARIOS_PATH.exists():
        payload = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))
        for s in payload["scenarios"]:
            if s["nature"] == "runtime_eval":
                continue  # 仅挂前置 ID，S3.6 不断言进程
            for code in s.get("sku_ids") or []:
                if code not in sku_codes:
                    issues.append(f"{s['scenario_id']} sku {code} 不存在")
            if s.get("order_no") and s["order_no"] not in order_nos:
                issues.append(f"{s['scenario_id']} 订单 {s['order_no']} 不存在")
    else:
        issues.append("scenarios.yaml 不存在，无法校验 SC 前置")
    return _ck("sc_preconditions", "SC data 前置可解析", "P0", not issues, issues)


def _op07_core_dims(d, output_root, profile) -> dict:
    issues = []
    sku_roles = _read_csv(output_root / profile / "sku_roles.csv")
    role_of = {r["sku_code"]: r["role_id"] for r in sku_roles}
    sku_by_code = {s["sku_code"]: s for s in d["product_skus"]}
    full = sku_by_code.get("SKU_01_HEALTH_FULL_01")
    miss = sku_by_code.get("SKU_01_HEALTH_CORE_MISS_01")
    if full:
        if not full["cost_price"]:
            issues.append("R_HEALTH_FULL 缺 cost（margin 维）")
    else:
        issues.append("缺 SKU_01_HEALTH_FULL_01")
    if miss:
        if miss["cost_price"]:
            issues.append("R_HEALTH_CORE_MISS 不应有 cost（margin 应缺失）")
    else:
        issues.append("缺 SKU_01_HEALTH_CORE_MISS_01")
    return _ck("op07_core_dims", "OP-07 核心维数据", "P1", not issues, issues)


def _knowledge_lifecycle(d, as_of) -> dict:
    issues = []
    def in_window(doc):
        ef = datetime.fromisoformat(doc["effective_from"]).date()
        et = datetime.fromisoformat(doc["effective_to"]).date() if doc["effective_to"] else None
        return doc["status"] == "ACTIVE" and ef <= as_of and (et is None or as_of < et)
    titles = {doc["title"] for doc in d["knowledge_documents"]}
    if not in_window(next(doc for doc in d["knowledge_documents"] if doc["title"] == "七日无理由退货底线")):
        issues.append("KD-AS-01 不在有效窗")
    exp = next((doc for doc in d["knowledge_documents"] if "已失效" in doc["title"]), None)
    if exp and in_window(exp):
        issues.append("EXP 夹具不应在有效窗内")
    if len(titles) != 10:
        issues.append(f"文档数 {len(titles)} != 10")
    return _ck("knowledge_lifecycle", "Knowledge 生命周期窗", "P0", not issues, issues)


def _isolation(d) -> dict:
    issues = []
    for t in ["orders", "product_skus", "customer_feedback"]:
        for r in d[t]:
            if int(r["store_id"]) not in (1, 2):
                issues.append(f"{t} {r['id']} store_id={r['store_id']} 非法")
    return _ck("isolation", "两店隔离（store_id 正确）", "P0", not issues, issues)


def _fixture_tolerance(d) -> dict:
    issues = []
    titles = {doc["title"] for doc in d["knowledge_documents"]}
    if not any("已失效" in t for t in titles):
        issues.append("缺 EXP 夹具")
    if sum(1 for t in titles if "冲突测试店规" in t) != 2:
        issues.append("缺 CONF 对（应为 2 篇）")
    return _ck("fixture_tolerance", "EXP/CONF 夹具容错", "P0", not issues, issues)


def _scope_mutual_exclusion(d) -> dict:
    issues = []
    id_by_title = {doc["title"]: doc["id"] for doc in d["knowledge_documents"]}
    as04 = id_by_title.get("店铺补充售后政策（STORE_01）")
    conf = [doc["id"] for doc in d["knowledge_documents"] if "冲突测试店规" in doc["title"]]
    for c in d["knowledge_chunks"]:
        if not c["metadata"]:
            continue
        meta = json.loads(c["metadata"])
        scope = meta.get("scope", {})
        if as04 and c["document_id"] == as04:
            if "apparel-conflict-test" not in scope.get("exclude_tags", []):
                issues.append("KD-AS-04 未排除 apparel-conflict-test")
        if c["document_id"] in conf:
            if scope.get("include_tags") != ["apparel-conflict-test"]:
                issues.append("CONF 对未 include apparel-conflict-test")
    return _ck("scope_mutual_exclusion", "KD-AS-04↔CONF scope 互斥", "P0", not issues, issues)
