// Request helpers shared by the /api functions.

export const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

// Every function requires the shared TRACKER_ACCESS_KEY so random visitors
// can't read task status or write to Salesforce. Returns an error Response,
// or the parsed JSON body when the request is allowed.
export async function authorize(request) {
  if (!process.env.TRACKER_ACCESS_KEY || request.headers.get("x-tracker-key") !== process.env.TRACKER_ACCESS_KEY) {
    return { error: json({ error: "Unauthorized" }, 401) };
  }
  try {
    return { body: await request.json() };
  } catch {
    return { error: json({ error: "Invalid JSON" }, 400) };
  }
}
