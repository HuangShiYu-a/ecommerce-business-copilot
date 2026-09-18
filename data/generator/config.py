"""Generator 配置加载：profiles 与数据集级参数（seed / as_of / timeline / timezone）。

默认值来自 S2 §0：seed=42, as_of_date=2026-09-17, timeline_start=2026-06-19, timezone=Asia/Shanghai。
profiles.yaml 中 dev/eval/full 的规模初值来自 S2 §2；精确数值在 S3.1+ 精化。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent / "config"
PROFILES_PATH = CONFIG_DIR / "profiles.yaml"


@dataclass(frozen=True)
class DatasetConfig:
    seed: int
    as_of_date: str
    timeline_start: str
    timezone: str


@dataclass(frozen=True)
class ProfileConfig:
    name: str
    params: dict


@dataclass(frozen=True)
class GeneratorConfig:
    dataset: DatasetConfig
    profile: ProfileConfig


def load_yaml(path: Path) -> dict:
    """读取 YAML 并校验顶层为映射。"""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: YAML 顶层必须是映射")
    return data


def load_config(profile: str, profiles_path: Path = PROFILES_PATH) -> GeneratorConfig:
    """读取 profiles.yaml，构造指定 profile 的配置；profile 不存在则报错。"""
    raw = load_yaml(profiles_path)

    dataset_raw = raw.get("dataset")
    if not isinstance(dataset_raw, dict):
        raise ValueError("profiles.yaml: 缺少 dataset 节（seed/as_of_date/timeline_start/timezone）")

    profiles_raw = raw.get("profiles")
    if not isinstance(profiles_raw, dict):
        raise ValueError("profiles.yaml: 缺少 profiles 节")
    if profile not in profiles_raw:
        available = ", ".join(sorted(profiles_raw))
        raise ValueError(f"profiles.yaml: 不存在 profile '{profile}'（可用：{available}）")

    dataset = DatasetConfig(
        seed=int(dataset_raw["seed"]),
        as_of_date=str(dataset_raw["as_of_date"]),
        timeline_start=str(dataset_raw["timeline_start"]),
        timezone=str(dataset_raw.get("timezone", "Asia/Shanghai")),
    )
    return GeneratorConfig(
        dataset=dataset,
        profile=ProfileConfig(name=profile, params=dict(profiles_raw[profile])),
    )
