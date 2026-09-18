"""S4.1 数据导入：canonical CSV → PostgreSQL。

用法：python db/import_data.py --profile dev [--no-reset] [--port 5434]

约定：
- 空串 → NULL；id 显式（canonical 提供稳定 id）
- created_at / updated_at 走 DB 默认 now()（canonical 未提供）
- JSONB / 数值 / 布尔 / 时间列由 PG 文本→目标类型隐式转换
- 默认先 TRUNCATE 再导入（可 --no-reset 跳过）
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import psycopg2

REPO = Path(__file__).resolve().parent.parent

PUBLIC_TABLES = [
    "stores", "staff_users", "warehouses", "product_categories", "products", "product_skus",
    "store_configs", "customers", "customer_addresses", "orders", "order_items",
    "shipments", "shipment_events", "inventory", "after_sales_requests", "customer_feedback",
    "price_history", "campaigns", "campaign_products",
]
KNOWLEDGE_TABLES = ["knowledge_documents", "knowledge_chunks"]


def _read_csv(path: Path):
    with open(path, encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames
        rows = [[None if v == "" else v for v in (r[c] for c in cols)] for r in reader]
    return cols, rows


def import_table(cur, qualified: str, csv_path: Path, truncate: bool) -> int:
    cols, rows = _read_csv(csv_path)
    if truncate:
        cur.execute(f"TRUNCATE TABLE {qualified} RESTART IDENTITY CASCADE")
    if not cols or not rows:
        return 0
    col_list = ",".join(f'"{c}"' for c in cols)
    placeholders = ",".join(["%s"] * len(cols))
    cur.executemany(f"INSERT INTO {qualified} ({col_list}) VALUES ({placeholders})", rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="canonical CSV → PostgreSQL 导入")
    parser.add_argument("--profile", default="dev")
    parser.add_argument("--no-reset", action="store_true", help="不 TRUNCATE")
    parser.add_argument("--port", type=int, default=5434)
    args = parser.parse_args()

    canonical = REPO / "data" / "generated" / args.profile / "canonical"
    conn = psycopg2.connect(host="localhost", port=args.port, dbname="ec_copilot",
                            user="ec", password="ec_secret")
    conn.autocommit = False
    cur = conn.cursor()

    plan = [(f"public.{t}", canonical / f"{t}.csv") for t in PUBLIC_TABLES] + \
           [(f"knowledge.{t}", canonical / f"{t}.csv") for t in KNOWLEDGE_TABLES]

    total = 0
    try:
        for qualified, csv_path in plan:
            if not csv_path.exists():
                print(f"  跳过 {qualified:<36}（无文件）")
                continue
            n = import_table(cur, qualified, csv_path, truncate=not args.no_reset)
            total += n
            print(f"  {qualified:<36} {n}")
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"导入失败，已回滚：{exc}", file=sys.stderr)
        return 1
    finally:
        cur.close()
        conn.close()
    print(f"总计导入 {total} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
