from unittest.mock import MagicMock

import pytest

from discover import discover_workspaces


def test_discover_workspace_by_name():
    client = MagicMock()
    client.get_workspace.return_value = {
        "id": "ws-A",
        "name": "prod-net",
        "project_id": "prj-PLATFORM",
        "project_name": None,
    }
    refs = discover_workspaces(
        client,
        "workspace",
        organization="my-org",
        workspace="prod-net",
    )
    assert refs == [
        {
            "id": "ws-A",
            "name": "prod-net",
            "project_id": "prj-PLATFORM",
            "project_name": None,
        }
    ]
    client.get_workspace.assert_called_once_with("my-org", "prod-net")


def test_discover_workspace_by_id():
    refs = discover_workspaces(
        MagicMock(),
        "workspace",
        organization="my-org",
        workspace_id="ws-A",
        workspace="ignored",
    )
    assert refs[0]["id"] == "ws-A"
    assert refs[0]["name"] == "ignored"


def test_discover_project_resolves_name():
    client = MagicMock()
    client.get_project_id.return_value = "prj-PLATFORM"
    client.list_workspaces.return_value = [
        {"id": "ws-A", "name": "prod-net", "project_id": "prj-PLATFORM", "project_name": "platform"}
    ]
    refs = discover_workspaces(
        client,
        "project",
        organization="my-org",
        project="platform",
    )
    client.get_project_id.assert_called_once_with("my-org", "platform")
    client.list_workspaces.assert_called_once_with("my-org", project_id="prj-PLATFORM")
    assert len(refs) == 1


def test_discover_organization():
    client = MagicMock()
    client.list_workspaces.return_value = [
        {"id": "ws-A", "name": "a", "project_id": "p1", "project_name": "p"},
        {"id": "ws-B", "name": "b", "project_id": "p1", "project_name": "p"},
    ]
    refs = discover_workspaces(client, "organization", organization="my-org")
    assert len(refs) == 2
    client.list_workspaces.assert_called_once_with("my-org", project_id=None)


def test_discover_requires_org():
    with pytest.raises(ValueError, match="organization"):
        discover_workspaces(MagicMock(), "organization")
