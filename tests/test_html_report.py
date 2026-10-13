import json
from pathlib import Path

import pandas as pd

from html_report import render_html_report, write_html_report
from inventory import extract_inventory
from report import build_report

FIX = Path(__file__).parent / "fixtures"


def _sample_report_and_df():
    state = json.loads((FIX / "sample_aws.tfstate").read_text(encoding="utf-8"))
    df = extract_inventory(
        state,
        organization="acme",
        workspace_name="prod-net",
        workspace_id="ws-A",
        project_name="platform",
        project_id="prj-PLATFORM",
    )
    # Inject a XSS-y name for escaping checks
    df = pd.concat(
        [
            df,
            pd.DataFrame(
                [
                    {
                        "organization": "acme",
                        "project_id": "prj-PLATFORM",
                        "project_name": "platform",
                        "workspace_id": "ws-A",
                        "workspace_name": "prod-net",
                        "module": "root",
                        "resource_type": "aws_instance",
                        "resource_name": '<script>alert("x")</script>',
                        "provider": "hashicorp/aws",
                        "provider_raw": 'provider["registry.terraform.io/hashicorp/aws"]',
                        "instance_count": 1,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    report = build_report(
        df,
        errors=[{"workspace_id": "ws-B", "workspace_name": "broken", "error": "404"}],
        scope="project",
        organization="acme",
        project="platform",
    )
    return report, df


def test_html_contains_dashboard_landmarks():
    report, df = _sample_report_and_df()
    html = render_html_report(report, df, generated_at="2026-07-29 00:00 UTC")
    assert "<!DOCTYPE html>" in html
    assert "RUM" in html and "Analysis" in html
    assert 'id="kpi-instances"' in html
    assert str(report["totals"]["instances"]) in html
    assert "Findings" in html
    assert "Inventory detail" in html
    assert "Breakdowns" in html
    assert "workspace-errors" in html
    assert "2026-07-29 00:00 UTC" in html


def test_html_escapes_script_in_resource_names():
    report, df = _sample_report_and_df()
    html = render_html_report(report, df)
    # Must not introduce a real script tag from the resource name in HTML body.
    assert "<script>alert" not in html
    # Escaped form or JSON unicode-safe form should appear in embedded data.
    assert "\\u003cscript\\u003e" in html or "&lt;script&gt;" in html


def test_write_html_report(tmp_path):
    report, df = _sample_report_and_df()
    path = write_html_report(tmp_path / "out", report, df)
    assert path.suffix == ".html"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "rum-data" in text
