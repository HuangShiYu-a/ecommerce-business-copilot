"""data.generator CLI 入口：python -m data.generator --profile dev|eval|full

P1 / S3.0 最小骨架：读取 profiles.yaml，为指定 profile 生成目录骨架与空 manifest。
"""
from __future__ import annotations

import argparse
import sys

from .config import load_config
from .generate import generate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data-generator",
        description="E-commerce Business Copilot 数据生成器（S3 骨架）",
    )
    parser.add_argument(
        "--profile",
        default="dev",
        help="生成 profile（默认 dev；可用值以 config/profiles.yaml 为准）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.profile)
        canonical_dir = generate(cfg)
    except (OSError, ValueError, KeyError) as exc:
        print(f"[data-generator] 失败: {exc}", file=sys.stderr)
        return 1
    print(
        f"[data-generator] OK profile={cfg.profile.name} seed={cfg.dataset.seed} "
        f"as_of={cfg.dataset.as_of_date} -> {canonical_dir}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
