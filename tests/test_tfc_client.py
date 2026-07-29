import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from tfc_client import TfcApiError, TfcClient

FIX = Path(__file__).parent / "fixtures"


def _resp(body: bytes, status: int = 200):
    mock = MagicMock()
    mock.status = status
    mock.read.return_value = body
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    return mock


def test_get_workspace_id():
    body = (FIX / "workspace_show.json").read_bytes()
    client = TfcClient("app.terraform.io", "token")
    with patch("tfc_client.urlopen", return_value=_resp(body)) as mocked:
        assert client.get_workspace_id("my-org", "prod-net") == "ws-A"
        req = mocked.call_args.args[0]
        assert req.full_url.endswith("/api/v2/organizations/my-org/workspaces/prod-net")
        assert req.get_header("Authorization") == "Bearer token"


def test_get_project_id():
    body = (FIX / "project_show.json").read_bytes()
    client = TfcClient("app.terraform.io", "token")
    with patch("tfc_client.urlopen", return_value=_resp(body)):
        assert client.get_project_id("my-org", "platform") == "prj-PLATFORM"


def test_list_workspaces_paginates_and_maps_project():
    page1 = (FIX / "workspaces_page1.json").read_bytes()
    page2 = (FIX / "workspaces_page2.json").read_bytes()
    client = TfcClient("app.terraform.io", "token")
    with patch("tfc_client.urlopen", side_effect=[_resp(page1), _resp(page2)]) as mocked:
        workspaces = client.list_workspaces("my-org", page_size=100)
        assert [w["id"] for w in workspaces] == ["ws-A", "ws-B"]
        assert workspaces[0]["project_id"] == "prj-PLATFORM"
        assert workspaces[0]["project_name"] == "platform"
        first_url = mocked.call_args_list[0].args[0].full_url
        parsed = urlparse(first_url)
        qs = parse_qs(parsed.query)
        assert qs["page[size]"] == ["100"]
        assert qs["page[number]"] == ["1"]


def test_list_workspaces_project_filter_encoded():
    page = (FIX / "workspaces_page2.json").read_bytes()
    # Force single page by using page2 meta (next-page null)
    client = TfcClient("tfe.example.com", "token")
    with patch("tfc_client.urlopen", return_value=_resp(page)) as mocked:
        client.list_workspaces("my-org", project_id="prj-PLATFORM")
        url = mocked.call_args.args[0].full_url
        assert "filter%5Bproject%5D%5Bid%5D=prj-PLATFORM" in url or "filter[project][id]=prj-PLATFORM" in url
        assert url.startswith("https://tfe.example.com/")


def test_download_current_state_uses_hosted_state_url():
    csv = (FIX / "current_state_version.json").read_bytes()
    state = (FIX / "sample_aws.tfstate").read_bytes()
    client = TfcClient("tfe.example.com", "token")
    with patch("tfc_client.urlopen", side_effect=[_resp(csv), _resp(state)]) as mocked:
        data = client.download_current_state("ws-A")
        assert data["resources"][0]["type"] == "aws_instance"
        assert mocked.call_args_list[0].args[0].full_url.endswith(
            "/api/v2/workspaces/ws-A/current-state-version"
        )
        assert mocked.call_args_list[1].args[0].full_url == (
            "https://archivist.example.test/v1/object/raw-state"
        )


def test_api_error_on_401():
    client = TfcClient("app.terraform.io", "bad")
    with patch("tfc_client.urlopen", return_value=_resp(b'{"errors":[]}', status=401)):
        with pytest.raises(TfcApiError, match="401"):
            client.get_workspace_id("o", "w")
