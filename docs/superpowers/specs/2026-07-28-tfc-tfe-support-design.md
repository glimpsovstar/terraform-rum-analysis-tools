# TFC/TFE Support Design

**Status:** Proposed  
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
- CSV and aggregate reporting suitable for audits.

### Gaps relative to TFC/TFE

1. **No remote state fetch.** Users with HCP Terraform (TFC) or Terraform Enterprise (TFE) must manually download state first (UI or API).
2. **No auth / hostname model.** TFE needs a custom hostname; TFC defaults to `app.terraform.io`.
3. **No workspace addressing.** Scripts do not accept org + workspace (or workspace ID).
4. **Duplicated state loading.** Each script opens/parses JSON independently; adding a second source without a shared loader would triple the work and drift.
5. **No tests or packaging.** No `requirements.txt`, shared module layout, or tests — remote I/O will need fixtures/mocks.
6. **Docs only mention local files.** README and script help text do not describe TFC/TFE workflows.
7. **Ephemeral-workspaces note is advisory only.** `temporary_intended_resources.py` mentions TFC ephemeral workspaces as a follow-on idea; that is product guidance, not integration.

### Non-goals for this design

- Uploading or mutating remote state
- Triggering plans/applies
- Organization-wide billing/RUM dashboards (multi-workspace aggregation can be a later phase)
- Parsing `terraform show -json` / `hosted-json-state-download-url` as the primary format (different schema than raw `.tfstate`)
- Replacing the TFE provider / official Terraform CLI

## 2. Problem statement

Operators who store state in TFC/TFE should be able to run the same RUM analysis against a workspace **without** a manual state download step, using a token and workspace identity.

## 3. Approaches considered

### A. Thin download helper (CLI wrapper)

Add a script that downloads current state to a temp/local file, then invoke existing tools unchanged.

- **Pros:** Minimal code change; easy to reason about.
- **Cons:** Two-step UX; each analysis tool still unaware of TFC; temp file hygiene and secrets logging risk.

### B. Shared state source + CLI flags on each tool (recommended)

Introduce a small shared module that returns parsed state from either:

- local file path, or
- TFC/TFE API (resolve workspace → current state version → download raw state)

Wire the same flags/env vars into all three CLIs (or a thin common arg group).

- **Pros:** One fetch path; analysis logic stays pure; matches “single workspace” product framing; TFE hostname is first-class.
- **Cons:** Touches all three entrypoints; needs requests/urllib and tests.

### C. Full TFC client / multi-workspace reporter

Build org/project listing, pagination, concurrency, aggregated RUM across many workspaces.

- **Pros:** Powerful for platform teams.
- **Cons:** Large scope; exceeds current “single workspace” tools; harder auth/permission stories.

**Recommendation:** **Approach B**, with Approach A’s download-to-file available as an optional `--save-state` / standalone helper for debugging. Defer Approach C.

## 4. Design

### 4.1 Architecture

```
┌────────────────────────────┐
│ CLI (extractor / stats /   │
│ temporary)                 │
└─────────────┬──────────────┘
              │ resolve StateSource
              ▼
┌────────────────────────────┐
│ state_source.py            │
│  - from_file(path)         │
│  - from_tfc(org, ws, …)    │
└─────────────┬──────────────┘
              │ HTTP (optional)
              ▼
┌────────────────────────────┐
│ TFC/TFE API                │
│ 1) GET workspace by name   │
│ 2) GET current-state-ver   │
│ 3) GET hosted-state URL    │
└────────────────────────────┘
              │
              ▼
        raw state JSON
              │
              ▼
   existing extract/aggregate logic
```

Analysis functions should accept **already-loaded** `dict` state (as `extract_resources(state_data, …)` already does in the main extractor). File/API concerns stay in the loader.

### 4.2 Remote fetch sequence

Compatible with HCP Terraform and TFE (same API shape; hostname differs):

1. **Auth:** `Authorization: Bearer <token>`, `Content-Type: application/vnd.api+json`.
2. **Resolve workspace** (if ID not provided):  
   `GET /api/v2/organizations/{org}/workspaces/{name}`
3. **Current state version:**  
   `GET /api/v2/workspaces/{workspace_id}/current-state-version`
4. **Download raw state:** follow `data.attributes.hosted-state-download-url`  
   (requires auth on newer TFE versions; always send the token).

Use **raw** state (`hosted-state-download-url`), not `hosted-json-state-download-url`, so existing parsers keep working without a second schema.

### 4.3 Configuration surface

| Input | Local | Remote |
|-------|-------|--------|
| State | `-f/--file` | omit file; pass org + workspace |
| Org | n/a | `--organization` / `TFC_ORGANIZATION` |
| Workspace | n/a | `--workspace` / `TFC_WORKSPACE` |
| Workspace ID | n/a | `--workspace-id` (skips name lookup) |
| Hostname | n/a | `--hostname` default `app.terraform.io`; env `TFE_HOSTNAME` |
| Token | n/a | `--token` or env `TFE_TOKEN` (also accept `TF_TOKEN_<hostname_with_underscores>` later if useful) |

Validation rules:

- Exactly one of: local file **or** remote workspace identity.
- Remote requires token + (workspace ID **or** org+workspace name).
- `--hide-tfe-vault` / analysis flags remain orthogonal to source.

### 4.4 Dependencies

- Prefer **stdlib `urllib`** for the MVP to avoid forcing a new runtime dep, **or** add `requests` + a `requirements.txt` if readability wins.
- Keep `pandas` as today.
- Add `requirements.txt` / `requirements-dev.txt` and a minimal `pytest` suite with HTTP mocked via `unittest.mock` or `responses`.

### 4.5 Error handling

Surface clear, actionable errors (non-zero exit):

| Condition | Message intent |
|-----------|----------------|
| 401/403 | Token missing/invalid or insufficient permissions (`state-versions:read`, workspace read) |
| 404 workspace | Org/workspace name wrong or no access |
| 404 current state | Workspace has never successfully written state |
| Download failure / empty body | Archivist URL expired or network/TLS issue (TFE custom CA note in docs) |
| Invalid JSON | Corrupt download |

Do not print tokens. Redact query strings from URLs in debug logs.

### 4.6 Security & ops notes

- Prefer env-var tokens over CLI flags (flags leak into shell history / process lists); if `--token` is allowed, document the risk.
- Do not write downloaded state to disk by default; optional `--save-state path` for support cases.
- Document TFE TLS / custom CA (`SSL_CERT_FILE` / corporate proxies).
- State contains secrets; treat temp files like production secrets.

### 4.7 CLI UX examples (target)

```bash
# Local (unchanged)
python terraform_resource_extractor.py -f terraform.tfstate -A

# HCP Terraform
export TFE_TOKEN=...
python terraform_resource_extractor.py \
  --organization my-org --workspace prod-net -A

# Terraform Enterprise
export TFE_TOKEN=...
python terraform_resource_extractor.py \
  --hostname tfe.example.com \
  --organization my-org --workspace prod-net -A
```

Same source flags on `extract_resource_type_stats.py` and `temporary_intended_resources.py`.

### 4.8 Testing strategy

- Unit tests for URL building, workspace resolution parsing, and attribute extraction from fixture JSON:API responses.
- Unit tests that existing extractors behave identically when fed fixture state loaded via the shared loader.
- No live API tests in CI; optional manual checklist against a sandbox workspace.

### 4.9 Documentation updates

- README: new “Remote state (TFC/TFE)” section with permissions, env vars, TFE hostname.
- Script docstrings/help text.
- Note raw-state requirement and Terraform version assumptions (standard remote state JSON).

### 4.10 Phased delivery

| Phase | Deliverable |
|-------|-------------|
| **P0** | Shared loader + remote flags on `terraform_resource_extractor.py` + README + tests |
| **P1** | Same source flags on the other two scripts; optional `--save-state` |
| **P2** (later) | Org/project multi-workspace rollup; sanitized-state option; official JSON state schema adapter |

## 5. Permissions required (operator checklist)

Token (user or team) needs at least:

- Read access to the target workspace
- Permission to read state versions / download state

Exact RBAC labels vary by TFC/TFE version; docs should point operators to “read state” capability for the workspace.

## 6. Open assumptions (locked for planning)

1. Primary users analyze **one workspace at a time** (matches README).
2. Raw `.tfstate` remains the canonical in-memory format.
3. Default hostname is HCP Terraform (`app.terraform.io`); TFE is hostname override only.
4. No SDK dependency (`terrasnek`, etc.) for MVP — thin HTTP client is enough.
5. Python 3.9+ is an acceptable floor unless the repo later states otherwise.
