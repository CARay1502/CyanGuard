// Compliance report display, shared by the Analyze and Case pages.
// Expects the report-card markup (#status, #score, #count-*, #report-meta, #highlighted, #flags).
// Uses helpers from common.js.

function renderReport(review, { scroll = true } = {}) {
  $("report-card").hidden = false;

  $("status").className = `status ${review.status}`;
  $("status").textContent = STATUS_LABEL[review.status];
  $("score").textContent = review.score;
  for (const sev of ["high", "medium", "low"]) $(`count-${sev}`).textContent = review.counts[sev];

  const when = new Date(review.created_at).toLocaleString();
  const prompt = review.prompt ? ` · Prompt: “${review.prompt}”` : "";
  $("report-meta").textContent = `Checked by ${review.checker} · Source: ${review.source} · ${when}${prompt}`;

  renderHighlighted(review.text, review.flags);
  renderFlags(review.flags);
  renderCaseBanner(review.case);
  if (scroll) $("report-card").scrollIntoView({ behavior: "smooth", block: "start" });
}

// Pages with a #case-banner element show where a flagged review went.
function renderCaseBanner(caseInfo) {
  const banner = $("case-banner");
  if (!banner) return;
  banner.hidden = !caseInfo;
  if (!caseInfo) return;
  const due = new Date(caseInfo.due_at).toLocaleString();
  banner.replaceChildren(
    el("strong", { textContent: "Sent to compliance review" }),
    ` · ${caseInfo.priority === "high" ? "High" : "Normal"} priority · resolve by ${due} · status: ${CASE_STATE_LABEL[caseInfo.state]}`);
}

function renderHighlighted(text, flags) {
  const box = $("highlighted");
  box.replaceChildren();
  const spans = flags
    .map((f, i) => ({ ...f, n: i + 1 }))
    .filter((f) => f.start !== null && f.start !== undefined)
    .sort((a, b) => a.start - b.start);

  let pos = 0;
  for (const f of spans) {
    if (f.start < pos) continue; // skip overlapping spans
    box.append(text.slice(pos, f.start));
    const mark = el("mark", { className: `sev-${f.severity}`, title: f.title },
      text.slice(f.start, f.end), el("sup", { textContent: f.n }));
    mark.addEventListener("click", () => focusFlag(f.n));
    box.append(mark);
    pos = f.end;
  }
  box.append(text.slice(pos));
}

function focusFlag(n) {
  const item = $(`flag-${n}`);
  document.querySelectorAll(".flag.focus").forEach((x) => x.classList.remove("focus"));
  item.classList.add("focus");
  item.scrollIntoView({ behavior: "smooth", block: "center" });
}

function renderFlags(flags) {
  const list = $("flags");
  list.replaceChildren();
  if (!flags.length) {
    list.append(el("li", { className: "muted", textContent: "No issues found." }));
    return;
  }
  flags.forEach((f, i) => {
    const head = el("div", { className: "flag-head" },
      el("strong", { textContent: `${i + 1}.` }),
      el("span", { className: `sev-pill sev-${f.severity}`, textContent: f.severity }),
      el("strong", { textContent: f.title }));
    const citation = el("div", { className: "muted" }, "Citation: ",
      el("a", { href: f.url, target: "_blank", rel: "noopener", textContent: f.citation }));
    const item = el("li", { className: `flag ${f.severity}`, id: `flag-${i + 1}` }, head, citation);
    if (f.excerpt) item.append(el("blockquote", { textContent: f.excerpt }));
    item.append(
      el("p", { textContent: f.explanation }),
      el("p", {}, el("strong", { textContent: "Fix: " }), f.suggestion));
    list.append(item);
  });
}
