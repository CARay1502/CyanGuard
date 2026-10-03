// Shared by every signed-in page: API helper, DOM helpers, and the header/nav.
// Load it before the page's own script. Each page calls `await initShell({...})` first.

// --- API ---

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 401) {
    location.href = "/login.html"; // session missing or expired
    throw new Error("Not signed in");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ? JSON.stringify(body.detail) : `${res.status} ${res.statusText}`);
  }
  return res.status === 204 ? null : res.json();
}

// --- Labels and DOM helpers ---

const STATUS_LABEL = { PASS: "PASS", NEEDS_REVIEW: "NEEDS REVIEW", FAIL: "FAIL" };
const CASE_STATE_LABEL = {
  open: "Open", in_review: "In review", escalated: "Escalated", approved: "Approved", rejected: "Rejected",
};
const DELIVERY_LABEL = { sent: "Emailed", failed: "Email failed", outbox: "Outbox only" };

const isResolved = (caseInfo) => caseInfo.state === "approved" || caseInfo.state === "rejected";

/** "Due in 3h", "Overdue by 2d", or "Resolved", with a class for styling. */
function dueLabel(caseInfo) {
  if (isResolved(caseInfo)) return { text: "Resolved", className: "due-done" };
  const ms = new Date(caseInfo.due_at) - Date.now();
  const abs = Math.abs(ms);
  const span = abs >= 86400000 ? `${Math.round(abs / 86400000)}d`
    : abs >= 3600000 ? `${Math.round(abs / 3600000)}h`
      : `${Math.max(1, Math.round(abs / 60000))}m`;
  return ms < 0
    ? { text: `Overdue by ${span}`, className: "due-overdue" }
    : { text: `Due in ${span}`, className: ms < 3600000 ? "due-soon" : "due-ok" };
}

const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  node.append(...children);
  return node;
}

// --- Signed-in user and roles ---

let currentUser = null;
const ROLE_RANK = { analyst: 0, compliance: 1, admin: 2 };
const hasRole = (minimum) => currentUser !== null && ROLE_RANK[currentUser.role] >= ROLE_RANK[minimum];

// Pages in the nav, and the lowest role that can open each one.
const NAV = [
  { id: "analyze", label: "Analyze", href: "/", role: "analyst" },
  { id: "queue", label: "Review queue", href: "/queue.html", role: "compliance" },
  { id: "reports", label: "Reports", href: "/reports.html", role: "compliance" },
  { id: "settings", label: "Settings", href: "/settings.html", role: "admin" },
];

// --- Header ---

function renderHeader(active) {
  const brand = el("a", { className: "brand", href: "/" },
    el("span", { className: "logo-mark", ariaHidden: "true" },
      el("img", { src: "/logo.png", alt: "" })),
    el("span", { className: "brand-name", textContent: "CyanGuard" }),
    el("span", { className: "brand-sub", textContent: "Agentic AI Safety Layer" }));

  const nav = el("nav", { className: "main-nav", ariaLabel: "Main" });
  for (const item of NAV.filter((n) => hasRole(n.role))) {
    const link = el("a", { href: item.href, textContent: item.label });
    if (item.id === active) {
      link.className = "active";
      link.setAttribute("aria-current", "page");
    }
    nav.append(link);
  }

  const mode = el("span", { className: "badge", textContent: `${currentUser.mode} mode` });

  const logout = el("button", { type: "button", className: "topbar-btn", textContent: "Sign out" });
  logout.addEventListener("click", async () => {
    await fetch("/auth/logout", { method: "POST" });
    location.href = "/login.html";
  });

  const right = el("div", { className: "topbar-right" },
    mode,
    el("span", { className: "user-chip", textContent: `${currentUser.name} · ${currentUser.role_label}` }),
    logout);

  $("topbar").replaceChildren(el("div", { className: "topbar-inner" }, brand, nav, right));
}

function renderNoAccess(minRole) {
  const needed = { compliance: "Compliance Officer", admin: "Admin" }[minRole] || minRole;
  document.querySelector("main").replaceChildren(
    el("section", { className: "card no-access" },
      el("h2", { textContent: "You don't have access to this page" }),
      el("p", { className: "muted", textContent: `This page needs the ${needed} role. Sign in with a different demo account to see it.` }),
      el("a", { href: "/", className: "button-link", textContent: "Back to Analyze" })));
  document.querySelector(".page-head")?.remove();
}

/**
 * Sign-in check + header for a page. Returns the user, or null if their role
 * can't open this page (a "no access" message is shown instead).
 */
async function initShell({ active, minRole = "analyst" }) {
  currentUser = await api("/auth/me"); // redirects to the login page if signed out
  renderHeader(active);
  if (!hasRole(minRole)) {
    renderNoAccess(minRole);
    return null;
  }
  return currentUser;
}
