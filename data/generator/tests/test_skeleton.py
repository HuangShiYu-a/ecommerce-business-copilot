"""S3.0 骨架最小测试：profiles 可读入 + generate 建路径 + CLI 退出码 0。"""
import subprocess
import sys
from pathlib import Path

import pytest

from data.generator.config import load_config
from data.generator.generate import generate

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


@pytest.mark.parametrize("profile", ["dev", "eval", "full"])
def test_profiles_loadable(profile):
    cfg = load_config(profile)
    assert cfg.dataset.seed == 42
    assert cfg.dataset.as_of_date == "2026-09-17"
    assert cfg.profile.name == profile


def test_generate_creates_canonical_and_manifest(tmp_path):
    cfg = load_config("dev")
    out = generate(cfg, output_root=tmp_path)
    assert out.name == "canonical"
    manifest = out / "manifest.json"
    assert manifest.exists()
    assert "tables" in manifest.read_text(encoding="utf-8")


def test_cli_exit_zero():
    result = subprocess.run(
        [sys.executable, "-m", "data.generator", "--profile", "dev"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK profile=dev" in result.stdout


def test_cli_bad_profile_returns_one():
    result = subprocess.run(
        [sys.executable, "-m", "data.generator", "--profile", "nope"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
