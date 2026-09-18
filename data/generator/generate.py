"""数据生成入口：按已实现子阶段产出 canonical 表、manifest、scenarios.yaml 与校验报告。

当前实现：S3.1 Master + S3.2 交易主链 + S3.3 派生事实 + S3.4 Scenario 绑定 + S3.5 Knowledge 导入 + S3.6 校验骨架。
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import GeneratorConfig
from .derived import generate_derived
from .importer import generate_importer
from .master import generate_master
from .scenarios import generate_scenarios
from .transactions import generate_transactions
from .validate import validate_all

# data/generated/
GENERATED_ROOT = Path(__file__).resolve().parent.parent / "generated"
MANIFEST_NAME = "manifest.json"


def generate(cfg: GeneratorConfig, output_root: Path = GENERATED_ROOT) -> Path:
    """为指定 profile 生成数据。eval = dev 世界（同 seed）的 manifest 过滤切片。"""
    if cfg.profile.name == "eval":
        return _generate_eval(cfg, output_root)
    return _generate_full(cfg, output_root)


def _generate_full(cfg: GeneratorConfig, output_root: Path) -> Path:
    """完整生成：master + 交易 + 派生 + SC 绑定 + Knowledge 导入 + 校验。返回 canonical 目录。"""
    canonical_dir = output_root / cfg.profile.name / "canonical"
    canonical_dir.mkdir(parents=True, exist_ok=True)

    tables = generate_master(cfg, canonical_dir, output_root)
    tables += generate_transactions(cfg, canonical_dir, output_root)
    tables += generate_derived(cfg, canonical_dir, output_root)
    sc_stats = generate_scenarios(cfg, canonical_dir, output_root)
    tables += generate_importer(cfg, canonical_dir, output_root)
    validate_report = validate_all(cfg, canonical_dir, output_root)

    manifest = {
        "seed": cfg.dataset.seed,
        "as_of_date": cfg.dataset.as_of_date,
        "timeline_start": cfg.dataset.timeline_start,
        "timezone": cfg.dataset.timezone,
        "profile": cfg.profile.name,
        "stage": "S3.6-validate",
        "tables": tables,
        "scenarios": sc_stats,
        "validate_gate": validate_report["gate"],
        "validate_p0_failures": validate_report["p0_failures"],
    }
    manifest_path = canonical_dir / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return canonical_dir


def _generate_eval(cfg_eval: GeneratorConfig, output_root: Path) -> Path:
    """同库 + manifest 过滤：先生成 dev 世界（同 seed），再切片出 eval。"""
    import tempfile

    from .config import load_config
    from .eval_slice import eval_slice

    dev_cfg = load_config("dev")
    with tempfile.TemporaryDirectory(prefix="gen_eval_") as td:
        full_root = Path(td)
        _generate_full(dev_cfg, full_root)
        return eval_slice(cfg_eval, full_root / "dev", output_root)
