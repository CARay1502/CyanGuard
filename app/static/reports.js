// Reports page: summary tiles, results-per-day chart, top rules, and digests.
// Uses helpers from common.js.

let days = 30;
let summary = null;

// Stacked bottom to top. Status colors (validated for color-blind separation),
// always shown with a legend, tooltip, and table so color never carries meaning alone.
const SERIES = [
  { key: "FAIL", label: "Fail", color: "var(--chart-fail)" },
  { key: "NEEDS_REVIEW", label: "Needs review", color: "var(--chart-review)" },
  { key: "PASS", label: "Pass", color: "var(--chart-pass)" },
];
const SVG_NS = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

const fmtDate = (iso, opts = { month: "short", day: "numeric" }) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, opts);

// --- Summary tiles ---

function tile(label, value, note = "", className = "") {
  return el("div", { className: `tile ${className}` },
    el("span", { className: "tile-label", textContent: label }),
    el("strong", { className: "tile-value", textContent: value }),
    note ? el("span", { className: "tile-note", textContent: note }) : "");
}

function renderTiles(s) {
  const pct = (n) => (s.total ? `${Math.round((100 * n) / s.total)}%` : "–");
  const c = s.cases;
  const avg = c.avg_hours_to_resolve;
  $("tiles").replaceChildren(
    tile("Outputs reviewed", s.total.toLocaleString(), `in the last ${s.days} days`),
    tile("Pass rate", pct(s.by_status.PASS), `${s.by_status.PASS} passed`),
    tile("Failed", s.by_status.FAIL.toLocaleString(), `${pct(s.by_status.FAIL)} of reviews`),
    tile("Open cases", c.active.toLocaleString(),
      `${c.by_state.open} open · ${c.by_state.in_review} in review · ${c.by_state.escalated} escalated`),
    tile("Overdue", c.overdue.toLocaleString(), c.overdue ? "past their deadline" : "none past deadline",
      c.overdue ? "tile-alert" : ""),
    tile("Avg. time to resolve", avg === null ? "–" : avg < 1 ? `${Math.round(avg * 60)}m` : `${avg}h`,
      `${c.resolved_in_period} resolved this period`));
}

// --- Results per day (stacked columns) ---

function niceMax(value) {
  if (value <= 4) return 4;
  const step = 10 ** Math.floor(Math.log10(value / 4));
  const nice = [1, 2, 5, 10].map((m) => m * step).find((m) => m * 4 >= value);
  return nice * 4;
}

function renderLegend() {
  // Same order as the stack, top to bottom.
  $("trend-legend").replaceChildren(...[...SERIES].reverse().map((s) => el("li", {},
    el("span", { className: "legend-swatch", style: `background:${s.color}` }), s.label)));
}

function renderTrend(s) {
  const box = $("trend-chart");
  box.replaceChildren();
  const width = Math.max(box.clientWidth, 280);
  const height = 220;
  const pad = { top: 10, right: 8, bottom: 26, left: 32 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const totals = s.daily.map((d) => SERIES.reduce((sum, ser) => sum + d[ser.key], 0));
  const yMax = niceMax(Math.max(...totals, 1));
  const y = (v) => pad.top + plotH - (v / yMax) * plotH;
  const band = plotW / s.daily.length;
  const barW = Math.max(2, Math.min(24, band * 0.7));
  const GAP = 2;

  const chart = svg("svg", {
    viewBox: `0 0 ${width} ${height}`, width, height, role: "img",
    "aria-label": `Results per day for the last ${s.days} days. ${s.total} reviews in total. Use the table view for exact values.`,
  });

  // Hairline grid and clean y ticks.
  for (let i = 0; i <= 4; i++) {
    const v = (yMax / 4) * i;
    chart.append(svg("line", { x1: pad.left, x2: width - pad.right, y1: y(v), y2: y(v), class: "grid" }));
    const label = svg("text", { x: pad.left - 6, y: y(v) + 4, class: "tick", "text-anchor": "end" });
    label.textContent = v.toLocaleString();
    chart.append(label);
  }

  // X labels: a handful, evenly spaced, always including today.
  const every = Math.ceil(s.daily.length / 6);
  s.daily.forEach((d, i) => {
    if ((s.daily.length - 1 - i) % every !== 0) return;
    const label = svg("text", { x: pad.left + band * (i + 0.5), y: height - 8, class: "tick", "text-anchor": "middle" });
    label.textContent = fmtDate(d.date);
    chart.append(label);
  });

  const tooltip = el("div", { className: "chart-tooltip", hidden: true });

  s.daily.forEach((d, i) => {
    const cx = pad.left + band * (i + 0.5);
    const x = cx - barW / 2;
    const col = svg("g", { class: "column" });
    const parts = SERIES.filter((ser) => d[ser.key] > 0);
    let base = 0;
    parts.forEach((ser, j) => {
      const top = base + d[ser.key];
      const yTop = y(top);
      const yBottom = y(base) - (j > 0 ? GAP : 0); // 2px surface gap between segments
      const h = Math.max(0, yBottom - yTop);
      const isTop = j === parts.length - 1;
      const r = isTop ? Math.min(4, h, barW / 2) : 0; // rounded data-end, square at the baseline
      col.append(svg("path", {
        d: `M${x},${yBottom} V${yTop + r} Q${x},${yTop} ${x + r},${yTop} H${x + barW - r} Q${x + barW},${yTop} ${x + barW},${yTop + r} V${yBottom} Z`,
        fill: ser.color,
      }));
      base = top;
    });

    // Hit target: the whole day's band, much bigger than the bar.
    const total = totals[i];
    const hit = svg("rect", {
      x: pad.left + band * i, y: pad.top, width: band, height: plotH, class: "hit", tabindex: 0,
      "aria-label": `${fmtDate(d.date, { weekday: "long", month: "long", day: "numeric" })}: ${total} reviews. `
        + SERIES.map((ser) => `${ser.label} ${d[ser.key]}`).join(", "),
    });
    const show = () => {
      col.classList.add("hover");
      tooltip.replaceChildren(
        el("div", { className: "tooltip-title", textContent: fmtDate(d.date, { weekday: "short", month: "short", day: "numeric" }) }),
        ...[...SERIES].reverse().map((ser) => el("div", { className: "tooltip-row" },
          el("span", { className: "tooltip-key", style: `background:${ser.color}` }),
          el("strong", { textContent: d[ser.key] }),
          el("span", { className: "muted", textContent: ser.label }))),
        el("div", { className: "tooltip-total" }, el("strong", { textContent: total }), " total"));
      tooltip.hidden = false;
      const left = Math.min(Math.max(cx - tooltip.offsetWidth / 2, 0), width - tooltip.offsetWidth);
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${Math.max(0, y(total) - tooltip.offsetHeight - 10)}px`;
    };
    const hide = () => { col.classList.remove("hover"); tooltip.hidden = true; };
    hit.addEventListener("pointerenter", show);
    hit.addEventListener("pointerleave", hide);
    hit.addEventListener("focus", show);
    hit.addEventListener("blur", hide);
    chart.append(col, hit);
  });

  box.append(chart, tooltip);

  $("trend-table").replaceChildren(...[...s.daily].reverse().map((d, i) => el("tr", {},
    el("td", { textContent: fmtDate(d.date, { weekday: "short", month: "short", day: "numeric" }) }),
    el("td", { className: "num", textContent: d.FAIL }),
    el("td", { className: "num", textContent: d.NEEDS_REVIEW }),
    el("td", { className: "num", textContent: d.PASS }),
    el("td", { className: "num", textContent: totals[totals.length - 1 - i] }))));
}

// --- Most-triggered rules (single series: one color; severity as a label) ---

function renderTopRules(s) {
  const list = $("top-rules");
  list.replaceChildren();
  if (!s.top_rules.length) {
    list.append(el("li", { className: "muted", textContent: "No rules triggered in this period." }));
    return;
  }
  const max = s.top_rules[0].count;
  for (const rule of s.top_rules) {
    const bar = el("span", { className: "bar" });
    bar.style.width = `${(100 * rule.count) / max}%`;
    list.append(el("li", {},
      el("span", { className: "bar-label" },
        el("span", { className: `sev-pill sev-${rule.severity}`, textContent: rule.severity }), ` ${rule.title}`),
      el("span", { className: "bar-track" }, bar),
      el("strong", { className: "bar-value", textContent: rule.count })));
  }
}

// --- Digests ---

async function loadDigests() {
  const digests = await api("/reports/digests");
  const list = $("digests");
  list.replaceChildren();
  if (!digests.length) {
    list.append(el("li", { className: "muted", textContent: "No digests yet." }));
    return;
  }
  for (const d of digests.slice(0, 15)) {
    const who = d.trigger === "scheduled" ? "Scheduled" : `By ${d.created_by.name}`;
    list.append(el("li", {}, el("details", {},
      el("summary", {},
        el("span", { className: `delivery-pill ${d.delivery.status}`, textContent: DELIVERY_LABEL[d.delivery.status] }),
        el("span", { className: "outbox-subject", textContent: `Last ${d.days === 1 ? "24 hours" : `${d.days} days`} · ${d.total} reviewed · ${d.by_status.FAIL} failed · ${d.cases.overdue} overdue` }),
        el("span", { className: "muted nowrap", textContent: `${who} · ${new Date(d.created_at).toLocaleString()}` })),
      el("pre", { className: "outbox-body", textContent: d.body }),
      el("p", { className: "muted", textContent: d.delivery.detail }))));
  }
}

$("generate-digest").addEventListener("click", async (e) => {
  const button = e.currentTarget;
  button.disabled = true;
  try {
    await api("/reports/digests", { method: "POST", body: JSON.stringify({ days }) });
    await loadDigests();
    $("digests").querySelector("details")?.setAttribute("open", "");
  } catch (err) {
    alert(`Couldn't generate the digest: ${err.message}`);
  } finally {
    button.disabled = false;
  }
});

// --- Loading ---

async function loadReport() {
  $("report-body").classList.add("loading"); // keep the old render visible, dimmed, while refetching
  try {
    summary = await api(`/reports/summary?days=${days}&tz_offset=${new Date().getTimezoneOffset()}`);
    renderTiles(summary);
    renderTrend(summary);
    renderTopRules(summary);
  } finally {
    $("report-body").classList.remove("loading");
  }
}

document.querySelectorAll(".filter[data-days]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".filter[data-days]").forEach((b) => b.classList.remove("active"));
    button.classList.add("active");
    days = Number(button.dataset.days);
    $("export-csv").href = `/reports/export.csv?days=${days}`;
    loadReport();
  });
});

let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => summary && renderTrend(summary), 150);
});

async function init() {
  if (!(await initShell({ active: "reports", minRole: "compliance" }))) return;
  renderLegend();
  await Promise.all([loadReport(), loadDigests()]);
}

init();
