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

const $ = (id) => document.getElementById(id);
const STATUS_LABEL = { PASS: "PASS", NEEDS_REVIEW: "NEEDS REVIEW", FAIL: "FAIL" };

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  node.append(...children);
  return node;
}

// --- Signed-in user ---
let currentUser = null;
const ROLE_RANK = { analyst: 0, compliance: 1, admin: 2 };
const hasRole = (minimum) => currentUser && ROLE_RANK[currentUser.role] >= ROLE_RANK[minimum];

$("logout").addEventListener("click", async () => {
  await fetch("/auth/logout", { method: "POST" });
  location.href = "/login.html";
});

// --- Mode badge ---
api("/health").then((h) => {
  $("mode").textContent = `${h.mode} mode`;
});

// --- Step 1: generate with Cyan ---
let lastGenerated = { prompt: "", model: "", output: "" };

async function generate(prompt) {
  const btn = $("generate-form").querySelector("button");
  btn.disabled = true;
  try {
    const { output, model } = await api("/cyan/generate", {
      method: "POST",
      body: JSON.stringify({ prompt }),
    });
    lastGenerated = { prompt, model, output };
    $("output").value = output;
    $("source").textContent = `Source: ${model}`;
  } catch (err) {
    alert(`Generate failed: ${err.message}`);
  } finally {
    btn.disabled = false;
  }
}

$("generate-form").addEventListener("submit", (e) => {
  e.preventDefault();
  generate($("prompt").value);
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    $("prompt").value = chip.dataset.prompt;
    generate(chip.dataset.prompt);
  });
});

$("output").addEventListener("input", () => {
  const edited = $("output").value !== lastGenerated.output;
  $("source").textContent = lastGenerated.model && !edited ? `Source: ${lastGenerated.model}` : "Source: manual";
});

// --- Step 2: compliance check ---
$("check-btn").addEventListener("click", async () => {
  const text = $("output").value.trim();
  if (!text) return;
  const fromCyan = text === lastGenerated.output.trim();
  const btn = $("check-btn");
  btn.disabled = true;
  try {
    const review = await api("/reviews", {
      method: "POST",
      body: JSON.stringify({
        text,
        prompt: fromCyan ? lastGenerated.prompt : "",
        source: fromCyan ? lastGenerated.model : "manual",
      }),
    });
    renderReport(review);
    loadHistory();
  } catch (err) {
    alert(`Compliance check failed: ${err.message}`);
  } finally {
    btn.disabled = false;
  }
});

function renderReport(review) {
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
  $("report-card").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderHighlighted(text, flags) {
  const box = $("highlighted");
  box.innerHTML = "";
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
  list.innerHTML = "";
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

// --- History ---
async function loadHistory() {
  const reviews = await api("/reviews");
  const list = $("history");
  list.innerHTML = "";
  if (!reviews.length) {
    list.append(el("li", { className: "muted", textContent: "No reviews yet." }));
    return;
  }
  for (const r of reviews) {
    const li = el("li", {},
      el("span", { className: `mini-status ${r.status}`, textContent: STATUS_LABEL[r.status] }),
      el("span", { className: "snippet", textContent: r.text }));
    // Compliance officers and admins see everyone's reviews, so show who ran each one.
    if (hasRole("compliance")) {
      li.append(el("span", { className: "muted", textContent: r.submitted_by?.name || "Unknown" }));
    }
    li.append(el("span", { className: "muted", textContent: `${r.score}` }));
    // Reviews are an audit trail: only admins can delete them.
    if (hasRole("admin")) {
      const del = el("button", { className: "link", textContent: "Delete" });
      del.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm("Delete this review from the audit trail?")) return;
        await api(`/reviews/${r.id}`, { method: "DELETE" });
        loadHistory();
      });
      li.append(del);
    }
    li.addEventListener("click", () => {
      $("output").value = r.text;
      renderReport(r);
    });
    list.append(li);
  }
}

async function init() {
  currentUser = await api("/auth/me");
  $("user").textContent = `${currentUser.name} · ${currentUser.role_label}`;
  $("user").hidden = false;
  $("logout").hidden = false;
  loadHistory();
}

init();
