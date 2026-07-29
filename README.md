# terraform-rum-analysis-tools

Tools to analyze Terraform **Resources Under Management (RUM)** from local state files or **HCP Terraform / Terraform Enterprise** at **workspace**, **project**, or **organization** scope.

## Install

```bash
pip install -r requirements.txt
```

For development / tests:

```bash
pip install -r requirements-dev.txt
pytest -v
```

## Primary tool: `rum_report.py`

Produces totals and breakdowns (per provider, resource type, workspace, and project).

### Local workspace (offline)

```bash
python3 rum_report.py --scope workspace -f terraform.tfstate
python3 rum_report.py --scope workspace -f terraform.tfstate --format json
```

### Remote scopes (TFC / TFE)

Set a token (preferred via env):

```bash
export TFE_TOKEN=...                 # required for remote
export TFE_HOSTNAME=app.terraform.io # optional; use your TFE host for Enterprise
export TFC_ORGANIZATION=my-org       # optional defaults
```

**Workspace**

```bash
python3 rum_report.py --scope workspace \
  --organization my-org --workspace prod-net
```

**Project**

```bash
python3 rum_report.py --scope project \
  --organization my-org --project platform \
  --format json --output rum-platform
```

**Organization**

```bash
python3 rum_report.py --scope organization \
  --organization my-org \
  --concurrency 8
```

### Report contents

- **Totals** — managed instances, unique types/providers, workspaces succeeded/failed  
- **By provider** — instance counts and %  
- **By resource type** — instance counts and %  
- **By workspace** — instance counts  
- **By project** — when project metadata is available (org/project runs)  
- **Errors** — workspaces that failed (no state, auth, etc.)

Managed-resource rules match the historical extractor: `mode == managed`, excluding `null_resource` and `terraform_data`.

### Useful flags

| Flag | Purpose |
|------|---------|
| `--format table\|json\|csv` | Output style (default `table`) |
| `--output PATH` | Write JSON/CSV artifacts |
| `--concurrency N` | Parallel state downloads (default 5) |
| `--max-workspaces N` | Cap workspaces (sampling/debug) |
| `--strict` | Exit non-zero if any workspace fails |
| `-H` / `-Ho` | Hide or only show `tfe_` / `vault_` resources |
| `--hostname` | TFE hostname (default `app.terraform.io`) |
| `--workspace-id` / `--project-id` | Skip name lookup |

Partial failures on project/org runs are recorded and the report continues unless `--strict` is set. Exit code `1` if zero workspaces succeed.

### Permissions

The API token needs permission to:

- List workspaces in the organization (and read projects for project scope)
- Read each target workspace
- Download current state versions (`hosted-state-download-url`)

### Security notes

- Prefer `TFE_TOKEN` over `--token` (shell history / process list).
- State files contain secrets; downloads stay in memory unless you export inventory/report files.
- For TFE with custom CAs, configure trust via the usual Python/`SSL_CERT_FILE` mechanisms.

Design details: [`docs/superpowers/specs/2026-07-28-tfc-tfe-support-design.md`](docs/superpowers/specs/2026-07-28-tfc-tfe-support-design.md)

---

## Legacy single-state scripts

These remain for deep dives on one state file. Counting is shared with `rum_report` via `inventory.py`.

### `terraform_resource_extractor.py`

```bash
python3 terraform_resource_extractor.py -f terraform.tfstate
python3 terraform_resource_extractor.py -f terraform.tfstate -A
python3 terraform_resource_extractor.py -f terraform.tfstate -n
python3 terraform_resource_extractor.py -f terraform.tfstate -G
python3 terraform_resource_extractor.py -f terraform.tfstate -o output.csv
python3 terraform_resource_extractor.py -f terraform.tfstate -H    # hide tfe_/vault_
python3 terraform_resource_extractor.py -f terraform.tfstate -Ho   # only tfe_/vault_
```

### `extract_resource_type_stats.py`

```bash
python3 extract_resource_type_stats.py -f terraform.tfstate -r aws_instance
python3 extract_resource_type_stats.py -f terraform.tfstate -r aws_instance -D
```

### `temporary_intended_resources.py`

Finds resources whose attribute `name` contains demo/test/temp/tmp/example (candidates for ephemeral cleanup).

```bash
python3 temporary_intended_resources.py terraform.tfstate
python3 temporary_intended_resources.py terraform.tfstate -D
```

---

## jq parity check

Managed instance counts should match:

```bash
cat terraform.tfstate | jq '[ .resources[] | select(.mode == "managed") | select(.type == "terraform_data" or .type == "null_resource" | not) | .instances | flatten[] ] | length'
```

```bash
python3 rum_report.py --scope workspace -f terraform.tfstate --format json | jq '.totals.instances'
```
