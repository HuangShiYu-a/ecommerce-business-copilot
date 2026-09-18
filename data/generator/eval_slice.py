"""S3.7 eval 切片（P8）。

「同库 + manifest 过滤」（S2 §15.2）：从 dev 世界（同 seed 全量生成）过滤出 eval 切片，
只保留 SC 引用对象 + 必要上下文，写入 generated/eval/。

包含集合：
- 全部 SC（data + runtime 前置）引用的 sku / order_no，以及由其带出的商品/类目/客户/物流/库存
- 一个 CANCELLED + 一个 PENDING_PAYMENT 订单（§12A 排除状态对照）
- 售后/反馈/价格史：仅引用订单/SKU 的（OP-07/08 证据、SC-CS08-006 对照）
- Knowledge：全部（CS-08/06 检索需要）
- stores / staff / warehouses / store_configs：两店全量
- campaigns：SC 未引用，不纳入
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from .config import GeneratorConfig
from .master import _write_csv
from .scenarios import SCENARIOS_PATH
from .transactions import _read_csv
from .validate import validate_all

EVAL_TABLES = [
    "stores", "staff_users", "warehouses", "product_categories", "products", "product_skus",
    "store_configs", "customers", "customer_addresses", "orders", "order_items",
    "shipments", "shipment_events", "inventory", "after_sales_requests", "customer_feedback",
    "price_history", "campaigns", "campaign_products", "knowledge_documents", "knowledge_chunks",
]


def _filter_rows(rows, keep):
    return [r for r in rows if r["id"] in keep]


def eval_slice(cfg: GeneratorConfig, dev_world_root: Path, output_root: Path) -> Path:
    dev_canonical = dev_world_root / "canonical"
    eval_dir = output_root / "eval"
    eval_canonical = eval_dir / "canonical"
    eval_canonical.mkdir(parents=True, exist_ok=True)

    data = {t: _read_csv(dev_canonical / f"{t}.csv") for t in EVAL_TABLES}
    sku_roles = _read_csv(dev_world_root / "sku_roles.csv")
    payload = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))

    # ---- 引用集合 ----
    ref_sku_codes: set[str] = set()
    ref_order_nos: set[str] = set()
    for s in payload["scenarios"]:
        ref_sku_codes.update(s.get("sku_ids") or [])
        if s.get("order_no"):
            ref_order_nos.add(s["order_no"])

    # §12A 排除状态对照（各取一个，先于 SKU 提取，保证其 SKU 一并入切片）
    for status in ("CANCELLED", "PENDING_PAYMENT"):
        o = next((o for o in data["orders"] if o["status"] == status), None)
        if o:
            ref_order_nos.add(o["order_no"])

    sku_by_id = {int(s["id"]): s for s in data["product_skus"]}
    sku_code_by_id = {int(s["id"]): s["sku_code"] for s in data["product_skus"]}
    order_by_no = {o["order_no"]: o for o in data["orders"]}
    item_by_order: dict[int, list[dict]] = {}
    for it in data["order_items"]:
        item_by_order.setdefault(int(it["order_id"]), []).append(it)

    # 引用订单带出 SKU（含 §12A 对照订单）
    for ono in ref_order_nos:
        o = order_by_no.get(ono)
        if o is None:
            raise RuntimeError(f"eval 切片：订单 {ono} 在 dev 世界不存在")
        for it in item_by_order.get(int(o["id"]), []):
            ref_sku_codes.add(sku_code_by_id[int(it["sku_id"])])

    # ---- 数值 id 集合 ----
    ref_skus = [s for s in data["product_skus"] if s["sku_code"] in ref_sku_codes]
    ref_sku_ids = {int(s["id"]) for s in ref_skus}
    ref_product_ids = {int(s["product_id"]) for s in ref_skus}
    ref_orders = [o for o in data["orders"] if o["order_no"] in ref_order_nos]
    ref_order_ids = {int(o["id"]) for o in ref_orders}
    ref_customer_ids = {int(o["customer_id"]) for o in ref_orders}
    ref_items = [it for it in data["order_items"] if int(it["order_id"]) in ref_order_ids]
    ref_item_ids = {int(it["id"]) for it in ref_items}
    ref_shipments = [s for s in data["shipments"] if int(s["order_id"]) in ref_order_ids]
    ref_shipment_ids = {int(s["id"]) for s in ref_shipments}
    ref_campaign_products = [c for c in data["campaign_products"]
                             if int(c["product_id"]) in ref_product_ids]
    ref_campaign_ids = {int(c["campaign_id"]) for c in ref_campaign_products}

    # ---- 过滤 ----
    keep = {
        "stores": {r["id"] for r in data["stores"]},
        "staff_users": {r["id"] for r in data["staff_users"]},
        "warehouses": {r["id"] for r in data["warehouses"]},
        "product_categories": {r["id"] for r in data["product_categories"]},
        "products": {str(p) for p in ref_product_ids},
        "product_skus": {str(s) for s in ref_sku_ids},
        "store_configs": {r["id"] for r in data["store_configs"]},
        "customers": {str(c) for c in ref_customer_ids},
        "customer_addresses": {r["id"] for r in data["customer_addresses"]
                               if int(r["customer_id"]) in ref_customer_ids},
        "orders": {str(o) for o in ref_order_ids},
        "order_items": {str(i) for i in ref_item_ids},
        "shipments": {str(s) for s in ref_shipment_ids},
        "shipment_events": {r["id"] for r in data["shipment_events"]
                            if int(r["shipment_id"]) in ref_shipment_ids},
        "inventory": {r["id"] for r in data["inventory"] if int(r["sku_id"]) in ref_sku_ids},
        "after_sales_requests": {r["id"] for r in data["after_sales_requests"]
                                 if int(r["order_id"]) in ref_order_ids},
        "customer_feedback": {r["id"] for r in data["customer_feedback"]
                              if int(r["order_id"]) in ref_order_ids},
        "price_history": {r["id"] for r in data["price_history"] if int(r["sku_id"]) in ref_sku_ids},
        "campaigns": {str(c) for c in ref_campaign_ids},
        "campaign_products": {str(c["id"]) for c in ref_campaign_products},
        "knowledge_documents": {r["id"] for r in data["knowledge_documents"]},
        "knowledge_chunks": {r["id"] for r in data["knowledge_chunks"]},
    }

    tables = []
    for t in EVAL_TABLES:
        rows = _filter_rows(data[t], keep[t])
        _write_csv(eval_canonical / f"{t}.csv", list(rows[0].keys()) if rows else [], rows)
        tables.append({"table": t, "rows": len(rows)})

    # sku_roles：仅引用 SKU
    ref_sku_roles = [r for r in sku_roles if r["sku_code"] in ref_sku_codes]
    _write_csv(eval_dir / "sku_roles.csv",
               ["sku_code", "product_code", "store_id", "role_id", "conflict_test"],
               ref_sku_roles)
    tables.append({"table": "sku_roles", "rows": len(ref_sku_roles), "internal": True})

    # 校验报告
    report = validate_all(cfg, eval_canonical, output_root)
    manifest = {
        "seed": cfg.dataset.seed,
        "as_of_date": cfg.dataset.as_of_date,
        "profile": "eval",
        "stage": "S3.7-eval",
        "basis": "dev 同库 + manifest 过滤",
        "tables": tables,
        "scenarios": {"total": len(payload["scenarios"]),
                      "data": sum(1 for s in payload["scenarios"] if s["nature"] == "data"),
                      "runtime_eval": sum(1 for s in payload["scenarios"] if s["nature"] == "runtime_eval")},
        "validate_gate": report["gate"],
        "validate_p0_failures": report["p0_failures"],
    }
    (eval_canonical / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return eval_canonical
