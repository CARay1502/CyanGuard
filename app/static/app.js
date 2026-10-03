// Analyze page: generate with Cyan, run a compliance check, see history.
// Uses helpers from common.js (loaded first).

// --- Step 1: generate with Cyan ---
let lastGenerated = { prompt: "", model: "", output: "" };

const sourceLabel = (model) => (model === "cyan-demo-script" ? "Source: demo script" : `Source: ${model}`);

// `scenario` is a demo scenario ID: the server returns its scripted output instead of calling the model.
async function generate(prompt, scenario = null) {
  const btn = $("generate-form").querySelector("button");
  btn.disabled = true;
  try {
    const { output, model } = await api("/cyan/generate", {
      method: "POST",
      body: JSON.stringify({ prompt, scenario }),
    });
    lastGenerated = { prompt, model, output };
    $("output").value = output;
    $("source").textContent = sourceLabel(model);
    $("scripted-note").hidden = scenario === null;
  } catch (err) {
    alert(`Generate failed: ${err.message}`);
  } finally {
    btn.disabled = false;
  }
}

$("generate-form").addEventListener("submit", (e) => {
  e.preventDefault();
  generate($("prompt").value); // typed prompts always go to the real model
});

async function loadScenarios() {
  const scenarios = await api("/cyan/scenarios");
  $("scenario-chips").append(...scenarios.map((s) => {
    const chip = el("button", { type: "button", className: "chip", textContent: s.label, title: s.prompt });
    chip.addEventListener("click", () => {
      $("prompt").value = s.prompt;
      generate(s.prompt, s.id);
    });
    return chip;
  }));
}

$("output").addEventListener("input", () => {
  const edited = $("output").value !== lastGenerated.output;
  $("source").textContent = lastGenerated.model && !edited ? sourceLabel(lastGenerated.model) : "Source: manual";
  if (edited) $("scripted-note").hidden = true;
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
  if (!(await initShell({ active: "analyze" }))) return;
  await Promise.all([loadScenarios(), loadHistory()]);

  // Opened from the review queue: /?review=<id>
  const reviewId = new URLSearchParams(location.search).get("review");
  if (reviewId) {
    try {
      const review = await api(`/reviews/${encodeURIComponent(reviewId)}`);
      $("output").value = review.text;
      renderReport(review);
    } catch (err) {
      alert(`Couldn't open that review: ${err.message}`);
    }
  }
}

init();
