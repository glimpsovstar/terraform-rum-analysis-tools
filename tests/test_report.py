import json
from pathlib import Path

import pandas as pd

from inventory import extract_inventory
from report import build_report, render_table, write_inventory_csv, write_json

FIX = Path(__file__).parent / "fixtures"


def _combined_inventory() -> pd.DataFrame:
    aws = extract_inventory(
        json.loads((FIX / "sample_aws.tfstate").read_text(encoding="utf-8")),
        workspace_name="a",
        workspace_id="ws-A",
        organization="o",
        project_id="prj-PLATFORM",
        project_name="platform",
    )
    azu = extract_inventory(
        json.loads((FIX / "sample_azurerm.tfstate").read_text(encoding="utf-8")),
        workspace_name="b",
        workspace_id="ws-B",
        organization="o",
        project_id="prj-PLATFORM",
        project_name="platform",
    )
    return pd.concat([aws, azu], ignore_index=True)


def test_rollup_totals_and_providers():
    rep = build_report(
        _combined_inventory(),
        errors=[],
        scope="organization",
        organization="o",
        project=None,
    )
    assert rep["totals"]["instances"] == 5
    assert rep["totals"]["workspaces_succeeded"] == 2
    assert rep["totals"]["workspaces_failed"] == 0
    providers = {r["provider"]: r["instances"] for r in rep["by_provider"]}
    assert providers["hashicorp/aws"] == 2
    assert providers["hashicorp/azurerm"] == 3
    assert abs(sum(r["pct"] for r in rep["by_provider"]) - 100.0) < 0.01
    assert len(rep["by_workspace"]) == 2
    assert len(rep["by_project"]) == 1
    assert rep["by_project"][0]["instances"] == 5


def test_errors_counted():
    rep = build_report(
        _combined_inventory(),
        errors=[{"workspace_id": "ws-C", "workspace_name": "c", "error": "404"}],
        scope="organization",
        organization="o",
        project=None,
    )
    assert rep["totals"]["workspaces_failed"] == 1
    assert len(rep["errors"]) == 1


def test_render_and_exports(tmp_path):
    rep = build_report(
        _combined_inventory(),
        errors=[],
        scope="organization",
        organization="o",
        project=None,
    )
    text = render_table(rep)
    assert "Totals" in text
    assert "hashicorp/aws" in text
    out_json = tmp_path / "summary.json"
    out_csv = tmp_path / "inventory.csv"
    write_json(rep, out_json)
    write_inventory_csv(_combined_inventory(), out_csv)
    assert out_json.exists()
    assert out_csv.exists()
    assert '"instances": 5' in out_json.read_text(encoding="utf-8")
