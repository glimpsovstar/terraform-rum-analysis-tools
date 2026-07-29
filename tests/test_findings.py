from findings import build_findings


def _base_report(**overrides):
    report = {
        "meta": {"scope": "organization", "organization": "o", "project": None},
        "totals": {
            "instances": 10,
            "unique_resource_types": 2,
            "unique_providers": 1,
            "workspaces_succeeded": 2,
            "workspaces_failed": 0,
        },
        "by_provider": [{"provider": "hashicorp/aws", "instances": 10, "pct": 100.0}],
        "by_resource_type": [{"resource_type": "aws_instance", "instances": 10, "pct": 100.0}],
        "by_workspace": [
            {"workspace_id": "ws-A", "workspace_name": "a", "instances": 7},
            {"workspace_id": "ws-B", "workspace_name": "b", "instances": 3},
        ],
        "by_project": [],
        "errors": [],
    }
    report.update(overrides)
    return report


def test_empty_inventory_finding():
    report = _base_report(
        totals={
            "instances": 0,
            "unique_resource_types": 0,
            "unique_providers": 0,
            "workspaces_succeeded": 0,
            "workspaces_failed": 0,
        },
        by_provider=[],
        by_resource_type=[],
        by_workspace=[],
    )
    findings = build_findings(report, [])
    assert any(f["id"] == "empty-inventory" for f in findings)
    assert findings[0]["severity"] == "high"


def test_workspace_errors_finding():
    report = _base_report(
        errors=[{"workspace_id": "ws-C", "workspace_name": "c", "error": "404"}],
        totals={
            "instances": 10,
            "unique_resource_types": 1,
            "unique_providers": 1,
            "workspaces_succeeded": 2,
            "workspaces_failed": 1,
        },
    )
    findings = build_findings(report, [])
    err = next(f for f in findings if f["id"] == "workspace-errors")
    assert err["severity"] == "high"
    assert len(err["detail_rows"]) == 1


def test_provider_concentration_and_hotspot():
    report = _base_report()
    inventory = [
        {
            "workspace_name": "a",
            "provider": "hashicorp/aws",
            "resource_type": "aws_instance",
            "resource_name": "web",
            "instance_count": 1,
        }
    ] * 7 + [
        {
            "workspace_name": "b",
            "provider": "hashicorp/aws",
            "resource_type": "aws_instance",
            "resource_name": "web",
            "instance_count": 1,
        }
    ] * 3
    findings = build_findings(report, inventory)
    ids = {f["id"] for f in findings}
    assert "provider-concentration" in ids
    assert "workspace-hotspot" in ids
    assert "top-resource-type" in ids


def test_no_hotspot_for_single_workspace():
    report = _base_report(
        by_workspace=[{"workspace_id": "ws-A", "workspace_name": "a", "instances": 10}],
        totals={
            "instances": 10,
            "unique_resource_types": 1,
            "unique_providers": 1,
            "workspaces_succeeded": 1,
            "workspaces_failed": 0,
        },
    )
    findings = build_findings(report, [])
    assert "workspace-hotspot" not in {f["id"] for f in findings}
