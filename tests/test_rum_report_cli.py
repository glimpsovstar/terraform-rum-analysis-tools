import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rum_report import collect_inventory, main

FIX = Path(__file__).parent / "fixtures"


def test_local_workspace_report_json(capsys):
    code = main(
        [
            "--scope",
            "workspace",
            "-f",
            str(FIX / "sample_aws.tfstate"),
            "--format",
            "json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["totals"]["instances"] == 2
    assert payload["by_provider"][0]["provider"] == "hashicorp/aws"


def test_local_and_remote_mutex():
    code = main(
        [
            "--scope",
            "workspace",
            "-f",
            str(FIX / "sample_aws.tfstate"),
            "--organization",
            "o",
            "--workspace",
            "w",
        ]
    )
    assert code == 2


def test_collect_inventory_org_scope_rollups():
    client = MagicMock()
    aws = json.loads((FIX / "sample_aws.tfstate").read_text(encoding="utf-8"))
    azu = json.loads((FIX / "sample_azurerm.tfstate").read_text(encoding="utf-8"))

    def download(workspace_id):
        return aws if workspace_id == "ws-A" else azu

    client.download_current_state.side_effect = download
    refs = [
        {
            "id": "ws-A",
            "name": "a",
            "project_id": "prj-PLATFORM",
            "project_name": "platform",
        },
        {
            "id": "ws-B",
            "name": "b",
            "project_id": "prj-PLATFORM",
            "project_name": "platform",
        },
    ]
    with patch("rum_report.discover_workspaces", return_value=refs):
        df, errors = collect_inventory(
            client,
            scope="organization",
            organization="o",
            concurrency=2,
            max_workspaces=None,
            hide_hashi=False,
            only_hashi=False,
        )
    assert errors == []
    assert int(df["instance_count"].sum()) == 5


def test_collect_inventory_records_errors_and_continues():
    client = MagicMock()
    aws = json.loads((FIX / "sample_aws.tfstate").read_text(encoding="utf-8"))

    def download(workspace_id):
        if workspace_id == "ws-B":
            raise RuntimeError("boom")
        return aws

    client.download_current_state.side_effect = download
    refs = [
        {"id": "ws-A", "name": "a", "project_id": "p", "project_name": "p"},
        {"id": "ws-B", "name": "b", "project_id": "p", "project_name": "p"},
    ]
    with patch("rum_report.discover_workspaces", return_value=refs):
        df, errors = collect_inventory(
            client,
            scope="organization",
            organization="o",
            concurrency=2,
            max_workspaces=None,
            hide_hashi=False,
            only_hashi=False,
        )
    assert int(df["instance_count"].sum()) == 2
    assert len(errors) == 1
    assert errors[0]["workspace_id"] == "ws-B"


def test_html_format_writes_dashboard(tmp_path, capsys):
    out = tmp_path / "dash.html"
    code = main(
        [
            "--scope",
            "workspace",
            "-f",
            str(FIX / "sample_aws.tfstate"),
            "--format",
            "html",
            "--output",
            str(out),
        ]
    )
    assert code == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "RUM" in text and "Findings" in text
    assert "Wrote HTML report:" in capsys.readouterr().out


def test_strict_exits_nonzero_on_partial_failure():
    client = MagicMock()
    client.download_current_state.side_effect = RuntimeError("no state")
    refs = [{"id": "ws-A", "name": "a", "project_id": None, "project_name": None}]
    with patch("rum_report.resolve_token", return_value="t"), patch(
        "rum_report.TfcClient", return_value=client
    ), patch("rum_report.discover_workspaces", return_value=refs):
        code = main(
            [
                "--scope",
                "organization",
                "--organization",
                "o",
                "--strict",
                "--format",
                "json",
            ]
        )
    assert code == 1
