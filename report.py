"""Build and render scoped RUM reports from inventory rows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def _breakdown(df: pd.DataFrame, column: str, total: int) -> list[dict[str, Any]]:
    if df.empty or column not in df.columns:
        return []
    grouped = (
        df.groupby(column, dropna=False)["instance_count"]
        .sum()
        .sort_values(ascending=False)
    )
    rows: list[dict[str, Any]] = []
    for key, count in grouped.items():
        instances = int(count)
        pct = (instances / total * 100.0) if total else 0.0
        rows.append({column: key, "instances": instances, "pct": round(pct, 2)})
    return rows


def build_report(
    inventory_df: pd.DataFrame,
    *,
    errors: list[dict[str, Any]],
    scope: str,
    organization: str | None,
    project: str | None,
) -> dict[str, Any]:
    df = inventory_df if inventory_df is not None else pd.DataFrame()
    total_instances = int(df["instance_count"].sum()) if not df.empty else 0
    if df.empty:
        succeeded = 0
    elif df["workspace_id"].notna().any():
        succeeded = int(df["workspace_id"].nunique())
    else:
        succeeded = int(df["workspace_name"].nunique())

    by_provider = []
    if not df.empty:
        for row in _breakdown(df, "provider", total_instances):
            by_provider.append(
                {
                    "provider": row["provider"],
                    "instances": row["instances"],
                    "pct": row["pct"],
                }
            )

    by_resource_type = []
    if not df.empty:
        for row in _breakdown(df, "resource_type", total_instances):
            by_resource_type.append(
                {
                    "resource_type": row["resource_type"],
                    "instances": row["instances"],
                    "pct": row["pct"],
                }
            )

    by_workspace: list[dict[str, Any]] = []
    if not df.empty:
        group_cols = [c for c in ("workspace_id", "workspace_name") if c in df.columns]
        grouped = df.groupby(group_cols, dropna=False)["instance_count"].sum().reset_index()
        for _, row in grouped.sort_values("instance_count", ascending=False).iterrows():
            by_workspace.append(
                {
                    "workspace_id": row.get("workspace_id"),
                    "workspace_name": row.get("workspace_name"),
                    "instances": int(row["instance_count"]),
                }
            )

    by_project: list[dict[str, Any]] = []
    if not df.empty and "project_id" in df.columns and df["project_id"].notna().any():
        grouped = (
            df.groupby(["project_id", "project_name"], dropna=False)["instance_count"]
            .sum()
            .reset_index()
        )
        for _, row in grouped.sort_values("instance_count", ascending=False).iterrows():
            by_project.append(
                {
                    "project_id": row.get("project_id"),
                    "project_name": row.get("project_name"),
                    "instances": int(row["instance_count"]),
                }
            )

    unique_types = int(df["resource_type"].nunique()) if not df.empty else 0
    unique_providers = int(df["provider"].nunique()) if not df.empty else 0

    return {
        "meta": {
            "scope": scope,
            "organization": organization,
            "project": project,
        },
        "totals": {
            "instances": total_instances,
            "unique_resource_types": unique_types,
            "unique_providers": unique_providers,
            "workspaces_succeeded": succeeded,
            "workspaces_failed": len(errors),
        },
        "by_provider": by_provider,
        "by_resource_type": by_resource_type,
        "by_workspace": by_workspace,
        "by_project": by_project,
        "errors": errors,
    }


def render_table(report: dict[str, Any]) -> str:
    lines: list[str] = []
    meta = report["meta"]
    totals = report["totals"]
    lines.append("RUM Report")
    lines.append("=" * 40)
    lines.append(f"Scope: {meta.get('scope')}")
    lines.append(f"Organization: {meta.get('organization')}")
    if meta.get("project"):
        lines.append(f"Project: {meta.get('project')}")
    lines.append("")
    lines.append("Totals")
    lines.append("-" * 40)
    lines.append(f"Managed instances: {totals['instances']}")
    lines.append(f"Unique resource types: {totals['unique_resource_types']}")
    lines.append(f"Unique providers: {totals['unique_providers']}")
    lines.append(f"Workspaces succeeded: {totals['workspaces_succeeded']}")
    lines.append(f"Workspaces failed: {totals['workspaces_failed']}")

    def _section(title: str, rows: list[dict[str, Any]], key: str) -> None:
        lines.append("")
        lines.append(title)
        lines.append("-" * 40)
        if not rows:
            lines.append("(none)")
            return
        for row in rows:
            pct = row.get("pct")
            suffix = f" ({pct}%)" if pct is not None else ""
            lines.append(f"{row.get(key)}: {row.get('instances')}{suffix}")

    _section("By provider", report["by_provider"], "provider")
    _section("By resource type", report["by_resource_type"], "resource_type")

    lines.append("")
    lines.append("By workspace")
    lines.append("-" * 40)
    if not report["by_workspace"]:
        lines.append("(none)")
    else:
        for row in report["by_workspace"]:
            name = row.get("workspace_name") or row.get("workspace_id")
            lines.append(f"{name}: {row.get('instances')}")

    if report["by_project"]:
        lines.append("")
        lines.append("By project")
        lines.append("-" * 40)
        for row in report["by_project"]:
            name = row.get("project_name") or row.get("project_id")
            lines.append(f"{name}: {row.get('instances')}")

    if report["errors"]:
        lines.append("")
        lines.append("Errors")
        lines.append("-" * 40)
        for err in report["errors"]:
            name = err.get("workspace_name") or err.get("workspace_id")
            lines.append(f"{name}: {err.get('error')}")

    return "\n".join(lines)


def write_json(report: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def write_inventory_csv(inventory_df: pd.DataFrame, path: str | Path) -> None:
    inventory_df.to_csv(path, index=False)
