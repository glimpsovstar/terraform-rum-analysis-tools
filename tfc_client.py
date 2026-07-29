"""Thin HCP Terraform / Terraform Enterprise API client for RUM analysis."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class TfcApiError(RuntimeError):
    """Raised when a TFC/TFE API call fails."""


class TfcClient:
    def __init__(self, hostname: str, token: str, timeout: float = 60.0) -> None:
        host = hostname.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
        self.base_url = f"https://{host}"
        self.token = token
        self.timeout = timeout

    def _request(self, url: str) -> bytes:
        req = Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/vnd.api+json",
            },
            method="GET",
        )
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                body = resp.read()
                status = getattr(resp, "status", 200)
                if status >= 400:
                    raise TfcApiError(f"TFC/TFE API error {status} for {url}")
                return body
        except HTTPError as exc:
            raise TfcApiError(f"TFC/TFE API error {exc.code} for {url}") from exc
        except URLError as exc:
            raise TfcApiError(f"TFC/TFE network error for {url}: {exc.reason}") from exc

    def get_workspace_id(self, organization: str, workspace: str) -> str:
        url = f"{self.base_url}/api/v2/organizations/{organization}/workspaces/{workspace}"
        payload = json.loads(self._request(url))
        try:
            return payload["data"]["id"]
        except (KeyError, TypeError) as exc:
            raise TfcApiError("Unexpected workspace API response") from exc

    def get_workspace(self, organization: str, workspace: str) -> dict[str, Any]:
        url = f"{self.base_url}/api/v2/organizations/{organization}/workspaces/{workspace}"
        payload = json.loads(self._request(url))
        try:
            data = payload["data"]
            project = (
                data.get("relationships", {})
                .get("project", {})
                .get("data")
                or {}
            )
            return {
                "id": data["id"],
                "name": data.get("attributes", {}).get("name", workspace),
                "project_id": project.get("id"),
                "project_name": None,
            }
        except (KeyError, TypeError) as exc:
            raise TfcApiError("Unexpected workspace API response") from exc

    def get_project_id(self, organization: str, project_name: str) -> str:
        url = f"{self.base_url}/api/v2/organizations/{organization}/projects/{project_name}"
        payload = json.loads(self._request(url))
        try:
            return payload["data"]["id"]
        except (KeyError, TypeError) as exc:
            raise TfcApiError("Unexpected project API response") from exc

    def list_workspaces(
        self,
        organization: str,
        *,
        project_id: str | None = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        workspaces: list[dict[str, Any]] = []
        page = 1
        while True:
            query: dict[str, str | int] = {
                "page[number]": page,
                "page[size]": page_size,
                "include": "project",
            }
            if project_id:
                query["filter[project][id]"] = project_id
            url = (
                f"{self.base_url}/api/v2/organizations/{organization}/workspaces"
                f"?{urlencode(query)}"
            )
            payload = json.loads(self._request(url))
            included_projects = {
                item["id"]: item.get("attributes", {}).get("name")
                for item in payload.get("included", [])
                if item.get("type") == "projects"
            }
            for item in payload.get("data", []):
                project = (
                    item.get("relationships", {})
                    .get("project", {})
                    .get("data")
                    or {}
                )
                project_ref_id = project.get("id")
                workspaces.append(
                    {
                        "id": item["id"],
                        "name": item.get("attributes", {}).get("name"),
                        "project_id": project_ref_id,
                        "project_name": included_projects.get(project_ref_id),
                    }
                )
            next_page = (
                payload.get("meta", {})
                .get("pagination", {})
                .get("next-page")
            )
            if not next_page:
                break
            page = int(next_page)
        return workspaces

    def download_current_state(self, workspace_id: str) -> dict[str, Any]:
        meta_url = f"{self.base_url}/api/v2/workspaces/{workspace_id}/current-state-version"
        meta = json.loads(self._request(meta_url))
        try:
            download_url = meta["data"]["attributes"]["hosted-state-download-url"]
        except (KeyError, TypeError) as exc:
            raise TfcApiError("No hosted-state-download-url on current state version") from exc
        if not download_url:
            raise TfcApiError("Workspace current state version has empty download URL")
        return json.loads(self._request(download_url))
