# TFC/TFE Scoped RUM Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Analyze RUM at workspace, project, or organization scope against HCP Terraform / TFE, and produce reports with totals plus per-provider / per-type / per-workspace (and per-project) breakdowns.

**Architecture:** Discover workspaces for the chosen scope → download each workspace’s current raw state → normalize managed instances into a shared inventory table → aggregate reports and export. Local `-f` remains workspace-scope offline mode. Existing scripts keep deep single-state workflows via shared inventory helpers.

**Tech Stack:** Python 3.9+, stdlib `urllib`/`json`/`argparse`/`concurrent.futures`, `pandas`, `pytest`.

## Global Constraints

- Scopes: `workspace` | `project` | `organization` (exactly one per run).
- Prefer raw state (`hosted-state-download-url`), not JSON-state schema.
- Default hostname `app.terraform.io`; TFE via `--hostname` / `TFE_HOSTNAME`.
- Token via `TFE_TOKEN` (preferred) or `--token`.
- Default RUM filters: `mode == managed`, exclude `null_resource` and `terraform_data`.
- Org/project runs continue on per-workspace errors unless `--strict`.
- Do not print tokens or state bodies.
- Spec reference: `docs/superpowers/specs/2026-07-28-tfc-tfe-support-design.md`.

---

## File structure

| Path | Responsibility |
|------|----------------|
| `tfc_client.py` | Auth HTTP, workspace/project lookup, list+paginate, state download |
| `inventory.py` | State → normalized rows; provider normalization; shared filters |
| `discover.py` | Resolve scope → list of workspace refs |
| `report.py` | Totals and breakdown tables; JSON/CSV export |
| `rum_report.py` | Primary CLI |
| `terraform_resource_extractor.py` | Use `inventory.py` (compat); optional remote workspace source |
| `requirements.txt` / `requirements-dev.txt` | Deps |
| `tests/fixtures/...` | Sample states + JSON:API list/show/state-version payloads |
| `tests/test_*.py` | Unit tests |
| `README.md` | Operator docs for all scopes |

---

### Task 1: Scaffolding and fixtures

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`
- Create: `tests/fixtures/sample_aws.tfstate`
- Create: `tests/fixtures/sample_azurerm.tfstate`
- Create: `tests/fixtures/workspace_show.json`
- Create: `tests/fixtures/project_show.json`
- Create: `tests/fixtures/workspaces_page1.json`
- Create: `tests/fixtures/workspaces_page2.json`
- Create: `tests/fixtures/current_state_version.json`

**Interfaces:**
- Produces: installable deps + fixtures for later tasks

- [ ] **Step 1: Add dependency files**

```text
# requirements.txt
pandas>=2.0

# requirements-dev.txt
-r requirements.txt
pytest>=8.0
```

- [ ] **Step 2: Add two small state fixtures** (different providers) used later for rollup totals

`tests/fixtures/sample_aws.tfstate` — 2× `aws_instance` managed instances (+ a `null_resource` to prove exclusion).

`tests/fixtures/sample_azurerm.tfstate` — 3× `azurerm_resource_group` managed instances.

(Use the same shape as in the prior plan’s `sample.tfstate`, varying provider/type/counts.)

- [ ] **Step 3: Add API fixtures**

- `workspace_show.json` → `data.id = ws-A`
- `project_show.json` → `data.id = prj-PLATFORM`
- `workspaces_page1.json` / `workspaces_page2.json` — two workspaces with project relationships; page1 has `next-page: 2`, page2 has `next-page: null`
- `current_state_version.json` — includes `hosted-state-download-url`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt requirements-dev.txt tests/fixtures
git commit -m "chore: add deps and fixtures for scoped RUM reporting"
```

---

### Task 2: Inventory extraction + provider normalization

**Files:**
- Create: `inventory.py`
- Create: `tests/test_inventory.py`

**Interfaces:**
- Produces:
  - `normalize_provider(provider_raw: str) -> str`
  - `extract_inventory(state_data: dict, *, organization=None, project_id=None, project_name=None, workspace_id=None, workspace_name=None, exclude_types=None, only_hashi=False, hide_hashi=False) -> pd.DataFrame`
  - Columns: `organization, project_id, project_name, workspace_id, workspace_name, module, resource_type, resource_name, provider, provider_raw, instance_count`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_inventory.py
import json
from pathlib import Path
from inventory import extract_inventory, normalize_provider

FIX = Path(__file__).parent / "fixtures"


def test_normalize_provider():
    assert normalize_provider('provider["registry.terraform.io/hashicorp/aws"]') == "hashicorp/aws"
    assert normalize_provider('provider["registry.terraform.io/hashicorp/azurerm"].prod') == "hashicorp/azurerm"


def test_extract_counts_and_excludes_null():
    state = json.loads((FIX / "sample_aws.tfstate").read_text())
    df = extract_inventory(state, workspace_name="ws1", organization="org")
    assert df["instance_count"].sum() == 2
    assert set(df["provider"]) == {"hashicorp/aws"}
    assert "null_resource" not in set(df["resource_type"])
```

- [ ] **Step 2: Run to verify fail**

Run: `pip install -r requirements-dev.txt && pytest tests/test_inventory.py -v`  
Expected: import error

- [ ] **Step 3: Implement `inventory.py`**

```python
# inventory.py (core logic sketch)
import re
import pandas as pd

_PROVIDER_RE = re.compile(r'provider\["([^"]+)"\]')
DEFAULT_EXCLUDE = {"null_resource", "terraform_data"}

def normalize_provider(provider_raw: str) -> str:
    m = _PROVIDER_RE.search(provider_raw or "")
    if not m:
        return provider_raw or "unknown"
    addr = m.group(1)  # registry.terraform.io/hashicorp/aws
    parts = addr.split("/")
    if len(parts) >= 2:
        return "/".join(parts[-2:])  # hashicorp/aws
    return addr

def extract_inventory(state_data, **meta):
    exclude = meta.pop("exclude_types", None) or DEFAULT_EXCLUDE
    only_hashi = meta.pop("only_hashi", False)
    hide_hashi = meta.pop("hide_hashi", False)
    rows = []
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
        for _ in resource.get("instances", []):
            rows.append({
                "organization": meta.get("organization"),
                "project_id": meta.get("project_id"),
                "project_name": meta.get("project_name"),
                "workspace_id": meta.get("workspace_id"),
                "workspace_name": meta.get("workspace_name"),
                "module": resource.get("module", "root"),
                "resource_type": rtype,
                "resource_name": resource.get("name", "unknown"),
                "provider": normalize_provider(provider_raw),
                "provider_raw": provider_raw,
                "instance_count": 1,
            })
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Run tests — expect PASS; commit**

```bash
pytest tests/test_inventory.py -v
git add inventory.py tests/test_inventory.py
git commit -m "feat: add shared RUM inventory extractor"
```

---

### Task 3: TFC client (show, list+paginate, download state)

**Files:**
- Create: `tfc_client.py`
- Create: `tests/test_tfc_client.py`

**Interfaces:**
- Produces:
  - `class TfcClient`
  - `get_workspace(organization, workspace) -> dict` (id + attrs)
  - `get_project_id(organization, project_name) -> str`
  - `list_workspaces(organization, *, project_id=None, page_size=100) -> list[dict]`
  - `download_current_state(workspace_id) -> dict`
  - `class TfcApiError`

Workspace list item shape returned to callers:

```python
{
  "id": "ws-A",
  "name": "net",
  "project_id": "prj-PLATFORM",
  "project_name": "platform",  # if present in included/relationships
}
```

- [ ] **Step 1: Write failing tests** for workspace id lookup, pagination across two fixture pages, project filter query param encoding, and raw state download URL selection (not json-state URL).

- [ ] **Step 2: Implement client with `urllib`**, percent-encoding `filter[project][id]` and `page[number]` / `page[size]`.

- [ ] **Step 3: pytest PASS; commit**

```bash
git commit -m "feat: add TFC/TFE client with paginated workspace listing"
```

---

### Task 4: Scope discovery

**Files:**
- Create: `discover.py`
- Create: `tests/test_discover.py`

**Interfaces:**
- Consumes: `TfcClient`
- Produces:
  - `discover_workspaces(client, scope, *, organization, workspace=None, workspace_id=None, project=None, project_id=None) -> list[WorkspaceRef]`

Rules:

- `scope=workspace` → one ref (by id or org+name)
- `scope=project` → resolve project id if needed → `list_workspaces(..., project_id=)`
- `scope=organization` → `list_workspaces(organization)`

- [ ] **Step 1: Failing tests** for each scope using mocked client return values.

- [ ] **Step 2: Implement `discover.py`**.

- [ ] **Step 3: PASS; commit**

```bash
git commit -m "feat: discover workspaces for org/project/workspace scopes"
```

---

### Task 5: Report aggregations + export

**Files:**
- Create: `report.py`
- Create: `tests/test_report.py`

**Interfaces:**
- Produces:
  - `build_report(inventory_df, *, errors: list[dict], scope: str, organization: str, project: str | None) -> dict`
  - Report dict keys:
    - `meta` (scope, org, project, workspace_counts)
    - `totals` (`instances`, `unique_resource_types`, `unique_providers`, `workspaces_succeeded`, `workspaces_failed`)
    - `by_provider` (list of `{provider, instances, pct}`)
    - `by_resource_type`
    - `by_workspace`
    - `by_project` (empty unless org scope / project cols present)
    - `errors`
  - `render_table(report) -> str`
  - `write_json(report, path)` / `write_inventory_csv(df, path)`

- [ ] **Step 1: Failing test** concatenating aws(2) + azurerm(3) inventories → totals 5; providers hashicorp/aws=2, hashicorp/azurerm=3; two workspaces.

```python
def test_rollup_totals_and_providers():
    aws = extract_inventory(json.loads((FIX/"sample_aws.tfstate").read_text()),
                            workspace_name="a", organization="o")
    azu = extract_inventory(json.loads((FIX/"sample_azurerm.tfstate").read_text()),
                            workspace_name="b", organization="o")
    import pandas as pd
    from report import build_report
    rep = build_report(pd.concat([aws, azu], ignore_index=True), errors=[], scope="organization", organization="o", project=None)
    assert rep["totals"]["instances"] == 5
    providers = {r["provider"]: r["instances"] for r in rep["by_provider"]}
    assert providers["hashicorp/aws"] == 2
    assert providers["hashicorp/azurerm"] == 3
```

- [ ] **Step 2: Implement aggregations with pandas `groupby`**.

- [ ] **Step 3: PASS; commit**

```bash
git commit -m "feat: add RUM totals and per-provider report builder"
```

---

### Task 6: Primary CLI `rum_report.py` (P0 workspace + local)

**Files:**
- Create: `rum_report.py`
- Create: `tests/test_rum_report_cli.py`

**Interfaces:**
- CLI flags: `--scope`, `-f/--file`, `--organization`, `--workspace`, `--workspace-id`, `--project`, `--project-id`, `--hostname`, `--token`, `--concurrency`, `--strict`, `--format table|json|csv`, `--output`, `--hide-tfe-vault`, `--only-tfe-vault`, `--max-workspaces`

P0 behavior to ship first:

- `scope=workspace` with `-f` or remote workspace identity
- prints totals + by_provider + by_resource_type
- json output optional

- [ ] **Step 1: Implement CLI wiring** calling discover (or direct local load) → inventory → report → render.

Local path shortcut:

```python
if args.file:
    state = json.load(open(args.file))
    df = extract_inventory(state, workspace_name=args.file, organization=args.organization)
    errors = []
else:
    # remote path using client + discover + per-ws download
    ...
```

- [ ] **Step 2: CLI test** via `subprocess` or calling `main` with `argv` on local fixture.

Run: `python rum_report.py --scope workspace -f tests/fixtures/sample_aws.tfstate --format json`  
Expected: JSON with `"totals": {"instances": 2, ...}`

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: add rum_report CLI for workspace-scope analysis"
```

---

### Task 7: Project + organization scope with concurrency (P1)

**Files:**
- Modify: `rum_report.py`, `tfc_client.py` (if needed)
- Create: `tests/test_scoped_run.py`

**Interfaces:**
- For each discovered workspace, fetch state in a `ThreadPoolExecutor(max_workers=concurrency)`
- Collect inventories + error dicts `{workspace_id, workspace_name, error}`
- Honor `--max-workspaces`
- `--strict` → exit 1 if any workspace error
- Default → exit 1 only when zero successes

- [ ] **Step 1: Test** mocked discover returning 2 workspaces; mocked downloads returning the two fixtures; assert org report totals == 5 and `by_workspace` has 2 rows.

- [ ] **Step 2: Implement fan-out fetch + concat**.

- [ ] **Step 3: Include `by_project` aggregation when `project_id` present.

- [ ] **Step 4: PASS; commit**

```bash
git commit -m "feat: support project and organization RUM rollups"
```

---

### Task 8: Wire shared inventory into existing extractor (compat)

**Files:**
- Modify: `terraform_resource_extractor.py`
- Create: `tests/test_extractor_compat.py`

**Interfaces:**
- `extract_resources` delegates counting to `inventory.extract_inventory` (map columns back to existing display names) **or** keep current logic but add a comment + dual-run test ensuring instance totals match `inventory` on fixtures.

Prefer **shared implementation** to avoid drift:

```python
df = extract_inventory(state_data, hide_hashi=exclude_tfe_vault, only_hashi=only_tfe_vault)
# rename columns for existing printers: provider→Provider, etc.
```

- [ ] **Step 1: Compat test** — old displayed total instances == inventory sum on fixtures.

- [ ] **Step 2: Refactor; commit**

```bash
git commit -m "refactor: share inventory counting with resource extractor"
```

---

### Task 9: Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document**
  - Install
  - Scopes: workspace / project / organization with examples
  - Report sections (totals, per provider, per type, per workspace, per project)
  - Auth, TFE hostname, permissions
  - Partial failure / `--strict` / `--concurrency`
  - Relationship of `rum_report.py` vs legacy scripts
  - Security notes (state secrets)

- [ ] **Step 2: Commit**

```bash
git commit -m "docs: document scoped TFC/TFE RUM reporting"
```

---

### Task 10: Manual verification checklist

- [ ] Local workspace fixture report matches expected counts
- [ ] Remote single workspace matches manually downloaded `-f` analysis
- [ ] Project scope only includes that project’s workspaces
- [ ] Org scope paginates beyond 100 workspaces
- [ ] Workspace without state appears under errors, org report still succeeds
- [ ] Per-provider totals sum to overall instances

---

## Self-review

1. **Spec coverage:** workspace/project/org scopes, discovery, raw state fetch, totals + per-provider/type/workspace/project reports, partial failures, concurrency, exports — all tasked.
2. **Placeholders:** none intentional; fixture names and function signatures are concrete.
3. **Consistency:** inventory columns feed report groupbys; client list shape matches discover `WorkspaceRef`.

## Deferred

- Snapshot diff (“RUM last week vs today”)
- Tag-based workspace filters
- `hosted-json-state-download-url` adapter
- Billing/list-price enrichment
- Temporary-resource scan inside org rollups (can call existing helper later)
