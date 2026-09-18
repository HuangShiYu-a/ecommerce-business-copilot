"""S3.1 Master 主数据生成（P2）。

产出 7 张主数据 canonical 表（DB §13 列级一致）+ SKU 角色映射（generator 内部，非 canonical）。
- canonical：stores / staff_users / warehouses / product_categories / products / product_skus / store_configs
- 内部：generated/<profile>/sku_roles.csv（sku_code → role / conflict_test，供 S3.2 / S3.4 / S3.6 消费）

约定：
- 确定性：单一 Random(seed)，生成顺序稳定 → 同 seed 可复现。
- id：生成器分配确定性整数；导入时（S4）映射到 DB。
- 空值：canonical CSV 用空字符串表示 NULL（导入时转换）。
- created_at / updated_at 由导入时 DB 默认，不写入 canonical。
"""
from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

from .config import CONFIG_DIR, GeneratorConfig, load_yaml

RULES_DIR = Path(__file__).resolve().parent / "rules"

MASTER_TABLES = [
    "stores",
    "staff_users",
    "warehouses",
    "product_categories",
    "products",
    "product_skus",
    "store_configs",
]

# 13 角色 → 首选类目（S2 §6.1 类目契约）
ROLE_CATEGORY = {
    "R_HOT": "electronics",
    "R_NORMAL": "apparel",
    "R_SLOW": "home",
    "R_SLOW_HEALTHY": "books",
    "R_STOCKOUT": "electronics",
    "R_OVERSTOCK": "home",
    "R_RETURN_HIGH": "apparel",
    "R_PRICE_DROP": "electronics",
    "R_ANOMALY_DROP": "electronics",
    "R_SPARSE_SALES": "baby",
    "R_HEALTH_FULL": "apparel",
    "R_HEALTH_CORE_MISS": "books",
    "R_BASELINE": "home",
}
# R_NORMAL / R_HOT 各 3 个 SKU（S2 §6：可 3+）
ROLE_SKU_COUNT = {"R_NORMAL": 3, "R_HOT": 3}

# STORE_02（隔离 + 缺配置测试店）角色最小集与类目子集
STORE02_ROLES = ["R_STOCKOUT", "R_ANOMALY_DROP", "R_NORMAL"]
STORE02_CATEGORIES = ["electronics", "apparel", "home"]
STORE02_PRODUCTS = 10

CONFLICT_TAG = "apparel-conflict-test"
CONFLICT_PRODUCT_CODE = "PRD_01_CONFLICT_01"
CONFLICT_SKU_CODE = "SKU_01_CONFLICT_01"

# apparel-intimate（KD-AS-02 平台不可退条款数据支撑；K3 §5 注册，用户 2026-09-18 采纳）
INTIMATE_TAG = "apparel-intimate"
INTIMATE_PRODUCT_CODE = "PRD_01_INTIMATE_01"
INTIMATE_SKU_CODE = "SKU_01_INTIMATE_01"

BRANDS = ["云雀", "蓝屿", "天枢", "青禾", "琥珀", "南风", "远山", "墨白"]
CATEGORY_WORDS = {
    "customized": ["定制T恤", "定制马克杯", "定制相册"],
    "fresh": ["鲜牛奶", "即食鸡胸", "时令水果"],
    "electronics": ["无线耳机", "快充充电器", "蓝牙音箱", "智能手环"],
    "beauty": ["保湿面霜", "氨基酸洁面", "防晒乳"],
    "apparel": ["基础白T", "直筒牛仔裤", "连帽卫衣"],
    "home": ["四件套", "记忆枕", "收纳箱"],
    "books": ["经营管理", "科幻小说", "儿童绘本"],
    "baby": ["婴儿湿巾", "益智积木", "安抚玩偶"],
}
CATEGORY_PRICE = {
    "customized": (99, 499),
    "fresh": (29, 199),
    "electronics": (129, 1299),
    "beauty": (49, 399),
    "apparel": (59, 399),
    "home": (89, 599),
    "books": (29, 129),
    "baby": (39, 299),
}


def _write_csv(path: Path, headers: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def generate_master(cfg: GeneratorConfig, canonical_dir: Path, output_root: Path) -> list[dict]:
    """生成主数据并写 canonical CSV + sku_roles.csv；返回表清单（供 manifest）。"""
    rng = random.Random(cfg.dataset.seed)
    params = cfg.profile.params

    categories_def = load_yaml(RULES_DIR / "categories.yaml")["categories"]
    roles_def = load_yaml(RULES_DIR / "roles.yaml")["roles"]
    sc_yaml = load_yaml(CONFIG_DIR / "store_configs.yaml")
    config_defaults = sc_yaml["defaults"]
    deficient_keys = set(sc_yaml["deficient_keys_store02"])

    as_of = date.fromisoformat(cfg.dataset.as_of_date)
    timeline_start = date.fromisoformat(cfg.dataset.timeline_start)

    stores = _gen_stores()
    staff = _gen_staff(stores)
    warehouses = _gen_warehouses(stores, params.get("warehouses_per_store", 1))
    categories = _gen_categories(stores, categories_def)
    products, skus, sku_roles = _gen_products_and_skus(
        stores, categories, categories_def, params, roles_def,
        as_of, timeline_start, rng,
    )
    store_configs = _gen_store_configs(stores, config_defaults, deficient_keys)

    specs = {
        "stores": (["id", "store_code", "name", "status"], stores),
        "staff_users": (["id", "store_id", "username", "display_name", "role", "is_active"], staff),
        "warehouses": (["id", "store_id", "warehouse_code", "name", "location", "status"], warehouses),
        "product_categories": (["id", "store_id", "parent_id", "name", "status"], categories),
        "products": (
            ["id", "store_id", "product_code", "name", "category_id", "brand", "description",
             "status", "cost_price", "listed_at", "launch_date"],
            products,
        ),
        "product_skus": (
            ["id", "store_id", "product_id", "sku_code", "attributes", "selling_price", "cost_price", "status"],
            skus,
        ),
        "store_configs": (["id", "store_id", "config_key", "config_value"], store_configs),
    }

    tables = []
    for name in MASTER_TABLES:
        headers, rows = specs[name]
        _write_csv(canonical_dir / f"{name}.csv", headers, rows)
        tables.append({"table": name, "rows": len(rows)})

    # SKU 角色映射（generator 内部，非 canonical）
    sku_roles_path = output_root / cfg.profile.name / "sku_roles.csv"
    _write_csv(sku_roles_path, ["sku_code", "product_code", "store_id", "role_id", "conflict_test"], sku_roles)
    tables.append({"table": "sku_roles", "rows": len(sku_roles), "internal": True})

    return tables


def _gen_stores() -> list[dict]:
    return [
        {"id": 1, "store_code": "STORE_01", "name": "模拟旗舰店", "status": "ACTIVE"},
        {"id": 2, "store_code": "STORE_02", "name": "模拟隔离测试店", "status": "ACTIVE"},
    ]


def _gen_staff(stores: list[dict]) -> list[dict]:
    rows = []
    for st in stores:
        sid = st["id"]
        prefix = f"STAFF_{sid:02d}"
        rows.append({"id": len(rows) + 1, "store_id": sid, "username": f"{prefix}_CS_01",
                     "display_name": "模拟客服01", "role": "customer_service", "is_active": "true"})
        rows.append({"id": len(rows) + 1, "store_id": sid, "username": f"{prefix}_CS_02",
                     "display_name": "模拟客服02", "role": "customer_service", "is_active": "true"})
        rows.append({"id": len(rows) + 1, "store_id": sid, "username": f"{prefix}_OP_01",
                     "display_name": "模拟运营01", "role": "operations", "is_active": "true"})
        rows.append({"id": len(rows) + 1, "store_id": sid, "username": f"{prefix}_OP_02",
                     "display_name": "模拟运营02", "role": "operations", "is_active": "true"})
        # 审批执行人：业务节点（Business §2.4），合法 role，非独立 approver 角色
        rows.append({"id": len(rows) + 1, "store_id": sid, "username": f"{prefix}_APPR_01",
                     "display_name": "审批执行人01", "role": "operations", "is_active": "true"})
    return rows


def _gen_warehouses(stores: list[dict], per_store: int) -> list[dict]:
    rows = []
    for st in stores:
        sid = st["id"]
        for i in range(1, per_store + 1):
            rows.append({"id": len(rows) + 1, "store_id": sid,
                         "warehouse_code": f"WH_{sid:02d}_{i:02d}",
                         "name": f"主仓{i}", "location": "", "status": "ACTIVE"})
    return rows


def _gen_categories(stores: list[dict], categories_def: list[dict]) -> list[dict]:
    rows = []
    for st in stores:
        sid = st["id"]
        codes = [c["code"] for c in categories_def] if sid == 1 else list(STORE02_CATEGORIES)
        name_map = {c["code"]: c["name"] for c in categories_def}
        for code in codes:
            rows.append({"id": len(rows) + 1, "store_id": sid, "parent_id": "",
                         "name": name_map[code], "status": "ACTIVE", "code": code})
    return rows


def _gen_products_and_skus(
    stores, categories, categories_def, params, roles_def, as_of, timeline_start, rng,
):
    # code -> id（按 store）
    cat_id = {}
    for c in categories:
        cat_id.setdefault(c["store_id"], {})[c["code"]] = c["id"]

    n_products = params.get("products_per_store") or 25
    n_skus = params.get("skus_per_store") or n_products * 2

    products: list[dict] = []
    skus: list[dict] = []
    sku_roles: list[dict] = []
    pid = 0
    sid = 0

    def add_product(store_id, category_code, product_code, word, rng, status="ACTIVE", has_cost=True):
        nonlocal pid
        pid += 1
        cost = ""
        if has_cost:
            lo, hi = CATEGORY_PRICE[category_code]
            cost = round(rng.uniform(lo, hi) * 0.6, 2)
        span = (as_of - timeline_start).days - 7
        listed = timeline_start + timedelta(days=rng.randint(0, span))
        row = {
            "id": pid, "store_id": store_id, "product_code": product_code,
            "name": f"{rng.choice(BRANDS)}{word}",
            "category_id": cat_id[store_id][category_code],
            "brand": rng.choice(BRANDS),
            "description": f"{word}（{category_code}）",
            "status": status, "cost_price": cost,
            "listed_at": listed.isoformat(), "launch_date": listed.isoformat(),
        }
        products.append(row)
        return row

    def add_sku(store_id, product, category_code, sku_code, role, conflict_test=False,
                product_type=None, has_cost=True):
        nonlocal sid
        sid += 1
        lo, hi = CATEGORY_PRICE[category_code]
        selling = round(rng.uniform(lo, hi), 2)
        cost = ""
        if has_cost:
            cost = round(selling * rng.uniform(0.5, 0.75), 2)
        attrs = {"color": rng.choice(["黑", "白", "灰", "蓝"])}
        if conflict_test:
            attrs["product_type"] = CONFLICT_TAG
        elif product_type:
            attrs["product_type"] = product_type
        skus.append({
            "id": sid, "store_id": store_id, "product_id": product["id"], "sku_code": sku_code,
            "attributes": json.dumps(attrs, ensure_ascii=False),
            "selling_price": selling, "cost_price": cost, "status": "ACTIVE",
        })
        sku_roles.append({
            "sku_code": sku_code, "product_code": product["product_code"], "store_id": store_id,
            "role_id": role, "conflict_test": "true" if conflict_test else "false",
        })

    def fill_bulk(store_id, n_bulk_products, n_bulk_skus, role="R_NORMAL"):
        """生成 bulk 商品/SKU，精确分配 n_bulk_skus 到 n_bulk_products 个商品。"""
        cat_codes = [c["code"] for c in categories if c["store_id"] == store_id]
        base, rem = divmod(n_bulk_skus, max(1, n_bulk_products))
        sku_idx = 0
        for i in range(n_bulk_products):
            cat_code = cat_codes[i % len(cat_codes)]
            word = rng.choice(CATEGORY_WORDS[cat_code])
            status = "ACTIVE" if (i % 7) != 0 else "INACTIVE"
            p = add_product(store_id, cat_code, f"PRD_{store_id:02d}_BULK_{i + 1:03d}", word, rng, status=status)
            n = base + (1 if i < rem else 0)
            for _ in range(n):
                sku_idx += 1
                add_sku(store_id, p, cat_code, f"SKU_{store_id:02d}_BULK_{sku_idx:03d}", role)

    for st in stores:
        store_id = st["id"]
        if store_id == 1:
            # 角色商品（13 角色；R_NORMAL/R_HOT 各 3）；逻辑 ID 对齐 S2 §8.1（去 R_ 前缀）
            for role, cat_code in ROLE_CATEGORY.items():
                rcode = role[2:]
                for n in range(1, ROLE_SKU_COUNT.get(role, 1) + 1):
                    has_cost = not (role == "R_HEALTH_CORE_MISS")
                    p = add_product(store_id, cat_code, f"PRD_{store_id:02d}_{rcode}_{n:02d}",
                                    rng.choice(CATEGORY_WORDS[cat_code]), rng, has_cost=has_cost)
                    add_sku(store_id, p, cat_code, f"SKU_{store_id:02d}_{rcode}_{n:02d}", role,
                            has_cost=has_cost)
            # conflict 产品（apparel + 窄 tag）
            cp = add_product(store_id, "apparel", CONFLICT_PRODUCT_CODE,
                             rng.choice(CATEGORY_WORDS["apparel"]), rng)
            add_sku(store_id, cp, "apparel", CONFLICT_SKU_CODE, "R_NORMAL", conflict_test=True)

            # apparel-intimate 产品（KD-AS-02 平台不可退条款数据支撑；非 conflict，不重叠）
            ip = add_product(store_id, "apparel", INTIMATE_PRODUCT_CODE,
                             rng.choice(CATEGORY_WORDS["apparel"]), rng)
            add_sku(store_id, ip, "apparel", INTIMATE_SKU_CODE, "R_NORMAL", product_type=INTIMATE_TAG)

            n_role_skus = sum(ROLE_SKU_COUNT.get(r, 1) for r in ROLE_CATEGORY)  # 17
            n_bulk_products = max(0, n_products - n_role_skus - 2)               # 40-17-2=21
            n_bulk_skus = max(0, n_skus - n_role_skus - 2)                       # 80-17-2=61
            fill_bulk(store_id, n_bulk_products, n_bulk_skus)
        else:
            # STORE_02：缺配置/隔离 SC 所需角色 + 少量 bulk
            for role in STORE02_ROLES:
                cat_code = ROLE_CATEGORY[role]
                rcode = role[2:]
                p = add_product(store_id, cat_code, f"PRD_{store_id:02d}_{rcode}_01",
                                rng.choice(CATEGORY_WORDS[cat_code]), rng)
                add_sku(store_id, p, cat_code, f"SKU_{store_id:02d}_{rcode}_01", role)
            n_bulk_products = max(0, STORE02_PRODUCTS - len(STORE02_ROLES))
            n_bulk_skus = n_bulk_products * 2
            fill_bulk(store_id, n_bulk_products, n_bulk_skus)

    return products, skus, sku_roles


def _gen_store_configs(stores, config_defaults, deficient_keys) -> list[dict]:
    rows = []
    for st in stores:
        keys = config_defaults if st["id"] == 1 else {k: v for k, v in config_defaults.items()
                                                      if k not in deficient_keys}
        for key, value in keys.items():
            rows.append({"id": len(rows) + 1, "store_id": st["id"], "config_key": key,
                         "config_value": json.dumps(value, ensure_ascii=False)})
    return rows
