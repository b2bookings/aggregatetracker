// Salesforce REST helpers shared by api/salesforce.js and api/tasks.js.
// Credentials come from Vercel environment variables:
//   SF_LOGIN_URL, SF_CLIENT_ID, SF_CLIENT_SECRET (connected app, client-credentials flow)
//   SF_CONTACT_FIELDS (optional) extra Contact fields to read

const API = "v61.0";
const STANDARD_FIELDS = ["Id", "Email", "AccountId", "Account.Name", "Owner.Name", "LastActivityDate"];

let cachedToken = null;

async function token() {
  if (cachedToken && cachedToken.expires > Date.now()) return cachedToken;
  const res = await fetch(`${process.env.SF_LOGIN_URL.replace(/\/$/, "")}/services/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "client_credentials",
      client_id: process.env.SF_CLIENT_ID,
      client_secret: process.env.SF_CLIENT_SECRET,
    }),
  });
  if (!res.ok) throw new Error(`Salesforce auth failed (${res.status}): ${await res.text()}`);
  const data = await res.json();
  cachedToken = { access: data.access_token, instance: data.instance_url, expires: Date.now() + 20 * 60 * 1000 };
  return cachedToken;
}

async function sf(path, init = {}) {
  const t = await token();
  const res = await fetch(`${t.instance}/services/data/${API}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${t.access}`, "Content-Type": "application/json", ...(init.headers || {}) },
  });
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const err = new Error((body && body[0] && body[0].message) || `Salesforce ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return body;
}

const quote = (s) => "'" + String(s).replace(/\\/g, "\\\\").replace(/'/g, "\\'") + "'";
const pick = (rec, dotted) => dotted.split(".").reduce((cur, k) => (cur == null ? cur : cur[k]), rec);

export async function lookup(emails) {
  const custom = (process.env.SF_CONTACT_FIELDS || "Outbound_Contact__c,Account.Engagement_Stage__c")
    .split(",").map((f) => f.trim()).filter(Boolean);
  let fields = [...STANDARD_FIELDS, ...custom];
  const out = {};
  for (let i = 0; i < emails.length; i += 100) {
    const chunk = emails.slice(i, i + 100);
    const where = `Email IN (${chunk.map(quote).join(",")})`;
    let result;
    try {
      result = await sf(`/query?q=${encodeURIComponent(`SELECT ${fields.join(", ")} FROM Contact WHERE ${where}`)}`);
    } catch (err) {
      if (err.status !== 400 || fields.length === STANDARD_FIELDS.length) throw err;
      fields = STANDARD_FIELDS; // custom field names don't exist in this org
      result = await sf(`/query?q=${encodeURIComponent(`SELECT ${fields.join(", ")} FROM Contact WHERE ${where}`)}`);
    }
    for (const r of result.records) {
      const extra = Object.fromEntries(fields.filter((f) => !STANDARD_FIELDS.includes(f)).map((f) => [f.split(".").pop(), pick(r, f)]));
      out[(r.Email || "").toLowerCase()] = {
        id: r.Id, account_id: r.AccountId, account: pick(r, "Account.Name"), owner: pick(r, "Owner.Name"),
        last_activity: r.LastActivityDate, ...extra,
      };
    }
  }
  return out;
}

async function findPerson(email) {
  const q = (obj) => `/query?q=${encodeURIComponent(`SELECT Id FROM ${obj} WHERE Email = ${quote(email)} LIMIT 1`)}`;
  const contact = await sf(q("Contact"));
  if (contact.records.length) return { id: contact.records[0].Id, type: "Contact" };
  const lead = await sf(q("Lead"));
  if (lead.records.length) return { id: lead.records[0].Id, type: "Lead" };
  return null;
}

export async function createTask({ email, subject, description, dueDate, status }) {
  const who = await findPerson(email);
  if (!who) return { ok: false, error: "No Salesforce Contact or Lead with that email - create a lead first." };
  const created = await sf("/sobjects/Task", {
    method: "POST",
    body: JSON.stringify({
      WhoId: who.id,
      Subject: (subject || "Follow up - aggregate tracker signal").slice(0, 255),
      Description: description || "",
      ActivityDate: dueDate || new Date(Date.now() + 2 * 864e5).toISOString().slice(0, 10),
      Status: status || "Not Started",
      Priority: "High",
    }),
  });
  return { ok: true, id: created.id, who };
}

export async function createLead(c) {
  if (c.email) {
    const existing = await findPerson(c.email);
    if (existing) return { ok: true, id: existing.id, existing: true, type: existing.type };
  }
  const created = await sf("/sobjects/Lead", {
    method: "POST",
    body: JSON.stringify({
      FirstName: c.first_name, LastName: c.last_name || "(unknown)", Title: c.title, Company: c.company || "(unknown)",
      Email: c.email, MobilePhone: c.mobile, State: c.state, LeadSource: "Aggregate Tracker",
    }),
  });
  return { ok: true, id: created.id, existing: false, type: "Lead" };
}

export const salesforceConfigured = () =>
  Boolean(process.env.SF_LOGIN_URL && process.env.SF_CLIENT_ID && process.env.SF_CLIENT_SECRET);
