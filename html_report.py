"""Render a self-contained HTML RUM dashboard report."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd

from findings import build_findings


def _inventory_records(inventory_df: pd.DataFrame) -> list[dict[str, Any]]:
    if inventory_df is None or inventory_df.empty:
        return []
    records = inventory_df.where(pd.notnull(inventory_df), None).to_dict(orient="records")
    # Ensure JSON-serializable ints
    for row in records:
        if "instance_count" in row and row["instance_count"] is not None:
            row["instance_count"] = int(row["instance_count"])
    return records


def _safe_json(data: Any) -> str:
    """JSON for embedding in <script type=application/json>; neutralize script breakouts."""
    return json.dumps(data, indent=2).replace("<", "\\u003c").replace(">", "\\u003e")


def _bar_rows(items: list[dict[str, Any]], label_key: str) -> str:
    if not items:
        return '<p class="muted">No data</p>'
    parts: list[str] = []
    for item in items:
        label = escape(str(item.get(label_key) or "—"))
        instances = int(item.get("instances") or 0)
        pct = float(item.get("pct") or 0)
        width = max(pct, 0.5) if instances else 0
        parts.append(
            f'<button type="button" class="bar-row" data-filter-key="{escape(label_key)}" '
            f'data-filter-value="{label}" title="Filter inventory">'
            f'<span class="bar-label">{label}</span>'
            f'<span class="bar-track"><span class="bar-fill" style="--w:{width}%"></span></span>'
            f'<span class="bar-meta">{instances} · {pct}%</span>'
            f"</button>"
        )
    return "\n".join(parts)


def render_html_report(
    report: dict[str, Any],
    inventory_df: pd.DataFrame,
    *,
    generated_at: str | None = None,
) -> str:
    """Return a full HTML document string for the RUM dashboard."""
    records = _inventory_records(inventory_df)
    findings = build_findings(report, records)
    generated_at = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    meta = report.get("meta") or {}
    totals = report.get("totals") or {}
    scope = escape(str(meta.get("scope") or "workspace"))
    organization = escape(str(meta.get("organization") or "—"))
    project = meta.get("project")
    project_html = escape(str(project)) if project else "—"

    payload = {
        "report": report,
        "inventory": records,
        "findings": findings,
        "generated_at": generated_at,
    }

    finding_blocks: list[str] = []
    for finding in findings:
        sev = escape(str(finding.get("severity", "info")))
        fid = escape(str(finding.get("id", "")))
        title = escape(str(finding.get("title", "")))
        summary = escape(str(finding.get("summary", "")))
        detail_count = len(finding.get("detail_rows") or [])
        finding_blocks.append(
            f'<details class="finding severity-{sev}" data-finding-id="{fid}">'
            f"<summary>"
            f'<span class="sev">{sev}</span>'
            f"<span class=\"finding-title\">{title}</span>"
            f'<span class="finding-count">{detail_count} rows</span>'
            f"</summary>"
            f'<p class="finding-summary">{summary}</p>'
            f'<div class="finding-detail" data-finding-detail="{fid}"></div>'
            f"</details>"
        )
    findings_html = (
        "\n".join(finding_blocks)
        if finding_blocks
        else '<p class="muted">No findings for this run.</p>'
    )

    provider_bars = _bar_rows(report.get("by_provider") or [], "provider")
    type_bars = _bar_rows(report.get("by_resource_type") or [], "resource_type")
    # workspace breakdown may lack pct — synthesize for bars
    ws_items = []
    total_instances = int(totals.get("instances") or 0) or 1
    for row in report.get("by_workspace") or []:
        inst = int(row.get("instances") or 0)
        ws_items.append(
            {
                "workspace_name": row.get("workspace_name") or row.get("workspace_id"),
                "instances": inst,
                "pct": round(inst / total_instances * 100.0, 2) if totals.get("instances") else 0,
            }
        )
    workspace_bars = _bar_rows(ws_items, "workspace_name")
    fail_count = int(totals.get("workspaces_failed") or 0)
    kpi_fail_class = " warn" if fail_count else ""
    instances_n = int(totals.get("instances") or 0)
    providers_n = int(totals.get("unique_providers") or 0)
    types_n = int(totals.get("unique_resource_types") or 0)
    findings_n = len(findings)
    generated_escaped = escape(generated_at)
    payload_json = _safe_json(payload)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>RUM Analysis — {scope}</title>
  <style>
    :root {{
      --bg0: #e8eef4;
      --bg1: #f7fafc;
      --ink: #1a2332;
      --muted: #5c6b7a;
      --line: #c9d4e0;
      --accent: #0f766e;
      --accent-soft: #ccfbf1;
      --high: #b45309;
      --medium: #0369a1;
      --info: #475569;
      --panel: rgba(255,255,255,0.82);
      --shadow: 0 1px 0 rgba(26,35,50,0.04);
      --font: "IBM Plex Sans", "Segoe UI", "Helvetica Neue", sans-serif;
      --mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: var(--font);
      color: var(--ink);
      background:
        radial-gradient(1200px 500px at 10% -10%, #d7e8e4 0%, transparent 55%),
        linear-gradient(165deg, var(--bg0), var(--bg1) 45%, #eef3f7);
    }}
    .wrap {{
      width: min(1120px, calc(100% - 2rem));
      margin: 0 auto;
      padding: 2rem 0 3.5rem;
    }}
    header.hero {{
      padding: 0.25rem 0 1.5rem;
      animation: rise 0.55s ease both;
    }}
    .brand {{
      font-size: clamp(1.75rem, 3vw, 2.35rem);
      font-weight: 650;
      letter-spacing: -0.03em;
      margin: 0 0 0.35rem;
    }}
    .brand span {{ color: var(--accent); }}
    .meta {{
      color: var(--muted);
      font-size: 0.95rem;
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem 1.25rem;
    }}
    .meta strong {{ color: var(--ink); font-weight: 600; }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 0.75rem;
      margin: 1.25rem 0 1.75rem;
      animation: rise 0.65s ease both;
    }}
    @media (max-width: 800px) {{
      .kpis {{ grid-template-columns: repeat(2, 1fr); }}
    }}
    .kpi {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 4px;
      padding: 1rem 1.1rem;
      box-shadow: var(--shadow);
    }}
    .kpi .label {{
      display: block;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
      margin-bottom: 0.35rem;
    }}
    .kpi .value {{
      font-size: 1.7rem;
      font-weight: 650;
      letter-spacing: -0.02em;
      font-variant-numeric: tabular-nums;
    }}
    .kpi.warn .value {{ color: var(--high); }}
    section.panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 4px;
      padding: 1.15rem 1.25rem 1.25rem;
      margin-bottom: 1rem;
      box-shadow: var(--shadow);
      animation: rise 0.7s ease both;
    }}
    section.panel h2 {{
      margin: 0 0 0.85rem;
      font-size: 1.05rem;
      letter-spacing: -0.01em;
    }}
    .grid-3 {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 1rem;
    }}
    @media (max-width: 900px) {{
      .grid-3 {{ grid-template-columns: 1fr; }}
    }}
    .bar-row {{
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(0, 1.6fr) auto;
      gap: 0.5rem;
      align-items: center;
      width: 100%;
      margin: 0 0 0.45rem;
      padding: 0.35rem 0.4rem;
      border: 0;
      background: transparent;
      text-align: left;
      font: inherit;
      color: inherit;
      cursor: pointer;
      border-radius: 3px;
    }}
    .bar-row:hover, .bar-row:focus-visible {{
      background: var(--accent-soft);
      outline: none;
    }}
    .bar-label {{
      font-family: var(--mono);
      font-size: 0.78rem;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .bar-track {{
      height: 0.45rem;
      background: #e2e8f0;
      border-radius: 999px;
      overflow: hidden;
    }}
    .bar-fill {{
      display: block;
      height: 100%;
      width: 0;
      background: linear-gradient(90deg, #0f766e, #14b8a6);
      border-radius: inherit;
      animation: grow 0.8s ease forwards;
    }}
    .bar-meta {{
      font-size: 0.75rem;
      color: var(--muted);
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }}
    .finding {{
      border: 1px solid var(--line);
      border-radius: 3px;
      margin-bottom: 0.55rem;
      background: #fff;
      overflow: hidden;
    }}
    .finding > summary {{
      list-style: none;
      cursor: pointer;
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 0.75rem;
      align-items: center;
      padding: 0.75rem 0.9rem;
    }}
    .finding > summary::-webkit-details-marker {{ display: none; }}
    .finding[open] > summary {{ border-bottom: 1px solid var(--line); }}
    .finding-summary {{
      margin: 0;
      padding: 0.75rem 0.9rem 0.35rem;
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .finding-detail {{
      padding: 0.35rem 0.9rem 0.9rem;
      max-height: 280px;
      overflow: auto;
    }}
    .sev {{
      font-size: 0.68rem;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      font-weight: 700;
      padding: 0.2rem 0.4rem;
      border-radius: 2px;
      background: #e2e8f0;
      color: var(--info);
    }}
    .severity-high .sev {{ background: #ffedd5; color: var(--high); }}
    .severity-medium .sev {{ background: #e0f2fe; color: var(--medium); }}
    .severity-info .sev {{ background: #e2e8f0; color: var(--info); }}
    .finding-title {{ font-weight: 600; }}
    .finding-count {{ color: var(--muted); font-size: 0.8rem; }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.6rem;
      align-items: center;
      margin-bottom: 0.75rem;
    }}
    .toolbar input {{
      flex: 1;
      min-width: 180px;
      border: 1px solid var(--line);
      border-radius: 3px;
      padding: 0.55rem 0.7rem;
      font: inherit;
      background: #fff;
    }}
    .toolbar button {{
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 3px;
      padding: 0.5rem 0.75rem;
      font: inherit;
      cursor: pointer;
    }}
    .toolbar button:hover {{ border-color: var(--accent); color: var(--accent); }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.84rem;
    }}
    th, td {{
      text-align: left;
      padding: 0.45rem 0.5rem;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-weight: 600;
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    td.mono {{ font-family: var(--mono); font-size: 0.78rem; }}
    .muted {{ color: var(--muted); }}
    footer {{
      margin-top: 1.5rem;
      color: var(--muted);
      font-size: 0.8rem;
    }}
    @keyframes rise {{
      from {{ opacity: 0; transform: translateY(8px); }}
      to {{ opacity: 1; transform: none; }}
    }}
    @keyframes grow {{
      from {{ width: 0; }}
      to {{ width: var(--w); }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="hero">
      <h1 class="brand">RUM <span>Analysis</span></h1>
      <div class="meta">
        <span>Scope <strong>{scope}</strong></span>
        <span>Organization <strong>{organization}</strong></span>
        <span>Project <strong>{project_html}</strong></span>
        <span>Generated <strong>{generated_escaped}</strong></span>
      </div>
    </header>

    <div class="kpis" id="kpi-band">
      <div class="kpi"><span class="label">Managed instances</span><span class="value" id="kpi-instances">{instances_n}</span></div>
      <div class="kpi"><span class="label">Providers</span><span class="value">{providers_n}</span></div>
      <div class="kpi"><span class="label">Resource types</span><span class="value">{types_n}</span></div>
      <div class="kpi{kpi_fail_class}"><span class="label">Workspace failures</span><span class="value">{fail_count}</span></div>
    </div>

    <section class="panel" aria-labelledby="breakdowns-title">
      <h2 id="breakdowns-title">Breakdowns</h2>
      <div class="grid-3">
        <div>
          <h3 class="muted" style="margin:0 0 0.5rem;font-size:0.85rem;">By provider</h3>
          {provider_bars}
        </div>
        <div>
          <h3 class="muted" style="margin:0 0 0.5rem;font-size:0.85rem;">By resource type</h3>
          {type_bars}
        </div>
        <div>
          <h3 class="muted" style="margin:0 0 0.5rem;font-size:0.85rem;">By workspace</h3>
          {workspace_bars}
        </div>
      </div>
    </section>

    <section class="panel" aria-labelledby="findings-title">
      <h2 id="findings-title">Findings <span class="muted" id="findings-count">({findings_n})</span></h2>
      <div id="findings-list">
        {findings_html}
      </div>
    </section>

    <section class="panel" aria-labelledby="inventory-title">
      <h2 id="inventory-title">Inventory detail</h2>
      <div class="toolbar">
        <input id="inventory-search" type="search" placeholder="Filter by provider, type, name, workspace…" />
        <button type="button" id="clear-filter">Clear filter</button>
        <span class="muted" id="inventory-count"></span>
      </div>
      <div style="overflow:auto; max-height:420px;">
        <table>
          <thead>
            <tr>
              <th>Workspace</th>
              <th>Provider</th>
              <th>Type</th>
              <th>Name</th>
              <th>Module</th>
              <th>Count</th>
            </tr>
          </thead>
          <tbody id="inventory-body"></tbody>
        </table>
      </div>
    </section>

    <footer>Self-contained RUM dashboard · no network required · generated by rum_report.py</footer>
  </div>

  <script type="application/json" id="rum-data">
{payload_json}
  </script>
  <script>
  (function () {{
    const data = JSON.parse(document.getElementById("rum-data").textContent);
    const inventory = data.inventory || [];
    const findings = data.findings || [];
    const body = document.getElementById("inventory-body");
    const search = document.getElementById("inventory-search");
    const countEl = document.getElementById("inventory-count");
    let activeFilter = null;

    function rowText(r) {{
      return [
        r.workspace_name, r.workspace_id, r.provider, r.resource_type,
        r.resource_name, r.module, r.project_name
      ].map(v => (v == null ? "" : String(v))).join(" ").toLowerCase();
    }}

    function matches(r, q, filter) {{
      if (filter) {{
        const val = r[filter.key];
        if (String(val == null ? "" : val) !== filter.value) return false;
      }}
      if (!q) return true;
      return rowText(r).includes(q);
    }}

    function renderInventory() {{
      const q = (search.value || "").trim().toLowerCase();
      const frag = document.createDocumentFragment();
      let shown = 0;
      for (const r of inventory) {{
        if (!matches(r, q, activeFilter)) continue;
        shown += 1;
        const tr = document.createElement("tr");
        const cells = [
          r.workspace_name || r.workspace_id || "—",
          r.provider || "—",
          r.resource_type || "—",
          r.resource_name || "—",
          r.module || "—",
          r.instance_count == null ? "1" : String(r.instance_count)
        ];
        cells.forEach((text, idx) => {{
          const td = document.createElement("td");
          if (idx >= 1 && idx <= 4) td.className = "mono";
          td.textContent = text;
          tr.appendChild(td);
        }});
        frag.appendChild(tr);
      }}
      body.replaceChildren(frag);
      countEl.textContent = shown + " / " + inventory.length + " rows";
    }}

    function renderFindingDetails() {{
      for (const f of findings) {{
        const host = document.querySelector('[data-finding-detail="' + f.id + '"]');
        if (!host) continue;
        const rows = f.detail_rows || [];
        if (!rows.length) {{
          host.textContent = "No detail rows.";
          continue;
        }}
        const table = document.createElement("table");
        const thead = document.createElement("thead");
        const hr = document.createElement("tr");
        const keys = Object.keys(rows[0]);
        keys.forEach(k => {{
          const th = document.createElement("th");
          th.textContent = k;
          hr.appendChild(th);
        }});
        thead.appendChild(hr);
        table.appendChild(thead);
        const tb = document.createElement("tbody");
        rows.slice(0, 200).forEach(row => {{
          const tr = document.createElement("tr");
          keys.forEach(k => {{
            const td = document.createElement("td");
            td.className = "mono";
            const v = row[k];
            td.textContent = v == null ? "" : String(v);
            tr.appendChild(td);
          }});
          tb.appendChild(tr);
        }});
        table.appendChild(tb);
        host.replaceChildren(table);
      }}
    }}

    document.querySelectorAll(".bar-row").forEach(btn => {{
      btn.addEventListener("click", () => {{
        activeFilter = {{
          key: btn.getAttribute("data-filter-key"),
          value: btn.getAttribute("data-filter-value")
        }};
        // map workspace_name filter key already matches inventory
        if (activeFilter.key === "workspace_name") {{
          /* ok */
        }}
        search.value = "";
        renderInventory();
        document.getElementById("inventory-title").scrollIntoView({{ behavior: "smooth", block: "start" }});
      }});
    }});

    document.getElementById("clear-filter").addEventListener("click", () => {{
      activeFilter = null;
      search.value = "";
      renderInventory();
    }});
    search.addEventListener("input", renderInventory);

    renderFindingDetails();
    renderInventory();
  }})();
  </script>
</body>
</html>
"""


def write_html_report(
    path: str | Path,
    report: dict[str, Any],
    inventory_df: pd.DataFrame,
    *,
    generated_at: str | None = None,
) -> Path:
    out = Path(path)
    if out.suffix.lower() != ".html":
        out = Path(str(path) + ".html")
    out.write_text(
        render_html_report(report, inventory_df, generated_at=generated_at),
        encoding="utf-8",
    )
    return out
