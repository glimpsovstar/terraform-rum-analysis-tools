# HTML Dashboard RUM Report — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Checkbox steps track progress.

**Status:** Implemented 2026-07-29 (`findings.py`, `html_report.py`, CLI `--format html`, tests).

**Goal:** Emit a self-contained HTML dashboard from `rum_report` with KPI overview, breakdowns, expandable findings, and searchable inventory detail.

**Architecture:** `build_findings(report, rows)` derives findings; `render_html_report` embeds JSON + CSS/JS into one file; CLI `--format html` writes it.

**Tech Stack:** Python stdlib (`html`, `json`), existing `report`/`inventory`, pytest.

## Global Constraints

- Offline-first (no CDN).
- Escape all untrusted strings in server-rendered HTML.
- Do not embed tokens or raw Terraform state.
- Spec: `docs/superpowers/specs/2026-07-29-html-dashboard-report-design.md`.

---

### Task 1: Findings engine

**Files:** Create `findings.py`, `tests/test_findings.py`

- [ ] Tests for workspace-errors, provider-concentration (≥60%), top-resource-type, workspace-hotspot (≥40% with >1 ws), empty-inventory
- [ ] Implement `build_findings(report, inventory_records) -> list[dict]`
- [ ] Commit

### Task 2: HTML renderer

**Files:** Create `html_report.py`, `tests/test_html_report.py`

- [ ] `render_html_report(report, inventory_df) -> str`
- [ ] `write_html_report(path, report, inventory_df)`
- [ ] Assert landmarks, KPI numbers, findings block, escaped `<script>` in names
- [ ] Commit

### Task 3: CLI wiring

**Files:** Modify `rum_report.py`, `tests/test_rum_report_cli.py`

- [ ] `--format html`; write file (default `rum-report.html` if `--output` omitted)
- [ ] Print `Wrote HTML report: ...`
- [ ] Commit

### Task 4: Docs

**Files:** `README.md`, mark plan/spec status

- [ ] Document HTML dashboard usage and sections
- [ ] Commit
