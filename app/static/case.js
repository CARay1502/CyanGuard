// Case page: one flagged review, its decision controls, and its audit history.
// Uses helpers from common.js and report.js.

const reviewId = new URLSearchParams(location.search).get("id");
const ACTION_LABEL = {
  open: "Case opened", assign: "Assigned", approve: "Approved", reject: "Rejected",
  escalate: "Escalated", reopen: "Reopened",
};

// Which buttons apply in each state (the server enforces the same rules).
function allowedActions(c) {
  if (isResolved(c)) return hasRole("admin") ? ["reopen"] : [];
  if (c.state === "escalated") return hasRole("admin") ? ["assign", "approve", "reject"] : ["assign"];
  return ["assign", "escalate", "approve", "reject"];
}

function renderCase(review) {
  const c = review.case;
  $("case-subtitle").textContent =
    `${STATUS_LABEL[review.status]} result submitted by ${review.submitted_by?.name || "Unknown"} on ${new Date(review.created_at).toLocaleString()}`;

  $("case-state").className = `state-pill ${c.state}`;
  $("case-state").textContent = CASE_STATE_LABEL[c.state];

  const due = dueLabel(c);
  const details = [
    ["Priority", el("span", { className: `priority-pill ${c.priority}`, textContent: c.priority })],
    ["Assignee", c.assignee?.name || "Unassigned"],
    ["Deadline", el("span", { className: due.className }, `${new Date(c.due_at).toLocaleString()} · ${due.text}`)],
  ];
  if (c.resolved_at) details.push(["Resolved", new Date(c.resolved_at).toLocaleString()]);
  $("case-details").replaceChildren(...details.flatMap(([term, value]) => [
    el("dt", { textContent: term }), el("dd", {}, value),
  ]));

  const allowed = allowedActions(c);
  document.querySelectorAll("#case-actions [data-action]").forEach((button) => {
    button.hidden = !allowed.includes(button.dataset.action);
  });
  $("assignee").hidden = !allowed.includes("assign");
  $("case-actions").hidden = allowed.length === 0;
  if (c.state === "escalated" && !hasRole("admin")) {
    $("action-error").textContent = "This case is escalated. An admin needs to approve or reject it.";
    $("action-error").hidden = false;
  }

  $("history-log").replaceChildren(...[...c.history].reverse().map((h) => el("li", {},
    el("div", { className: "timeline-head" },
      el("strong", { textContent: ACTION_LABEL[h.action] || h.action }),
      h.assignee ? ` to ${h.assignee.name}` : "",
      el("span", { className: "muted", textContent: ` · ${h.by.name} · ${new Date(h.at).toLocaleString()}` })),
    h.note ? el("p", { textContent: h.note }) : "")));

  renderReport(review, { scroll: false });
}

async function act(action) {
  $("action-error").hidden = true;
  const note = $("case-note").value;
  if ((action === "reject" || action === "escalate" || action === "reopen") && !note.trim()) {
    $("action-error").textContent = `Add a note to ${action} this case.`;
    $("action-error").hidden = false;
    $("case-note").focus();
    return;
  }
  const buttons = document.querySelectorAll("#case-actions button");
  buttons.forEach((b) => { b.disabled = true; });
  try {
    const review = await api(`/reviews/${encodeURIComponent(reviewId)}/case`, {
      method: "POST",
      body: JSON.stringify({ action, note, assignee_id: action === "assign" ? $("assignee").value : null }),
    });
    $("case-note").value = "";
    renderCase(review);
  } catch (err) {
    $("action-error").textContent = err.message.replace(/^"|"$/g, "");
    $("action-error").hidden = false;
  } finally {
    buttons.forEach((b) => { b.disabled = false; });
  }
}

document.querySelectorAll("#case-actions [data-action]").forEach((button) => {
  button.addEventListener("click", () => act(button.dataset.action));
});

async function init() {
  if (!(await initShell({ active: "queue", minRole: "compliance" }))) return;
  if (!reviewId) {
    location.href = "/queue.html";
    return;
  }
  const [review, people] = await Promise.all([
    api(`/reviews/${encodeURIComponent(reviewId)}`),
    api("/users/assignable"),
  ]);
  $("assignee").replaceChildren(...people.map((p) => el("option", {
    value: p.id,
    textContent: p.id === currentUser.id ? `${p.name} (me)` : p.name,
    selected: p.id === currentUser.id,
  })));
  if (!review.case) {
    $("case-card").replaceChildren(el("h2", { textContent: "No case" }),
      el("p", { className: "muted", textContent: "This review passed, so it never needed a compliance decision." }));
    renderReport(review, { scroll: false });
    return;
  }
  renderCase(review);
}

init();
