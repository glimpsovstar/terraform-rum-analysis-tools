"""Extract normalized RUM inventory rows from Terraform raw state JSON."""

from __future__ import annotations

import re
from typing import Any, Iterable

import pandas as pd

_PROVIDER_RE = re.compile(r'provider\["([^"]+)"\]')
DEFAULT_EXCLUDE = frozenset({"null_resource", "terraform_data"})


def normalize_provider(provider_raw: str | None) -> str:
    """Normalize a Terraform state provider address to ``namespace/name``."""
    if not provider_raw:
        return "unknown"
    match = _PROVIDER_RE.search(provider_raw)
    if not match:
        return provider_raw or "unknown"
    addr = match.group(1)
    parts = addr.split("/")
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return addr


def extract_inventory(
    state_data: dict[str, Any],
    *,
    organization: str | None = None,
    project_id: str | None = None,
    project_name: str | None = None,
    workspace_id: str | None = None,
    workspace_name: str | None = None,
    exclude_types: Iterable[str] | None = None,
    only_hashi: bool = False,
    hide_hashi: bool = False,
) -> pd.DataFrame:
    """
    Return one row per managed resource instance.

    Excludes ``null_resource`` and ``terraform_data`` by default.
    """
    exclude = set(exclude_types) if exclude_types is not None else set(DEFAULT_EXCLUDE)
    rows: list[dict[str, Any]] = []

    for resource in state_data.get("resources", []):
        if resource.get("mode") != "managed":
            continue
        rtype = resource.get("type", "unknown")
        if rtype in exclude:
            continue
        is_hashi = rtype.startswith("tfe_") or rtype.startswith("vault_")
        if hide_hashi and is_hashi:
            continue
        if only_hashi and not is_hashi:
            continue

        provider_raw = resource.get("provider", "unknown")
        for _instance in resource.get("instances", []):
            rows.append(
                {
                    "organization": organization,
                    "project_id": project_id,
                    "project_name": project_name,
                    "workspace_id": workspace_id,
                    "workspace_name": workspace_name,
                    "module": resource.get("module", "root"),
                    "resource_type": rtype,
                    "resource_name": resource.get("name", "unknown"),
                    "provider": normalize_provider(provider_raw),
                    "provider_raw": provider_raw,
                    "instance_count": 1,
                }
            )

    return pd.DataFrame(rows)
