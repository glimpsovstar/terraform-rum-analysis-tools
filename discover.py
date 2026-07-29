"""Resolve org/project/workspace scope to a list of workspace references."""

from __future__ import annotations

from typing import Any

from tfc_client import TfcClient

WorkspaceRef = dict[str, Any]


def discover_workspaces(
    client: TfcClient,
    scope: str,
    *,
    organization: str | None = None,
    workspace: str | None = None,
    workspace_id: str | None = None,
    project: str | None = None,
    project_id: str | None = None,
) -> list[WorkspaceRef]:
    """
    Return workspace refs for the requested scope.

    Each ref contains: id, name, project_id, project_name.
    """
    if scope not in {"workspace", "project", "organization"}:
        raise ValueError(f"Unsupported scope: {scope}")

    if scope == "workspace":
        if workspace_id:
            return [
                {
                    "id": workspace_id,
                    "name": workspace or workspace_id,
                    "project_id": project_id,
                    "project_name": project,
                }
            ]
        if not organization or not workspace:
            raise ValueError("workspace scope requires --organization and --workspace (or --workspace-id)")
        return [client.get_workspace(organization, workspace)]

    if not organization:
        raise ValueError("organization is required for project and organization scopes")

    if scope == "project":
        resolved_project_id = project_id
        if not resolved_project_id:
            if not project:
                raise ValueError("project scope requires --project or --project-id")
            resolved_project_id = client.get_project_id(organization, project)
        return client.list_workspaces(organization, project_id=resolved_project_id)

    return client.list_workspaces(organization, project_id=None)
