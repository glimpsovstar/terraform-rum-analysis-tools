# TFC/TFE Support Design

**Status:** Proposed (revised)  
**Date:** 2026-07-28  
**Repo:** `terraform-rum-analysis-tools`

## 1. Current state review

This repo analyzes Terraform **Resources Under Management (RUM)** for a single workspace. All three scripts assume a **local** `.tfstate` JSON file:

| Script | Role | Input today |
|--------|------|-------------|
| `terraform_resource_extractor.py` | Inventory, counts, aggregates, CSV export, HashiCorp resource filters | `-f path/to.tfstate` |
| `extract_resource_type_stats.py` | Per-type instance stats / uniqueness | `-f` + `-r <type>` |
| `temporary_intended_resources.py` | Find demo/test/temp-named resources | positional path |

### What already works for RUM analysis

- Parses modern Terraform state (`resources[]` with `mode`, `type`, `name`, `provider`, `instances[]`).
- Counts instances correctly for `count` / `for_each` (one row per instance).
- Filters `terraform_data` / `null_resource` out of managed-resource counts (aligned with the documented `jq` check).
- Optional HashiCorp resource focus (`tfe_*`, `vault_*`) via `-H` / `-Ho`.
- CSV and aggregate reporting suitable for audits at **one** workspace.

### Gaps relative to TFC/TFE (platform-scale RUM)

1. **No remote state fetch** from HCP Terraform / TFE.
2. **No scope model** — cannot analyze an organization, a project, or choose a single workspace via API identity.
3. **No rollup reports** — totals, per-provider, per-resource-type, and per-workspace breakdowns across many states.
4. **No workspace discovery** — listing/pagination/`filter[project][id]` not implemented.
5. **Duplicated state loading** across scripts; no shared inventory pipeline.
6. **No tests/packaging** for remote I/O, concurrency, or partial-failure reporting.
7. Docs describe local files only.

### Non-goals

- Uploading or mutating remote state
- Triggering plans/applies / cost estimation APIs
- Replacing HCP Terraform’s own billing UI (this tool produces **inventory RUM**, not invoice reconciliation)
- Using `hosted-json-state-download-url` as the primary schema (raw `.tfstate` remains canonical)
- Auto-remediation of temporary resources (advisory scripts can remain separate)

## 2. Problem statement

Platform operators need RUM analysis at the same granularity they manage TFC/TFE:

| Scope | Question answered |
|-------|-------------------|
| **Workspace** | What is managed in this one workspace? |
| **Project** | What is managed across workspaces in this project? |
| **Organization** | What is managed across the org (optionally filtered)? |

Reports must summarize **totals** and breakdowns (**per provider**, **per resource type**, **per workspace**, and for org scope **per project**), not only a flat resource dump.

**Yes — this makes sense.** TFC/TFE already structure ownership as org → project → workspace; RUM reporting should follow that hierarchy. Single-workspace local-file analysis remains useful, but remote support should treat workspace as one scope option, not the only product.

## 3. Approaches considered

### A. Thin per-workspace download helper only

Download one state, run existing scripts.

- Good for debugging; insufficient for org/project RUM.

### B. Shared loader + remote flags on existing scripts only

Single-workspace remote fetch wired into current CLIs.

- Necessary foundation; not sufficient alone for the requested scopes/reports.

### C. Scoped inventory runner + report engine (recommended)

1. **Discover** target workspaces for a scope (org / project / workspace).
2. **Fetch** each workspace’s current raw state (with concurrency + partial failure tolerance).
3. **Normalize** rows (org, project, workspace, provider, type, name, instance count).
4. **Report** totals and breakdowns; export CSV/JSON.

Keep existing single-file scripts as thin local/workspace tools; add a primary `rum_report` (or extend the extractor) for scoped rollups.

**Recommendation:** **C built on B’s loader.** Implement discovery + reporting as first-class; do not defer org/project to a vague later phase.

## 4. Design

### 4.1 Scope model

Exactly one analysis scope per run:

| Scope | Required identity | Discovery |
|-------|-------------------|-----------|
| `workspace` | `--organization` + `--workspace` **or** `--workspace-id` (+ optional local `-f` for offline) | None (single target) |
| `project` | `--organization` + `--project` (name) or `--project-id` | List workspaces with `filter[project][id]` (paginated) |
| `organization` | `--organization` | List all org workspaces (paginated); optional exclude tags / name filters later |

Local `-f` remains a special case of workspace scope without API discovery.

### 4.2 Architecture

```
CLI: rum_report.py (primary)
  scope = organization | project | workspace
        │
        ▼
┌─────────────────────┐
│ discover.py         │  list workspaces (paginate, project filter)
└──────────┬──────────┘
           │ [workspace refs]
           ▼
┌─────────────────────┐
│ tfc_client.py       │  current-state-version → hosted-state-download-url
└──────────┬──────────┘
           │ raw state JSON (per workspace)
           ▼
┌─────────────────────┐
│ inventory.py        │  extract managed instances → normalized rows
└──────────┬──────────┘
           │ DataFrame / row stream
           ▼
┌─────────────────────┐
│ report.py           │  totals + breakdowns + exports
└─────────────────────┘
```

Existing scripts can call `inventory.extract_from_state(state_data)` so local analysis and remote rollups share one counting definition.

### 4.3 Workspace discovery (API)

- List: `GET /api/v2/organizations/{org}/workspaces?page[number]=&page[size]=100`
- Project filter: `filter[project][id]=prj-...`
- Resolve project name → id via Projects API when `--project` name is given
- Include workspace attributes needed for reports: `id`, `name`, and project relationship (`project.id` / name when available)
- Paginate until `meta.pagination.next-page` is null

### 4.4 State fetch

Per workspace (same as prior design):

1. `GET /api/v2/workspaces/{id}/current-state-version`
2. Download `hosted-state-download-url` (raw state; send Bearer token)
3. Parse JSON → inventory extractor

**Partial failure policy:** a workspace with 404 (no state), 401/403, or corrupt JSON is recorded in an errors table and **does not fail the whole org/project run** (exit non-zero only if zero workspaces succeeded, or if `--strict` is set).

**Concurrency:** bounded worker pool (default ~5–10) to avoid API throttling; configurable `--concurrency`.

### 4.5 Normalized inventory row

Every managed instance becomes one row:

| Field | Source |
|-------|--------|
| `organization` | CLI / API |
| `project_id` / `project_name` | workspace relationship (best-effort) |
| `workspace_id` / `workspace_name` | discovery |
| `module` | state `module` or `root` |
| `resource_type` | state `type` |
| `resource_name` | state `name` |
| `provider` | normalized from state `provider` address |
| `provider_raw` | original provider string |
| `instance_count` | `1` per instance (preserves count/for_each) |

**Provider normalization examples:**

- `provider["registry.terraform.io/hashicorp/aws"]` → `hashicorp/aws` (report key), short label `aws` optional
- `provider["registry.terraform.io/hashicorp/azurerm"].alias` → `hashicorp/azurerm`

Exclude `mode != managed`, and exclude `terraform_data` / `null_resource` by default (same as today). Keep `-H` / `-Ho` style filters as report options.

### 4.6 Reports (required outputs)

For every successful run, print (and optionally export) at least:

1. **Run header** — scope, org, project (if any), hostname, workspace targeted/succeeded/failed counts
2. **Totals**
   - total managed resource instances
   - unique resource types
   - unique providers
   - workspaces with state / without state / errors
3. **Per provider** — instance counts (and % of total)
4. **Per resource type** — instance counts (top N + full export)
5. **Per workspace** — instance counts, provider mix summary
6. **Per project** — when scope is `organization` (and project metadata available)

Exports:

- `--format table|json|csv` (table default for human use)
- `--output path` for machine-readable full inventory and/or summary files  
  Suggested: `summary.json` + `inventory.csv` when a directory/`--output` prefix is given

Existing single-workspace detailed dump (`-G`, full resource table) remains available at workspace scope.

### 4.7 CLI sketch

```bash
# Workspace
python rum_report.py --scope workspace \
  --organization my-org --workspace prod-net

# Project
python rum_report.py --scope project \
  --organization my-org --project platform \
  --format json --output rum-platform.json

# Organization
python rum_report.py --scope organization \
  --organization my-org \
  --concurrency 8

# Local file (workspace-equivalent, offline)
python rum_report.py --scope workspace -f terraform.tfstate
```

Auth/hostname unchanged: `TFE_TOKEN`, `TFE_HOSTNAME` (default `app.terraform.io`), optional `--token`.

### 4.8 Relationship to existing scripts

| Capability | Where it lives |
|------------|----------------|
| Scoped discovery + rollup reports | **New** `rum_report.py` (+ modules above) |
| Deep single-state exploration | Keep `terraform_resource_extractor.py` (local + remote workspace source) |
| Type-specific deep dive | Keep `extract_resource_type_stats.py` |
| Temp/demo naming scan | Keep `temporary_intended_resources.py`; later optional `--include-temporary-scan` on rollup |

Do not force org-level logic into the old CLIs; share libraries instead.

### 4.9 Security & ops

- Prefer env tokens; never log secrets or full state bodies
- State downloads are sensitive — default in-memory only
- Document org tokens vs user tokens and required read permissions (workspaces list, state versions read)
- TFE custom CA / proxy notes in README
- Large orgs: warn that full org RUM may take a long time; support `--max-workspaces` for sampling/debug

### 4.10 Testing strategy

- Unit: provider normalization, inventory filters, pagination loop, report aggregations
- Fixture-based: multi-workspace fake discovery + two sample states → known totals/per-provider
- No live API in CI; optional manual checklist for sandbox org/project/workspace

### 4.11 Phased delivery

| Phase | Deliverable |
|-------|-------------|
| **P0** | Shared client + inventory extractor + workspace-scope remote/local report (totals, per provider, per type) |
| **P1** | Project + organization discovery (pagination, project filter), per-workspace/per-project rollups, partial-failure table, concurrency |
| **P2** | JSON/CSV export polish, tag filters, temporary-resource rollup option, README operator runbooks |
| **P3** (optional) | Progress UI, caching of state versions, comparison between two report snapshots |

## 5. Permissions (operator checklist)

Token needs, at minimum:

- List workspaces in the org (and read project metadata for project scope)
- Read each target workspace
- Read/download state versions for each target workspace

Missing permissions on a subset of workspaces → row in errors report, continue.

## 6. Locked assumptions

1. Hierarchy is **organization → project → workspace**; reports follow that.
2. RUM count = managed instances excluding `null_resource` / `terraform_data` by default.
3. Raw state download is the source of truth for counts.
4. Org/project runs tolerate partial failures unless `--strict`.
5. Primary UX is a dedicated report CLI; legacy scripts remain for focused local analysis.
6. Python 3.9+; stdlib HTTP client acceptable for MVP (or `requests` if preferred during implementation).
