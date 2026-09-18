"""P7 / S3.6 校验骨架门禁测试：报告生成 / 无 P0 失败 / 13 项检查覆盖。"""
import json
from pathlib import Path

import pytest

from data.generator.config import load_config
from data.generator.generate import generate

CHECK_IDS = [
    "schema_fk", "s12a_status", "time_order", "after_sales_qty", "derived_after_delivery",
    "price_history", "role_narrative", "sales_shape", "sc_preconditions", "op07_core_dims",
    "knowledge_lifecycle", "isolation", "fixture_tolerance", "scope_mutual_exclusion",
]


@pytest.fixture()
def report(tmp_path):
    generate(load_config("dev"), output_root=tmp_path)
    p = tmp_path / "dev" / "validate_report.json"
    assert p.exists()
    return json.loads(p.read_text(encoding="utf-8"))


def test_report_generated_and_gate_pass(report):
    assert report["gate"] == "PASS"
    assert report["p0_failures"] == []


def test_all_checks_present(report):
    ids = {c["id"] for c in report["checks"]}
    assert set(ids) == set(CHECK_IDS)


def test_no_p0_check_failed(report):
    for c in report["checks"]:
        if c["level"] == "P0":
            assert c["passed"], f"{c['id']} 失败: {c['issues']}"


def test_p1_checks_reported(report):
    p1 = [c for c in report["checks"] if c["level"] == "P1"]
    assert len(p1) >= 2  # role_narrative / op07_core_dims
    for c in p1:
        assert "passed" in c and "issues" in c


def test_manifest_has_validate_summary(tmp_path):
    generate(load_config("dev"), output_root=tmp_path)
    manifest = json.loads((tmp_path / "dev" / "canonical" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["validate_gate"] == "PASS"
    assert manifest["validate_p0_failures"] == []
