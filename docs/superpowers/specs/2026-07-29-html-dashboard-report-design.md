# HTML Dashboard RUM Report — Design

**Status:** Implemented  
**Date:** 2026-07-29  
**Depends on:** `docs/superpowers/specs/2026-07-28-tfc-tfe-support-design.md`

## Implementation map

| Spec area | Code |
|-----------|------|
| Findings rules | `findings.py` |
| HTML dashboard renderer | `html_report.py` |
| CLI `--format html` | `rum_report.py` |
| Tests | `tests/test_findings.py`, `tests/test_html_report.py`, CLI coverage |

## 1. Goals

| Driver | Goal |
|--------|------|
| **Product** | Operators can open a single HTML file that reads as a RUM **dashboard**, then drill into **findings** and inventory detail without a web server. |
| **Spec** | Self-contained HTML; reuses existing `build_report` + inventory; no secrets in page beyond inventory fields already exported. |
| **Task** | Deliver via plan tasks with tests and README updates. |

### Success criteria

1. `rum_report.py --format html --output report.html` writes a valid HTML document.
2. Dashboard shows scope meta + KPI totals + provider/type/workspace breakdowns.
3. **Findings** section lists actionable items; each expands to supporting detail rows.
4. Detail inventory is searchable/filterable in-browser.
5. Works offline (no CDN/network required at view time).
6. Unit tests assert structure, escaping, findings, and CLI wiring.

## 2. Approaches considered

### A. External template engine (Jinja2) + Chart.js CDN

- Rich templates; **fails offline**; new dependency.

### B. Self-contained HTML generator (stdlib) + CSS bars + vanilla JS (recommended)

- One `.html` file embedding CSS, JS, and JSON payload.
- No new runtime deps; offline-safe; testable string/DOM structure checks.
- Charts as CSS bar meters (accessible, no canvas lib).

### C. Multi-page export (index + finding pages)

- Better for huge orgs; heavier UX/file management for v1.

**Recommendation:** **B**.

## 3. Information architecture

```
┌─────────────────────────────────────────────┐
│ Header: RUM Analysis · scope / org / time   │
├──────────┬──────────┬──────────┬────────────┤
│ Instances│ Providers│ Types    │ WS fail    │  ← KPI band
├─────────────────────────────────────────────┤
│ Breakdowns: providers · types · workspaces  │  ← bar lists
├─────────────────────────────────────────────┤
│ Findings (N)  [severityable finding rows]    │  ← drill-down
├─────────────────────────────────────────────┤
│ Inventory detail  [search] [table]          │
└─────────────────────────────────────────────┘
```

One composition: overview → findings → detail (not a multi-widget admin soup). Brand signal: **RUM Analysis** as the header product name.

### Visual direction

- Light “ops slate” surface: cool gray-blue gradient background, deep slate text, **teal** accent (not purple/indigo, not cream/terracotta).
- Typography: distinctive pair via system stack with `"IBM Plex Sans", "Segoe UI", sans-serif` and mono for resource types (`"IBM Plex Mono", ui-monospace, monospace`) — falls back cleanly offline.
- Motion: short fade/expand on finding open; KPI number fade-in; bar width transition once on load (2–3 intentional motions).
- No floating badges/stickers on the header visual plane.
- Breakdown rows are interactive filters (click provider → filter inventory), not decorative cards.

## 4. Findings model

`build_findings(report, inventory_rows) -> list[Finding]`

Each finding:

```python
{
  "id": "provider-concentration-hashicorp-aws",
  "severity": "high" | "medium" | "info",
  "title": str,
  "summary": str,
  "category": "availability" | "concentration" | "distribution" | "inventory",
  "detail_rows": [ ... subset of inventory or error rows ... ],
}
```

### v1 finding rules

| ID pattern | When | Severity |
|------------|------|----------|
| `workspace-errors` | `errors` non-empty | high |
| `provider-concentration` | any provider `pct >= 60` | medium |
| `top-resource-type` | top type exists | info |
| `workspace-hotspot` | a workspace holds `>= 40%` of instances (and >1 workspace) | medium |
| `empty-inventory` | instances == 0 | high |

Findings are derived only from report/inventory already in memory (no extra API calls).

## 5. HTML payload & security

- Embed report JSON + inventory records (list of dicts) inside `<script type="application/json" id="rum-data">`.
- All dynamic text HTML-escaped when rendered server-side; client JS uses `textContent` / careful DOM APIs.
- Do not embed API tokens or raw state JSON.
- Large inventories: embed full rows for v1; document that very large org exports may produce large HTML files (`--max-workspaces` remains the relief valve).

## 6. CLI

Extend `rum_report.py`:

- `--format html`
- When `html`, **`--output` required** (cannot meaningfully stream a dashboard to a TTY as primary UX); if omitted, default write `rum-report.html` in CWD and print its path.
- Also accept `--output something.html` with `--format table|json` unchanged.

Stdout: short confirmation `Wrote HTML report: path` plus optional one-line totals; full dashboard is the file.

## 7. Modules

| File | Role |
|------|------|
| `findings.py` | Pure finding rules + tests |
| `html_report.py` | `render_html_report(report, inventory_df) -> str` and `write_html_report(...)` |
| `rum_report.py` | Wire `--format html` |
| `tests/test_findings.py` | Rule coverage |
| `tests/test_html_report.py` | Markup/escaping/sections |
| `README.md` | Operator docs |

## 8. Non-goals (v1)

- Hosted web app / auth
- Chart.js / external CDNs
- PDF export
- Diffing two HTML reports
- Embedding temporary-name scan (can be a later finding source)

## 9. Testing strategy

- Unit: each finding rule with fixture report dicts
- Unit: HTML contains required landmarks (`RUM Analysis`, findings section, KPI values)
- Unit: XSS — resource name with `<script>` appears escaped
- CLI: `--format html --output tmp.html` exit 0 and file exists

## 10. Locked assumptions

1. Single self-contained HTML file per run.
2. Reuse existing report + inventory; findings are a view-layer derivation.
3. Offline-first; no CDN.
4. Python 3.9+; stdlib HTML generation (`html` module) + existing pandas.
