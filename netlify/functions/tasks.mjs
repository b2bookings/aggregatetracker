// Shared outreach task status, served at /.netlify/functions/tasks.
//
// Completion marks live in Netlify Blobs (store "outreach-tasks", one blob
// per contact email) so everyone using the tracker sees the same list.
// Same TRACKER_ACCESS_KEY as the Salesforce function. When Salesforce is
// configured, marking a task done also logs a completed Task there.
//
// POST body shapes:
//   { action: "list" }
//   { action: "complete", email, name, company, by, channel, note, signalAt }
//   { action: "reopen", email }

import { getStore } from "@netlify/blobs";
import { createTask, salesforceConfigured } from "./salesforce.mjs";

const CHANNEL_LABEL = { linkedin_dm: "LinkedIn DM", email: "Email", call: "Call" };

const store = () => getStore({ name: "outreach-tasks", consistency: "strong" });
const keyFor = (email) => encodeURIComponent(String(email || "").trim().toLowerCase());

async function list() {
  const s = store();
  const { blobs } = await s.list();
  const records = await Promise.all(blobs.map((b) => s.get(b.key, { type: "json" })));
  const out = {};
  records.forEach((r) => { if (r && r.email) out[r.email] = r; });
  return out;
}

async function complete(body) {
  const email = String(body.email || "").trim().toLowerCase();
  if (!email) return { ok: false, error: "email required" };
  const record = {
    email,
    name: body.name || "",
    company: body.company || "",
    channel: CHANNEL_LABEL[body.channel] ? body.channel : "linkedin_dm",
    note: String(body.note || "").slice(0, 1000),
    done_by: String(body.by || "Someone").slice(0, 80),
    done_at: new Date().toISOString(),
    signal_at: body.signalAt || null,
  };
  await store().setJSON(keyFor(email), record);

  // Best effort: mirror into Salesforce so activity history stays complete.
  if (salesforceConfigured()) {
    try {
      const res = await createTask({
        email,
        status: "Completed",
        subject: `${CHANNEL_LABEL[record.channel]} sent - ${record.name || email}`,
        description: `Logged from the aggregate tracker by ${record.done_by}.${record.note ? "\n\n" + record.note : ""}`,
        dueDate: record.done_at.slice(0, 10),
      });
      record.salesforce = res.ok ? "logged" : res.error;
    } catch (err) {
      record.salesforce = `not logged: ${err.message}`;
    }
  }
  return { ok: true, record };
}

export default async (req) => {
  const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  if (req.method !== "POST") return json({ error: "POST only" }, 405);
  if (!process.env.TRACKER_ACCESS_KEY || req.headers.get("x-tracker-key") !== process.env.TRACKER_ACCESS_KEY) {
    return json({ error: "Unauthorized" }, 401);
  }
  let body;
  try {
    body = await req.json();
  } catch {
    return json({ error: "Invalid JSON" }, 400);
  }
  try {
    if (body.action === "list") return json({ ok: true, completions: await list() });
    if (body.action === "complete") return json(await complete(body));
    if (body.action === "reopen") {
      await store().delete(keyFor(body.email));
      return json({ ok: true });
    }
    return json({ error: "Unknown action" }, 400);
  } catch (err) {
    return json({ ok: false, error: err.message }, 502);
  }
};
