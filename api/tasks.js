// Shared outreach task status, served at /api/tasks.
//
// Completion marks live in Upstash Redis (added to the Vercel project from
// the Marketplace; credentials arrive as UPSTASH_REDIS_REST_URL/TOKEN or
// KV_REST_API_URL/TOKEN) in one hash, field = contact email, so everyone
// using the tracker sees the same list. When Salesforce is configured,
// marking a task done also logs a completed Task there.
//
// POST body shapes:
//   { action: "list" }
//   { action: "complete", email, name, company, by, channel, note, signalAt }
//   { action: "reopen", email }

import { Redis } from "@upstash/redis";
import { authorize, json } from "./_lib/http.js";
import { createTask, salesforceConfigured } from "./_lib/salesforce.js";

const HASH = "outreach-tasks";
const CHANNEL_LABEL = { linkedin_dm: "LinkedIn DM", email: "Email", call: "Call" };

let redis = null;
const db = () => (redis ??= Redis.fromEnv());

async function list() {
  const all = (await db().hgetall(HASH)) || {};
  // The client parses JSON values automatically; tolerate raw strings too.
  return Object.fromEntries(Object.entries(all).map(([k, v]) => [k, typeof v === "string" ? JSON.parse(v) : v]));
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
  await db().hset(HASH, { [email]: JSON.stringify(record) });
  return { ok: true, record };
}

export async function POST(request) {
  const { body, error } = await authorize(request);
  if (error) return error;
  try {
    if (body.action === "list") return json({ ok: true, completions: await list() });
    if (body.action === "complete") return json(await complete(body));
    if (body.action === "reopen") {
      await db().hdel(HASH, String(body.email || "").trim().toLowerCase());
      return json({ ok: true });
    }
    return json({ error: "Unknown action" }, 400);
  } catch (err) {
    const msg = /Unable to find environment variable/.test(err.message)
      ? "Task storage isn't connected yet - add Upstash Redis to the Vercel project"
      : err.message;
    return json({ ok: false, error: msg }, 502);
  }
}
