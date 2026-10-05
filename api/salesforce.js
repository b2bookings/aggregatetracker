// Salesforce actions for the tracker, served at /api/salesforce.
//
// POST body shapes:
//   { action: "lookup", emails: [...] }
//   { action: "task", email, subject, description, dueDate }        -> Task on the Contact (or Lead)
//   { action: "lead", contact: { first_name, last_name, title, company, email, mobile, state } }

import { authorize, json } from "./_lib/http.js";
import { createLead, createTask, lookup, salesforceConfigured } from "./_lib/salesforce.js";

export async function POST(request) {
  const { body, error } = await authorize(request);
  if (error) return error;
  if (!salesforceConfigured()) return json({ error: "Salesforce is not configured on the server" }, 503);
  try {
    if (body.action === "lookup") return json({ ok: true, contacts: await lookup((body.emails || []).map((e) => String(e).toLowerCase())) });
    if (body.action === "task") return json(await createTask(body));
    if (body.action === "lead") return json(await createLead(body.contact || {}));
    return json({ error: "Unknown action" }, 400);
  } catch (err) {
    return json({ ok: false, error: err.message }, 502);
  }
}
