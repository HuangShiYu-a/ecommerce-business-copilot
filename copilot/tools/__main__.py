"""Tool CLI 调试：python -m copilot.tools --tool T-R-01 --sku SKU_01_STOCKOUT_01 [--store 1]"""
from __future__ import annotations

import argparse
import json
import sys

from ..context import ops_ctx
from ..tool import run_tool
from . import *  # noqa: F401,F403  触发工具注册


def main() -> int:
    parser = argparse.ArgumentParser(description="Tool 调试入口")
    parser.add_argument("--tool", required=True, help="tool_id，如 T-R-01")
    parser.add_argument("--sku", default=None, help="sku_code")
    parser.add_argument("--sku-id", type=int, default=None)
    parser.add_argument("--store", type=int, default=1)
    parser.add_argument("--horizon", type=int, default=None)
    args = parser.parse_args()

    res = run_tool(args.tool, ops_ctx(args.store),
                   sku_code=args.sku, sku_id=args.sku_id, horizon_days=args.horizon)
    payload = {"ok": res.ok, "data": res.data,
               "error_code": res.error_code, "error_detail": res.error_detail}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
