"""Derive actionable RUM findings from a report and inventory rows."""

from __future__ import annotations

from typing import Any


def build_findings(
    report: dict[str, Any],
    inventory_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Return findings ordered by severity (high → medium → info).

    Each finding: id, severity, title, summary, category, detail_rows.
    """
    inventory_records = inventory_records or []
    findings: list[dict[str, Any]] = []
    totals = report.get("totals") or {}
    instances = int(totals.get("instances") or 0)

    errors = report.get("errors") or []
    if errors:
        findings.append(
            {
                "id": "workspace-errors",
                "severity": "high",
                "title": f"{len(errors)} workspace(s) failed to analyze",
                "summary": "State download or access failed for one or more workspaces.",
                "category": "availability",
                "detail_rows": list(errors),
            }
        )

    if instances == 0:
        findings.append(
            {
                "id": "empty-inventory",
                "severity": "high",
                "title": "No managed resources found",
                "summary": "Inventory is empty after filters (or no successful workspace state).",
                "category": "inventory",
                "detail_rows": [],
            }
        )
        return _sort_findings(findings)

    for provider_row in report.get("by_provider") or []:
        pct = float(provider_row.get("pct") or 0)
        if pct >= 60.0:
            provider = provider_row.get("provider")
            detail = [r for r in inventory_records if r.get("provider") == provider]
            findings.append(
                {
                    "id": "provider-concentration",
                    "severity": "medium",
                    "title": f"Provider concentration: {provider}",
                    "summary": f"{provider} accounts for {pct}% of managed instances.",
                    "category": "concentration",
                    "detail_rows": detail,
                }
            )
            break  # one concentration finding is enough for v1

    types = report.get("by_resource_type") or []
    if types:
        top = types[0]
        rtype = top.get("resource_type")
        detail = [r for r in inventory_records if r.get("resource_type") == rtype]
        findings.append(
            {
                "id": "top-resource-type",
                "severity": "info",
                "title": f"Top resource type: {rtype}",
                "summary": (
                    f"{rtype} is the most common type "
                    f"({top.get('instances')} instances, {top.get('pct')}%)."
                ),
                "category": "distribution",
                "detail_rows": detail,
            }
        )

    workspaces = report.get("by_workspace") or []
    if len(workspaces) > 1 and instances > 0:
        top_ws = max(workspaces, key=lambda w: int(w.get("instances") or 0))
        ws_instances = int(top_ws.get("instances") or 0)
        pct = ws_instances / instances * 100.0
        if pct >= 40.0:
            name = top_ws.get("workspace_name") or top_ws.get("workspace_id")
            detail = [
                r
                for r in inventory_records
                if r.get("workspace_name") == top_ws.get("workspace_name")
                or r.get("workspace_id") == top_ws.get("workspace_id")
            ]
            findings.append(
                {
                    "id": "workspace-hotspot",
                    "severity": "medium",
                    "title": f"Workspace hotspot: {name}",
                    "summary": (
                        f"{name} holds {ws_instances} instances "
                        f"({round(pct, 2)}% of the analyzed scope)."
                    ),
                    "category": "concentration",
                    "detail_rows": detail,
                }
            )

    return _sort_findings(findings)


def _sort_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {"high": 0, "medium": 1, "info": 2}
    return sorted(findings, key=lambda f: order.get(f.get("severity", "info"), 9))
