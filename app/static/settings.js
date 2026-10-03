// Settings page (admin): environment info, case alert settings, and the rule catalog.
// Uses helpers from common.js.

function renderAlertSettings(settings) {
  const email = $("email_notifications");
  email.checked = settings.email_notifications;
  email.disabled = !settings.email_available;
  $("email-help").textContent = settings.email_available
    ? "Sent through Amazon SNS to everyone subscribed to the CyanGuard topic."
    : settings.mode === "aws"
      ? "Unavailable: set the SNS_TOPIC_ARN environment variable on the Lambda function first."
      : "Unavailable in local mode. Alerts are saved to the outbox on the Review queue page.";

  document.querySelectorAll('input[name="notify_on"]').forEach((box) => {
    box.checked = settings.notify_on.includes(box.value);
  });
  $("sla_hours_high").value = settings.sla_hours_high;
  $("sla_hours_normal").value = settings.sla_hours_normal;
  $("digest_days").value = settings.digest_days;
}

$("alerts-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const status = $("settings-status");
  const button = e.target.querySelector("button[type=submit]");
  button.disabled = true;
  status.textContent = "Saving…";
  try {
    const saved = await api("/admin/settings", {
      method: "PUT",
      body: JSON.stringify({
        email_notifications: $("email_notifications").checked,
        notify_on: [...document.querySelectorAll('input[name="notify_on"]:checked')].map((b) => b.value),
        sla_hours_high: Number($("sla_hours_high").value),
        sla_hours_normal: Number($("sla_hours_normal").value),
        digest_days: Number($("digest_days").value),
      }),
    });
    renderAlertSettings(saved);
    status.textContent = `Saved at ${new Date().toLocaleTimeString()}.`;
  } catch (err) {
    status.textContent = `Couldn't save: ${err.message}`;
  } finally {
    button.disabled = false;
  }
});

async function init() {
  if (!(await initShell({ active: "settings", minRole: "admin" }))) return;
  const [health, rules, settings] = await Promise.all([api("/health"), api("/rules"), api("/admin/settings")]);

  const env = [
    ["Mode", health.mode === "aws" ? "AWS (Bedrock + DynamoDB)" : "Local (no AWS)"],
    ["Signed in as", `${currentUser.name} (${currentUser.role_label})`],
    ["Rules", `${rules.length} active`],
  ];
  $("environment").replaceChildren(...env.flatMap(([term, value]) => [
    el("dt", { textContent: term }),
    el("dd", { textContent: value }),
  ]));

  renderAlertSettings(settings);

  $("rules").replaceChildren(...rules.map((rule) => el("tr", {},
    el("td", {}, el("strong", { textContent: rule.title }), el("div", { className: "muted", textContent: rule.id })),
    el("td", {}, el("span", { className: `sev-pill sev-${rule.severity}`, textContent: rule.severity })),
    el("td", {}, el("a", { href: rule.url, target: "_blank", rel: "noopener", textContent: rule.citation })))));
}

init();
