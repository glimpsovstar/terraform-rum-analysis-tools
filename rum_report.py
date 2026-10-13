#!/usr/bin/env python3
"""
Scoped RUM reporting for local Terraform state or HCP Terraform / TFE.

Scopes:
  - workspace: one workspace (local -f or remote)
  - project: all workspaces in a project
  - organization: all workspaces in an organization

Examples:
  python3 rum_report.py --scope workspace -f terraform.tfstate
  python3 rum_report.py --scope workspace --organization ORG --workspace WS
  python3 rum_report.py --scope project --organization ORG --project platform
  python3 rum_report.py --scope organization --organization ORG --format json
  python3 rum_report.py --scope workspace -f terraform.tfstate --format html --output rum.html
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd

from discover import discover_workspaces
from inventory import extract_inventory
from html_report import write_html_report
from report import build_report, render_table, write_inventory_csv, write_json
from tfc_client import TfcApiError, TfcClient


def resolve_token(cli_token: str | None) -> str | None:
    return cli_token or os.environ.get("TFE_TOKEN") or None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze Terraform RUM at workspace, project, or organization scope."
    )
    parser.add_argument(
        "--scope",
        choices=("workspace", "project", "organization"),
        default="workspace",
        help="Analysis scope (default: workspace).",
    )
    parser.add_argument("-f", "--file", help="Local Terraform state file (.tfstate).")
    parser.add_argument(
        "--organization",
        default=None,
        help="TFC/TFE organization name (or TFC_ORGANIZATION for remote runs).",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace name (or TFC_WORKSPACE for remote runs).",
    )
    parser.add_argument("--workspace-id", default=None, help="Workspace ID (ws-...).")
    parser.add_argument(
        "--project",
        default=None,
        help="Project name (or TFC_PROJECT for remote runs).",
    )
    parser.add_argument("--project-id", default=None, help="Project ID (prj-...).")
    parser.add_argument(
        "--hostname",
        default=os.environ.get("TFE_HOSTNAME", "app.terraform.io"),
        help="TFC/TFE hostname (default app.terraform.io or TFE_HOSTNAME).",
    )
    parser.add_argument("--token", default=None, help="API token (prefer TFE_TOKEN).")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Max parallel state downloads (default: 5).",
    )
    parser.add_argument(
        "--max-workspaces",
        type=int,
        default=None,
        help="Optional cap on workspaces processed (debug/sampling).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any workspace fails.",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json", "csv", "html"),
        default="table",
        help="Output format (default: table). Use html for a dashboard file.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write report artifacts to this path prefix or file (required intent for html; defaults to rum-report.html).",
    )
    parser.add_argument(
        "-H",
        "--hide-tfe-vault",
        action="store_true",
        help="Exclude tfe_ and vault_ resources.",
    )
    parser.add_argument(
        "-Ho",
        "--only-tfe-vault",
        action="store_true",
        help="Only include tfe_ and vault_ resources.",
    )
    return parser.parse_args(argv)


def apply_remote_env_defaults(args: argparse.Namespace) -> None:
    """Fill remote identity from env only when CLI flags were omitted.

    Local ``--file`` analysis must ignore ``TFC_WORKSPACE`` / ``TFC_PROJECT`` so
    operators can analyze a downloaded state file with TFC env vars still set.
    """
    if args.organization is None:
        args.organization = os.environ.get("TFC_ORGANIZATION")
    if args.file:
        return
    if args.workspace is None:
        args.workspace = os.environ.get("TFC_WORKSPACE")
    if args.project is None:
        args.project = os.environ.get("TFC_PROJECT")


def _fetch_one(
    client: TfcClient,
    ref: dict[str, Any],
    *,
    organization: str | None,
    hide_hashi: bool,
    only_hashi: bool,
) -> tuple[pd.DataFrame | None, dict[str, Any] | None]:
    try:
        state = client.download_current_state(ref["id"])
        df = extract_inventory(
            state,
            organization=organization,
            project_id=ref.get("project_id"),
            project_name=ref.get("project_name"),
            workspace_id=ref.get("id"),
            workspace_name=ref.get("name"),
            hide_hashi=hide_hashi,
            only_hashi=only_hashi,
        )
        return df, None
    except Exception as exc:  # noqa: BLE001 - per-workspace isolation
        return None, {
            "workspace_id": ref.get("id"),
            "workspace_name": ref.get("name"),
            "error": str(exc),
        }


def collect_inventory(
    client: TfcClient,
    *,
    scope: str,
    organization: str | None,
    workspace: str | None = None,
    workspace_id: str | None = None,
    project: str | None = None,
    project_id: str | None = None,
    concurrency: int = 5,
    max_workspaces: int | None = None,
    hide_hashi: bool = False,
    only_hashi: bool = False,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    refs = discover_workspaces(
        client,
        scope,
        organization=organization,
        workspace=workspace,
        workspace_id=workspace_id,
        project=project,
        project_id=project_id,
    )
    if max_workspaces is not None:
        refs = refs[: max(0, max_workspaces)]

    frames: list[pd.DataFrame] = []
    errors: list[dict[str, Any]] = []
    workers = max(1, concurrency)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                _fetch_one,
                client,
                ref,
                organization=organization,
                hide_hashi=hide_hashi,
                only_hashi=only_hashi,
            )
            for ref in refs
        ]
        for future in as_completed(futures):
            df, err = future.result()
            if err:
                errors.append(err)
            elif df is not None:
                frames.append(df)

    if not frames:
        return pd.DataFrame(), errors
    return pd.concat(frames, ignore_index=True), errors


def _write_outputs(
    report: dict[str, Any],
    inventory_df: pd.DataFrame,
    output: str,
    fmt: str,
) -> Path | None:
    path = Path(output)
    if fmt == "html" or path.suffix.lower() == ".html":
        return write_html_report(path if path.suffix else Path(f"{output}.html"), report, inventory_df)
    if fmt == "csv" or path.suffix.lower() == ".csv":
        write_inventory_csv(inventory_df, path if path.suffix else Path(f"{output}.csv"))
        if path.suffix.lower() == ".csv":
            summary_path = path.with_suffix(".summary.json")
        else:
            summary_path = Path(f"{output}.summary.json")
        write_json(report, summary_path)
        return summary_path
    if fmt == "json" or path.suffix.lower() == ".json":
        write_json(report, path if path.suffix else Path(f"{output}.json"))
        csv_path = path.with_suffix(".inventory.csv") if path.suffix else Path(f"{output}.inventory.csv")
        write_inventory_csv(inventory_df, csv_path)
        return Path(path if path.suffix else f"{output}.json")
    # table + output prefix: write both
    write_json(report, Path(f"{output}.json") if not path.suffix else path)
    write_inventory_csv(
        inventory_df,
        Path(f"{output}.inventory.csv") if not path.suffix else path.with_suffix(".inventory.csv"),
    )
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Mutex uses CLI flags only — env defaults are applied after this check.
    explicit_remote_target = bool(
        args.workspace or args.workspace_id or args.project or args.project_id
    )
    if args.file and (explicit_remote_target or args.scope in {"project", "organization"}):
        print(
            "❌ Error: Provide a local --file or remote workspace/project/org identity, not both.",
            file=sys.stderr,
        )
        return 2

    apply_remote_env_defaults(args)

    hide_hashi = args.hide_tfe_vault
    only_hashi = args.only_tfe_vault

    try:
        if args.file:
            if args.scope != "workspace":
                print("❌ Error: --file is only valid with --scope workspace.", file=sys.stderr)
                return 2
            with open(args.file, "r", encoding="utf-8") as fh:
                state = json.load(fh)
            inventory_df = extract_inventory(
                state,
                organization=args.organization,
                workspace_name=Path(args.file).name,
                hide_hashi=hide_hashi,
                only_hashi=only_hashi,
            )
            errors: list[dict[str, Any]] = []
        else:
            token = resolve_token(args.token)
            if not token:
                print(
                    "❌ Error: Provide --file for a local state file, "
                    "or TFE_TOKEN/--token plus organization/workspace for TFC/TFE.",
                    file=sys.stderr,
                )
                return 2
            if args.scope in {"project", "organization"} and not args.organization:
                print("❌ Error: --organization is required for this scope.", file=sys.stderr)
                return 2
            client = TfcClient(args.hostname, token)
            inventory_df, errors = collect_inventory(
                client,
                scope=args.scope,
                organization=args.organization,
                workspace=args.workspace,
                workspace_id=args.workspace_id,
                project=args.project,
                project_id=args.project_id,
                concurrency=args.concurrency,
                max_workspaces=args.max_workspaces,
                hide_hashi=hide_hashi,
                only_hashi=only_hashi,
            )
    except (OSError, json.JSONDecodeError, TfcApiError, ValueError) as exc:
        print(f"❌ Error: {exc}", file=sys.stderr)
        return 2

    report = build_report(
        inventory_df,
        errors=errors,
        scope=args.scope,
        organization=args.organization,
        project=args.project or args.project_id,
    )

    if args.format == "html":
        output = args.output or "rum-report.html"
        written = _write_outputs(report, inventory_df, output, "html")
        print(f"Wrote HTML report: {written}")
        print(
            f"Instances={report['totals']['instances']} "
            f"findings available in dashboard · open the HTML file in a browser"
        )
    elif args.output:
        _write_outputs(report, inventory_df, args.output, args.format)

    if args.format == "json":
        print(json.dumps(report, indent=2))
    elif args.format == "csv":
        if not args.output:
            if inventory_df.empty:
                print(
                    "organization,project_id,project_name,workspace_id,workspace_name,"
                    "module,resource_type,resource_name,provider,provider_raw,instance_count"
                )
            else:
                print(inventory_df.to_csv(index=False).rstrip("\n"))
        else:
            print(render_table(report))
    elif args.format == "table":
        print(render_table(report))

    if args.file:
        return 0

    succeeded = report["totals"]["workspaces_succeeded"]
    failed = report["totals"]["workspaces_failed"]
    if succeeded == 0:
        return 1
    if args.strict and failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
