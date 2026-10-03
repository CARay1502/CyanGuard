// Review queue page: compliance cases plus the notification outbox. Uses helpers from common.js.

let caseFilter = "active";

async function loadCases() {
  const rows = await api(`/cases?state=${caseFilter}`);
  const body = $("cases");
  body.innerHTML = "";
  if (!rows.length) {
    const empty = { active: "Nothing waiting for review.", resolved: "No resolved cases yet.", all: "No cases yet." };
    body.append(el("tr", {}, el("td", { colSpan: 6, className: "muted", textContent: empty[caseFilter] })));
    return;
  }
  for (const r of rows) {
    const c = r.case;
    const due = dueLabel(c);
    const tr = el("tr", { className: "clickable" },
      el("td", {}, el("span", { className: `priority-pill ${c.priority}`, textContent: c.priority })),
      el("td", {}, el("span", { className: `mini-status ${r.status}`, textContent: STATUS_LABEL[r.status] })),
      el("td", { className: "snippet-cell" }, el("div", { className: "snippet", textContent: r.text })),
      el("td", {}, el("span", { className: `state-pill ${c.state}`, textContent: CASE_STATE_LABEL[c.state] })),
      el("td", { className: "nowrap", textContent: c.assignee?.name || "Unassigned" }),
      el("td", { className: `nowrap ${due.className}`, textContent: due.text }));
    tr.addEventListener("click", () => { location.href = `/case.html?id=${encodeURIComponent(r.id)}`; });
    body.append(tr);
  }
}

async function loadOutbox() {
  const notes = await api("/notifications");
  const list = $("outbox");
  list.innerHTML = "";
  if (!notes.length) {
    list.append(el("li", { className: "muted", textContent: "No alerts yet." }));
    return;
  }
  const deliveryLabel = { sent: "Emailed", failed: "Email failed", outbox: "Outbox only" };
  for (const n of notes.slice(0, 20)) {
    const details = el("details", {},
      el("summary", {},
        el("span", { className: `delivery-pill ${n.delivery.status}`, textContent: deliveryLabel[n.delivery.status] }),
        el("span", { className: "outbox-subject", textContent: n.subject }),
        el("span", { className: "muted nowrap", textContent: new Date(n.created_at).toLocaleString() })),
      el("pre", { className: "outbox-body", textContent: n.body }),
      el("p", { className: "muted", textContent: n.delivery.detail }));
    list.append(el("li", {}, details));
  }
}

document.querySelectorAll(".filter").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".filter").forEach((b) => b.classList.remove("active"));
    button.classList.add("active");
    caseFilter = button.dataset.state;
    loadCases();
  });
});

async function init() {
  if (!(await initShell({ active: "queue", minRole: "compliance" }))) return;
  await Promise.all([loadCases(), loadOutbox()]);
}

init();
