# TFC/TFE Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the RUM analysis scripts load Terraform state from HCP Terraform / Terraform Enterprise workspaces via API, while keeping local `.tfstate` analysis unchanged.

**Architecture:** Add a shared `state_source` module that returns parsed raw state JSON from either a local file or the TFC/TFE State Versions API (`workspace` → `current-state-version` → `hosted-state-download-url`). Wire remote CLI/env options into the three existing scripts without changing core aggregation logic.

**Tech Stack:** Python 3.9+, stdlib `urllib` + `json` + `argparse`, existing `pandas`, `pytest` for tests.

## Global Constraints

- Prefer raw state download (`hosted-state-download-url`), not `hosted-json-state-download-url`.
- Default hostname: `app.terraform.io`; TFE uses `--hostname` / `TFE_HOSTNAME`.
- Token from `TFE_TOKEN` preferred; optional `--token` allowed but discouraged in docs.
- Exactly one source: `-f/--file` **or** remote workspace identity.
- Do not print tokens or write state to disk unless `--save-state` is set.
- Keep analysis behavior for local files byte-for-byte equivalent (same filters, counts, exits).
- No multi-workspace aggregation in this plan (deferred).

---

## File structure

| Path | Responsibility |
|------|----------------|
| `state_source.py` | Load state from file or TFC/TFE; shared argparse helpers |
| `tfc_client.py` | Thin HTTP client for workspace lookup + state download |
| `terraform_resource_extractor.py` | Use shared loader; add remote flags |
| `extract_resource_type_stats.py` | Use shared loader; add remote flags |
| `temporary_intended_resources.py` | Use shared loader; add remote flags (replace brittle `sys.argv`) |
| `requirements.txt` | Runtime deps (`pandas`) |
| `requirements-dev.txt` | `pytest` |
| `tests/fixtures/*.json` | Sample state + JSON:API responses |
| `tests/test_tfc_client.py` | HTTP client unit tests |
| `tests/test_state_source.py` | Source selection / validation tests |
| `tests/test_extractor_compat.py` | Local fixture still aggregates correctly |
| `README.md` | Document remote usage |
| `docs/superpowers/specs/2026-07-28-tfc-tfe-support-design.md` | Design reference (already written) |

---

### Task 1: Project scaffolding and fixtures

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `tests/fixtures/sample.tfstate`
- Create: `tests/fixtures/workspace_show.json`
- Create: `tests/fixtures/current_state_version.json`
- Modify: `README.md` (add install note only if missing; full remote docs in Task 6)

**Interfaces:**
- Produces: fixture files consumed by later tests; `pip install -r requirements-dev.txt` works

- [ ] **Step 1: Add dependency files**

```text
# requirements.txt
pandas>=2.0

# requirements-dev.txt
-r requirements.txt
pytest>=8.0
```

- [ ] **Step 2: Add a minimal managed-resource state fixture**

`tests/fixtures/sample.tfstate`:

```json
{
  "version": 4,
  "terraform_version": "1.5.0",
  "serial": 1,
  "lineage": "test-lineage",
  "outputs": {},
  "resources": [
    {
      "mode": "managed",
      "type": "aws_instance",
      "name": "web",
      "provider": "provider[\"registry.terraform.io/hashicorp/aws\"]",
      "instances": [
        {"attributes": {"id": "i-1", "name": "web-demo"}},
        {"attributes": {"id": "i-2", "name": "web-prod"}}
      ]
    },
    {
      "mode": "managed",
      "type": "null_resource",
      "name": "ignored",
      "provider": "provider[\"registry.terraform.io/hashicorp/null\"]",
      "instances": [{"attributes": {}}]
    },
    {
      "mode": "data",
      "type": "aws_ami",
      "name": "ami",
      "provider": "provider[\"registry.terraform.io/hashicorp/aws\"]",
      "instances": [{"attributes": {"id": "ami-1"}}]
    }
  ]
}
```

- [ ] **Step 3: Add JSON:API fixtures**

`tests/fixtures/workspace_show.json`:

```json
{
  "data": {
    "id": "ws-TESTWORKSPACE",
    "type": "workspaces",
    "attributes": {
      "name": "prod-net"
    }
  }
}
```

`tests/fixtures/current_state_version.json`:

```json
{
  "data": {
    "id": "sv-TESTSTATE",
    "type": "state-versions",
    "attributes": {
      "hosted-state-download-url": "https://archivist.example.test/v1/object/raw-state",
      "hosted-json-state-download-url": "https://archivist.example.test/v1/object/json-state"
    }
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt requirements-dev.txt tests/fixtures
git commit -m "chore: add deps and fixtures for TFC/TFE support"
```

---

### Task 2: TFC/TFE HTTP client

**Files:**
- Create: `tfc_client.py`
- Create: `tests/test_tfc_client.py`

**Interfaces:**
- Produces:
  - `class TfcClient`
  - `TfcClient(hostname: str, token: str, timeout: float = 60.0)`
  - `get_workspace_id(organization: str, workspace: str) -> str`
  - `download_current_state(workspace_id: str) -> dict`
- Consumes: JSON:API fixtures; mocked `urlopen`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_tfc_client.py
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from tfc_client import TfcClient, TfcApiError

FIX = Path(__file__).parent / "fixtures"


def _resp(body: bytes, status=200):
    mock = MagicMock()
    mock.status = status
    mock.read.return_value = body
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    return mock


def test_get_workspace_id():
    body = (FIX / "workspace_show.json").read_bytes()
    client = TfcClient("app.terraform.io", "token")
    with patch("tfc_client.urlopen", return_value=_resp(body)) as m:
        assert client.get_workspace_id("my-org", "prod-net") == "ws-TESTWORKSPACE"
        req = m.call_args.args[0]
        assert req.full_url.endswith("/api/v2/organizations/my-org/workspaces/prod-net")
        assert req.get_header("Authorization") == "Bearer token"


def test_download_current_state_uses_hosted_state_url():
    csv = (FIX / "current_state_version.json").read_bytes()
    state = (FIX / "sample.tfstate").read_bytes()
    client = TfcClient("tfe.example.com", "token")

    with patch("tfc_client.urlopen", side_effect=[_resp(csv), _resp(state)]) as m:
        data = client.download_current_state("ws-TESTWORKSPACE")
        assert data["resources"][0]["type"] == "aws_instance"
        assert m.call_args_list[0].args[0].full_url.endswith(
            "/api/v2/workspaces/ws-TESTWORKSPACE/current-state-version"
        )
        assert m.call_args_list[1].args[0].full_url == (
            "https://archivist.example.test/v1/object/raw-state"
        )


def test_api_error_on_401():
    client = TfcClient("app.terraform.io", "bad")
    with patch("tfc_client.urlopen", return_value=_resp(b'{"errors":[]}', status=401)):
        with pytest.raises(TfcApiError, match="401"):
            client.get_workspace_id("o", "w")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pip install -r requirements-dev.txt && pytest tests/test_tfc_client.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'tfc_client'`

- [ ] **Step 3: Implement minimal client**

```python
# tfc_client.py
from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TfcApiError(RuntimeError):
    pass


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
                if getattr(resp, "status", 200) >= 400:
                    raise TfcApiError(f"TFC/TFE API error {resp.status} for {url}")
                return body
        except HTTPError as e:
            raise TfcApiError(f"TFC/TFE API error {e.code} for {url}") from e
        except URLError as e:
            raise TfcApiError(f"TFC/TFE network error for {url}: {e.reason}") from e

    def get_workspace_id(self, organization: str, workspace: str) -> str:
        url = f"{self.base_url}/api/v2/organizations/{organization}/workspaces/{workspace}"
        payload = json.loads(self._request(url))
        try:
            return payload["data"]["id"]
        except (KeyError, TypeError) as e:
            raise TfcApiError("Unexpected workspace API response") from e

    def download_current_state(self, workspace_id: str) -> dict[str, Any]:
        meta_url = f"{self.base_url}/api/v2/workspaces/{workspace_id}/current-state-version"
        meta = json.loads(self._request(meta_url))
        try:
            download_url = meta["data"]["attributes"]["hosted-state-download-url"]
        except (KeyError, TypeError) as e:
            raise TfcApiError("No hosted-state-download-url on current state version") from e
        if not download_url:
            raise TfcApiError("Workspace current state version has empty download URL")
        return json.loads(self._request(download_url))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tfc_client.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tfc_client.py tests/test_tfc_client.py
git commit -m "feat: add TFC/TFE API client for state download"
```

---

### Task 3: Shared state source + argparse helpers

**Files:**
- Create: `state_source.py`
- Create: `tests/test_state_source.py`

**Interfaces:**
- Consumes: `TfcClient`
- Produces:
  - `load_state_data(file: str | None, *, hostname, token, organization, workspace, workspace_id, save_state: str | None) -> dict`
  - `add_state_source_arguments(parser: argparse.ArgumentParser) -> None`
  - `resolve_token(cli_token: str | None) -> str | None` reading `TFE_TOKEN`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_state_source.py
import json
import os
from pathlib import Path
from unittest.mock import patch
import pytest

from state_source import load_state_data, StateSourceError

FIX = Path(__file__).parent / "fixtures"


def test_load_from_file():
    data = load_state_data(str(FIX / "sample.tfstate"))
    assert len(data["resources"]) == 3


def test_remote_requires_token(monkeypatch):
    monkeypatch.delenv("TFE_TOKEN", raising=False)
    with pytest.raises(StateSourceError, match="token"):
        load_state_data(
            None,
            organization="o",
            workspace="w",
            hostname="app.terraform.io",
            token=None,
        )


def test_mutual_exclusion():
    with pytest.raises(StateSourceError, match="not both"):
        load_state_data(
            str(FIX / "sample.tfstate"),
            organization="o",
            workspace="w",
            token="t",
        )


def test_load_from_remote_with_workspace_id(monkeypatch):
    monkeypatch.setenv("TFE_TOKEN", "t")
    state = json.loads((FIX / "sample.tfstate").read_text())
    with patch("state_source.TfcClient") as cls:
        cls.return_value.download_current_state.return_value = state
        data = load_state_data(
            None,
            workspace_id="ws-1",
            hostname="app.terraform.io",
        )
        assert data is state
        cls.assert_called_once_with("app.terraform.io", "t")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_state_source.py -v`  
Expected: FAIL with import error

- [ ] **Step 3: Implement `state_source.py`**

```python
# state_source.py
from __future__ import annotations

import argparse
import json
import os
from typing import Any

from tfc_client import TfcApiError, TfcClient


class StateSourceError(ValueError):
    pass


def resolve_token(cli_token: str | None) -> str | None:
    return cli_token or os.environ.get("TFE_TOKEN") or None


def add_state_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-f", "--file", help="Local Terraform state file (.tfstate).")
    parser.add_argument("--organization", default=os.environ.get("TFC_ORGANIZATION"),
                        help="TFC/TFE organization name (or TFC_ORGANIZATION).")
    parser.add_argument("--workspace", default=os.environ.get("TFC_WORKSPACE"),
                        help="TFC/TFE workspace name (or TFC_WORKSPACE).")
    parser.add_argument("--workspace-id", default=None, help="TFC/TFE workspace ID (ws-...).")
    parser.add_argument("--hostname", default=os.environ.get("TFE_HOSTNAME", "app.terraform.io"),
                        help="TFC/TFE hostname (default app.terraform.io or TFE_HOSTNAME).")
    parser.add_argument("--token", default=None, help="API token (prefer TFE_TOKEN env var).")
    parser.add_argument("--save-state", default=None, help="Optional path to write downloaded state.")


def load_state_data(
    file: str | None,
    *,
    hostname: str = "app.terraform.io",
    token: str | None = None,
    organization: str | None = None,
    workspace: str | None = None,
    workspace_id: str | None = None,
    save_state: str | None = None,
) -> dict[str, Any]:
    remote_requested = any([organization, workspace, workspace_id])
    if file and remote_requested:
        raise StateSourceError("Provide a local --file or remote workspace identity, not both.")
    if not file and not remote_requested:
        raise StateSourceError("Provide --file or remote --organization/--workspace (or --workspace-id).")

    if file:
        try:
            with open(file, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError as e:
            raise StateSourceError(f"File '{file}' not found.") from e
        except json.JSONDecodeError as e:
            raise StateSourceError(f"File '{file}' is not valid JSON.") from e

    resolved = resolve_token(token)
    if not resolved:
        raise StateSourceError("Remote state requires a token via TFE_TOKEN or --token.")

    if not workspace_id:
        if not organization or not workspace:
            raise StateSourceError("Remote state requires --workspace-id or both --organization and --workspace.")
        try:
            workspace_id = TfcClient(hostname, resolved).get_workspace_id(organization, workspace)
        except TfcApiError as e:
            raise StateSourceError(str(e)) from e

    try:
        data = TfcClient(hostname, resolved).download_current_state(workspace_id)
    except TfcApiError as e:
        raise StateSourceError(str(e)) from e

    if save_state:
        with open(save_state, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_state_source.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add state_source.py tests/test_state_source.py
git commit -m "feat: add shared local/remote state source loader"
```

---

### Task 4: Wire remote source into `terraform_resource_extractor.py`

**Files:**
- Modify: `terraform_resource_extractor.py`
- Create: `tests/test_extractor_compat.py`

**Interfaces:**
- Consumes: `add_state_source_arguments`, `load_state_data`, `StateSourceError`
- Produces: CLI supports local and remote; `extract_resources` unchanged

- [ ] **Step 1: Write compatibility test using local fixture**

```python
# tests/test_extractor_compat.py
from pathlib import Path
from terraform_resource_extractor import extract_resources, load_state_file

FIX = Path(__file__).parent / "fixtures" / "sample.tfstate"


def test_extract_skips_null_and_data():
    # After refactor, prefer loading via state_source; keep extract_resources pure.
    import json
    state = json.loads(FIX.read_text())
    df, hashi = extract_resources(state)
    assert len(df) == 2  # two aws_instance instances
    assert set(df["Resource Type"]) == {"aws_instance"}
```

- [ ] **Step 2: Refactor main to use shared loader**

Replace `load_state_file(args.file)` usage in `main()`:

1. Remove required=`True` from local `-f` (moved to shared helper) — delete the old `-f` definition and call `add_state_source_arguments(parser)` instead.
2. Load with:

```python
from state_source import add_state_source_arguments, load_state_data, StateSourceError

# in main(), after parse_args:
try:
    state_data = load_state_data(
        args.file,
        hostname=args.hostname,
        token=args.token,
        organization=args.organization,
        workspace=args.workspace,
        workspace_id=args.workspace_id,
        save_state=args.save_state,
    )
except StateSourceError as e:
    print(f"❌ Error: {e}")
    exit(1)
```

3. Keep `load_state_file` as a thin wrapper around `load_state_data(file)` for backward compatibility **or** delete it if unused after refactor (prefer delete + update docstring examples).

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_extractor_compat.py tests/test_state_source.py -v`  
Expected: PASS

- [ ] **Step 4: Manual smoke (local)**

Run: `python terraform_resource_extractor.py -f tests/fixtures/sample.tfstate -n`  
Expected: `Total number of resource instances: 2`

- [ ] **Step 5: Commit**

```bash
git add terraform_resource_extractor.py tests/test_extractor_compat.py
git commit -m "feat: support TFC/TFE remote state in resource extractor"
```

---

### Task 5: Wire the other two scripts

**Files:**
- Modify: `extract_resource_type_stats.py`
- Modify: `temporary_intended_resources.py`
- Create: `tests/test_temporary_and_stats.py`

**Interfaces:**
- Consumes: same `state_source` helpers
- Produces: both scripts accept remote flags; `temporary_intended_resources.py` gains argparse (breaking soft: positional path still accepted as `-f` equivalent)

- [ ] **Step 1: Write tests**

```python
# tests/test_temporary_and_stats.py
import json
from pathlib import Path
from extract_resource_type_stats import extract_resource_instances
from temporary_intended_resources import extract_resources as extract_temp

FIX = Path(__file__).parent / "fixtures" / "sample.tfstate"


def test_stats_counts_unique_instances(tmp_path):
    df = extract_resource_instances(str(FIX), "aws_instance", detailed_output=False)
    assert len(df) == 2


def test_temporary_matches_demo_name(capsys):
    # Refactor extract_resources to accept state dict OR path; test dict path:
    state = json.loads(FIX.read_text())
    df = extract_temp(state_data=state)
    assert df is not None
    assert (df["Resource Name"] == "web-demo").any()
```

- [ ] **Step 2: Refactor `extract_resource_type_stats.py`**

- Change `extract_resource_instances` to accept either a path or preloaded `state_data: dict | None = None`.
- In `__main__`, use `add_state_source_arguments` + `load_state_data`, then pass `state_data=` into the function.

- [ ] **Step 3: Refactor `temporary_intended_resources.py`**

- Replace `sys.argv` parsing with `argparse`.
- Keep keyword filtering logic; split I/O from analysis:

```python
def extract_resources(state_file_path=None, display_attributes=False, state_data=None):
    if state_data is None:
        # load via state_source.load_state_data(state_file_path) or open path
        ...
```

- Add remote flags identically.

- [ ] **Step 4: Run full suite**

Run: `pytest -v`  
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add extract_resource_type_stats.py temporary_intended_resources.py tests/test_temporary_and_stats.py
git commit -m "feat: add TFC/TFE state source to stats and temporary-resource scripts"
```

---

### Task 6: Documentation and operator checklist

**Files:**
- Modify: `README.md`
- Modify: module docstrings in the three scripts

**Interfaces:**
- Produces: operators can follow README to run against TFC and TFE

- [ ] **Step 1: Add README section after installation**

Include:

1. Install: `pip install -r requirements.txt`
2. Local usage (existing examples)
3. **Remote state (HCP Terraform / TFE)**
   - Env: `TFE_TOKEN`, optional `TFE_HOSTNAME`, `TFC_ORGANIZATION`, `TFC_WORKSPACE`
   - Examples for TFC and TFE hostname
   - Required permissions (workspace read + state version download)
   - Note: uses raw state download URL
   - Security: prefer env token; state may contain secrets; `--save-state` caution
4. Dev: `pip install -r requirements-dev.txt && pytest`

- [ ] **Step 2: Update top-of-file usage examples in each script** to show one remote example.

- [ ] **Step 3: Commit**

```bash
git add README.md terraform_resource_extractor.py extract_resource_type_stats.py temporary_intended_resources.py
git commit -m "docs: document TFC/TFE remote state usage"
```

---

### Task 7: Manual verification checklist (no live CI dependency)

**Files:** none (operator / agent with credentials)

- [ ] **Step 1: Local regression**

```bash
python terraform_resource_extractor.py -f tests/fixtures/sample.tfstate -A
python extract_resource_type_stats.py -f tests/fixtures/sample.tfstate -r aws_instance
python temporary_intended_resources.py -f tests/fixtures/sample.tfstate
```

- [ ] **Step 2: Against a real workspace (optional)**

```bash
export TFE_TOKEN=...
python terraform_resource_extractor.py --organization ORG --workspace WS -A
python terraform_resource_extractor.py --hostname tfe.example.com --organization ORG --workspace WS -n
```

Confirm counts match a manually downloaded `.tfstate` analyzed with `-f`.

- [ ] **Step 3: Negative paths**

- Bad token → clear 401 error
- File + remote flags together → validation error
- Missing token → validation error

---

## Self-review

1. **Spec coverage:** P0/P1 from design map to Tasks 2–6; P2 multi-workspace explicitly deferred; raw state choice enforced in client tests.
2. **Placeholders:** None intentionally left; fixture IDs and function signatures are concrete.
3. **Type consistency:** `TfcClient.download_current_state` → `dict`; `load_state_data` → `dict`; scripts consume `state_data` dicts.

## Deferred (not in this plan)

- Org-wide RUM rollup / project filters
- `hosted-json-state-download-url` / `terraform show -json` adapter
- `TF_TOKEN_<hostname>` multi-host token map
- Official HashiCorp Python SDK
- Ephemeral workspace automation from `temporary_intended_resources.py` findings
