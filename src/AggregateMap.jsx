import React, { useState, useMemo, useEffect } from "react";

const NAVY = "#2B2B2E"; // steel/charcoal — industrial, replaces navy-blue corporate feel
const GOLD = "#F7830F"; // Turner Mining Group brand orange
const CREAM = "#F2F0EC"; // cooler, more neutral industrial grey (was warm cream)
const INK = "#2A2A28";

const TREND_COLOR = {
  growing: "#3E7A4C",
  flat: "#8C8577",
  declining: "#B0453E",
  unknown: "#D8D3C8",
};

const TIER_LABEL = { "Tier 1": "Tier 1 \u2014 VP / Regional", "Tier 2": "Tier 2 \u2014 Area / Ops", "Tier 3": "Tier 3 \u2014 Site-level" };

// Direct-border adjacency for the 48 contiguous states + DC. AK, HI, PR have
// no land borders, so they're only ever matched at hop 0 (their own state).
const STATE_ADJACENCY = {
  AL: ["FL","GA","MS","TN"], AZ: ["CA","CO","NV","NM","UT"],
  AR: ["LA","MS","MO","OK","TN","TX"], CA: ["AZ","NV","OR"],
  CO: ["AZ","KS","NE","NM","OK","UT","WY"], CT: ["MA","NY","RI"],
  DE: ["MD","NJ","PA"], FL: ["AL","GA"], GA: ["AL","FL","NC","SC","TN"],
  ID: ["MT","NV","OR","UT","WA","WY"], IL: ["IN","IA","KY","MO","WI"],
  IN: ["IL","KY","MI","OH"], IA: ["IL","MN","MO","NE","SD","WI"],
  KS: ["CO","MO","NE","OK"], KY: ["IL","IN","MO","OH","TN","VA","WV"],
  LA: ["AR","MS","TX"], ME: ["NH"], MD: ["DE","PA","VA","WV","DC"],
  MA: ["CT","NH","NY","RI","VT"], MI: ["IN","OH","WI"],
  MN: ["IA","ND","SD","WI"], MS: ["AL","AR","LA","TN"],
  MO: ["AR","IL","IA","KS","KY","NE","OK","TN"], MT: ["ID","ND","SD","WY"],
  NE: ["CO","IA","KS","MO","SD","WY"], NV: ["AZ","CA","ID","OR","UT"],
  NH: ["ME","MA","VT"], NJ: ["DE","NY","PA"], NM: ["AZ","CO","OK","TX","UT"],
  NY: ["CT","MA","NJ","PA","VT"], NC: ["GA","SC","TN","VA"],
  ND: ["MN","MT","SD"], OH: ["IN","KY","MI","PA","WV"],
  OK: ["AR","CO","KS","MO","NM","TX"], OR: ["CA","ID","NV","WA"],
  PA: ["DE","MD","NJ","NY","OH","WV"], RI: ["CT","MA"], SC: ["GA","NC"],
  SD: ["IA","MN","MT","ND","NE","WY"], TN: ["AL","AR","GA","KY","MS","MO","NC","VA"],
  TX: ["AR","LA","NM","OK"], UT: ["AZ","CO","ID","NV","NM","WY"],
  VT: ["MA","NH","NY"], VA: ["KY","MD","NC","TN","WV","DC"],
  WA: ["ID","OR"], WV: ["KY","MD","OH","PA","VA"], WI: ["IL","IA","MI","MN"],
  WY: ["CO","ID","MT","NE","SD","UT"], DC: ["MD","VA"],
};
const TIER_HOPS = { "Tier 1": 2, "Tier 2": 1, "Tier 3": 0 };
function statesWithinHops(origin, maxHops) {
  const visited = new Set([origin]);
  let frontier = [origin];
  for (let h = 0; h < maxHops; h++) {
    const next = [];
    frontier.forEach((s) => {
      (STATE_ADJACENCY[s] || []).forEach((n) => {
        if (!visited.has(n)) {
          visited.add(n);
          next.push(n);
        }
      });
    });
    frontier = next;
  }
  return visited;
}
function contactReachesStates(contact, siteStates) {
  const maxHops = TIER_HOPS[contact.tier] ?? 0;
  return siteStates.some((s) => statesWithinHops(s, maxHops).has(contact.state));
}

// Match quality: geography + role fit, with a deliberate lean toward Tier 2/3
// (the people who actually own site/regional production) over Tier 1 corporate
// VPs, whose reach is broad but often too high-level for a single site's story.
const DEMOTE_TITLE_KEYWORDS = [
  "excellence", "technology", "talent", "golf", "marketing", "finance",
  "analyst", "coordinator", "recruit", "human resources", " hr ", "it manager",
];
const PROMOTE_TITLE_KEYWORDS = [
  "general manager", "plant manager", "quarry manager", "site manager",
  "operations manager", "regional manager", "area manager", "district manager",
  "vice president operations", "vp operations", "president",
];
function titleSignal(title) {
  const t = (" " + (title || "").toLowerCase() + " ");
  if (DEMOTE_TITLE_KEYWORDS.some((k) => t.includes(k))) return -3;
  if (PROMOTE_TITLE_KEYWORDS.some((k) => t.includes(k))) return 2;
  return 0;
}
function hopDistance(origin, target) {
  if (origin === target) return 0;
  for (let h = 1; h <= 2; h++) {
    if (statesWithinHops(origin, h).has(target)) return h;
  }
  return 3;
}
function matchScore(contact, siteStates) {
  const geoScore = Math.max(...siteStates.map((s) => 3 - hopDistance(s, contact.state)));
  const tierScore = contact.tier === "Tier 1" ? 1 : 3;
  return geoScore + tierScore + titleSignal(contact.title);
}

// Rough equirectangular projection tuned to the continental US bounding box.
const LON_MIN = -125, LON_MAX = -66.5, LAT_MIN = 24.3, LAT_MAX = 49.5;
const W = 960, H = 560;
function project(lat, lon) {
  const x = ((lon - LON_MIN) / (LON_MAX - LON_MIN)) * W;
  const y = H - ((lat - LAT_MIN) / (LAT_MAX - LAT_MIN)) * H;
  return [x, y];
}

function fmtPct(v) {
  if (v === undefined || v === null) return "\u2014";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}%`;
}

// Group nearby same-company sites into a single circle so dense regions
// don't render a dot per site. ~0.9deg cell trims the map to roughly half
// its raw site count while leaving genuinely sparse areas untouched.
const CLUSTER_CELL = 0.9;
function clusterSites(list) {
  const buckets = new Map();
  list.forEach((s) => {
    const key = `${s.company}|${Math.round(s.lat / CLUSTER_CELL)}|${Math.round(s.lon / CLUSTER_CELL)}`;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(s);
  });
  return Array.from(buckets.values()).map((group) => {
    if (group.length === 1) {
      return { ...group[0], members: group };
    }
    const employees = group.reduce((sum, s) => sum + (s.employees || 0), 0);
    const lat = group.reduce((sum, s) => sum + s.lat, 0) / group.length;
    const lon = group.reduce((sum, s) => sum + s.lon, 0) / group.length;
    const trendCounts = {};
    const stateCounts = {};
    group.forEach((s) => {
      trendCounts[s.trend_class] = (trendCounts[s.trend_class] || 0) + 1;
      stateCounts[s.state] = (stateCounts[s.state] || 0) + 1;
    });
    const trend_class = Object.entries(trendCounts).sort((a, b) => b[1] - a[1])[0][0];
    const majorityState = Object.entries(stateCounts).sort((a, b) => b[1] - a[1])[0][0];
    return {
      mine_id: "cluster-" + group.map((s) => s.mine_id).join("-"),
      name: `${group.length} sites (${majorityState})`,
      company: group[0].company,
      state: majorityState,
      county: null,
      mine_type: null,
      material: null,
      employees,
      pct_off_peak: null,
      trend_last3: null,
      trend_class,
      lat,
      lon,
      portable: false,
      isCluster: true,
      members: group,
    };
  });
}

function Dashboard({ SITES, CONTACTS, STATE_CENTROIDS, STATE_PATHS }) {
  const COMPANIES = useMemo(() => Array.from(new Set(SITES.map((s) => s.company))).sort(), [SITES]);
  const companiesWithSignal = useMemo(() => {
    const set = new Set();
    SITES.forEach((s) => {
      if (s.news && s.news.length) set.add(s.company);
    });
    return set;
  }, [SITES]);

  // Site starts in intent-signal mode by default, showing every company that
  // currently has a finding. hasManualIntentPick tracks whether the user has
  // clicked a specific company yet: the FIRST click while still in the
  // default "show every signal company" state isolates to just that one
  // company; every click after that behaves as a normal add/remove toggle.
  const [activeCompanies, setActiveCompanies] = useState(() => new Set(companiesWithSignal));
  const [intentMode, setIntentMode] = useState(true);
  const [hasManualIntentPick, setHasManualIntentPick] = useState(false);
  const [selectedSite, setSelectedSite] = useState(null);
  const [hoverSite, setHoverSite] = useState(null);
  const [showAllContacts, setShowAllContacts] = useState(false);
  const [sfStatus, setSfStatus] = useState({}); // email -> { stage, outbound, source, last_activity }
  const [sfSync, setSfSync] = useState({ state: "idle", synced: 0, total: 0, error: null });

  // NOTE for standalone/Netlify deployment: this calls api.anthropic.com,
  // which only works inside Claude's own artifact preview (Claude injects
  // auth for that call automatically there). Outside Claude — e.g. hosted
  // here on Netlify — this request has no credentials and will fail. That's
  // fine: the sync already falls back cleanly to the Apollo-based contact
  // badges on any error, so the map still works correctly. To make this
  // button do something real on your own domain, you'd need to stand up
  // your own backend (e.g. a Netlify Function) that holds a Salesforce
  // API token server-side and swap this fetch to call that instead.
  async function syncSalesforce() {
    const emails = CONTACTS.filter((c) => c.email).map((c) => c.email);
    if (emails.length === 0) return;
    setSfSync({ state: "loading", synced: 0, total: emails.length, error: null });

    const BATCH = 25;
    const batches = [];
    for (let i = 0; i < emails.length; i += BATCH) batches.push(emails.slice(i, i + BATCH));

    let merged = {};
    let syncedCount = 0;
    let anySuccess = false;
    let lastError = null;

    await Promise.all(
      batches.map(async (batch) => {
        try {
          const res = await fetch("https://api.anthropic.com/v1/messages", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              model: "claude-sonnet-4-6",
              max_tokens: 1000,
              messages: [
                {
                  role: "user",
                  content:
                    "Query Salesforce Contact records whose Email matches any of: " +
                    batch.join(", ") +
                    ". For each match, get the Contact's Email, the Outbound_Contact__c checkbox, and the related Account's Engagement_Stage__c. Respond ONLY with a compact JSON array, no other text: " +
                    '[{"email":"...","outbound":true,"stage":"..."}]. If a contact has no Salesforce record, omit it. If the fields have different exact API names in this org, use the closest equivalent.',
                },
              ],
              mcp_servers: [
                {
                  type: "url",
                  url: "https://api.salesforce.com/platform/mcp/v1/platform/headless-360",
                  name: "salesforce-mcp",
                },
              ],
            }),
          });
          const data = await res.json();
          const text = (data.content || [])
            .filter((b) => b.type === "text")
            .map((b) => b.text)
            .join("");
          const cleaned = text.replace(/```json|```/g, "").trim();
          const jsonMatch = cleaned.match(/\[[\s\S]*\]/);
          const parsed = JSON.parse(jsonMatch ? jsonMatch[0] : cleaned);
          parsed.forEach((r) => {
            if (r.email) {
              merged[r.email] = { stage: r.stage || null, outbound: !!r.outbound, source: "salesforce" };
            }
          });
          anySuccess = true;
        } catch (err) {
          lastError = String(err && err.message ? err.message : err);
        } finally {
          syncedCount += batch.length;
          setSfSync((prev) => ({ ...prev, synced: syncedCount }));
        }
      })
    );

    setSfStatus(merged);
    setSfSync({
      state: anySuccess ? "done" : "error",
      synced: syncedCount,
      total: emails.length,
      error: anySuccess ? null : lastError || "Salesforce sync failed",
    });
  }

  // Salesforce sync is manual only (see the "Sync Salesforce" button in the
  // header) — it used to fire automatically on every load, which kept
  // throwing errors while the connector was broken. Not auto-running it
  // means the map never makes an unrequested network call on open.

  const signalCountByCompany = useMemo(() => {
    const m = {};
    SITES.forEach((s) => {
      if (s.news && s.news.length) m[s.company] = (m[s.company] || 0) + 1;
    });
    return m;
  }, [SITES]);

  function toggleIntentMode() {
    setIntentMode((prev) => {
      const next = !prev;
      setActiveCompanies(new Set(next ? companiesWithSignal : COMPANIES));
      setHasManualIntentPick(false);
      return next;
    });
    setSelectedSite(null);
    setShowAllContacts(false);
  }

  const rawVisibleSites = useMemo(
    () =>
      SITES.filter(
        (s) =>
          activeCompanies.has(s.company) &&
          s.lat &&
          s.state !== "PR" &&
          (!intentMode || (s.news && s.news.length))
      ),
    [activeCompanies, intentMode]
  );
  const visibleSites = useMemo(() => clusterSites(rawVisibleSites), [rawVisibleSites]);

  const stateSiteCounts = useMemo(() => {
    const m = {};
    visibleSites.forEach((s) => {
      m[s.state] = (m[s.state] || 0) + 1;
    });
    return m;
  }, [visibleSites]);

  const selectedStateContacts = useMemo(() => {
    if (!selectedSite) return [];
    const siteStates = selectedSite.isCluster
      ? Array.from(new Set(selectedSite.members.map((m) => m.state)))
      : [selectedSite.state];
    return CONTACTS.filter(
      (c) => c.state && activeCompanies.has(c.company) && contactReachesStates(c, siteStates)
    )
      .map((c) => ({ ...c, _score: matchScore(c, siteStates) }))
      .sort((a, b) => b._score - a._score);
  }, [selectedSite, activeCompanies]);

  const totals = useMemo(() => {
    const growing = rawVisibleSites.filter((s) => s.trend_class === "growing").length;
    const declining = rawVisibleSites.filter((s) => s.trend_class === "declining").length;
    const employees = rawVisibleSites.reduce((sum, s) => sum + (s.employees || 0), 0);
    return { count: rawVisibleSites.length, shown: visibleSites.length, growing, declining, employees };
  }, [rawVisibleSites, visibleSites]);

  function toggleCompany(c) {
    if (intentMode && !hasManualIntentPick) {
      // First click while still showing the full default signal set: isolate
      // to just this company.
      setActiveCompanies(new Set([c]));
      setHasManualIntentPick(true);
    } else {
      // Every click after that (or any click outside intent mode) is a
      // normal one-at-a-time add/remove toggle.
      setActiveCompanies((prev) => {
        const next = new Set(prev);
        if (next.has(c)) next.delete(c);
        else next.add(c);
        return next;
      });
      if (intentMode) setHasManualIntentPick(true);
    }
    setSelectedSite(null);
    setShowAllContacts(false);
  }
  function toggleAll() {
    setActiveCompanies(activeCompanies.size === COMPANIES.length ? new Set() : new Set(COMPANIES));
    if (intentMode) setHasManualIntentPick(true);
    setSelectedSite(null);
    setShowAllContacts(false);
  }

  const displaySite = selectedSite || hoverSite;

  return (
    <div style={{ fontFamily: "'Georgia', 'Times New Roman', serif", background: CREAM, minHeight: "100%", color: INK, display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "16px 24px 14px", borderBottom: `3px solid ${GOLD}`, background: "#FFFFFF" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 2 }}>
          <img src="/logo.png" alt="Turner Mining Group" style={{ height: 34, width: "auto", display: "block" }} />
          <div style={{ borderLeft: "2px solid #D8D7D2", paddingLeft: 14, fontFamily: "system-ui, sans-serif" }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: NAVY, letterSpacing: 1, textTransform: "uppercase" }}>
              Aggregate Intelligence Map
            </div>
          </div>
        </div>
        <div style={{ fontFamily: "system-ui, sans-serif", fontSize: 13, color: "#6B655A", marginTop: 4 }}>
          {intentMode
            ? `Intent signals only — ${totals.count} sites with active findings across ${activeCompanies.size} compan${activeCompanies.size === 1 ? "y" : "ies"}`
            : `${totals.count} active sites (${totals.shown} circles shown, nearby same-company sites grouped) · ${totals.growing} growing · ${totals.declining} declining · ~${totals.employees.toLocaleString()} employees`}
        </div>
        <div style={{ fontFamily: "system-ui, sans-serif", fontSize: 11.5, color: "#9A9382", marginTop: 3, display: "flex", alignItems: "center", gap: 8 }}>
          {sfSync.state === "loading" && <span>Syncing Salesforce… ({sfSync.synced}/{sfSync.total})</span>}
          {sfSync.state === "done" && <span>Salesforce synced · {Object.keys(sfStatus).length} contacts matched</span>}
          {sfSync.state === "error" && <span style={{ color: "#B0453E" }}>Salesforce sync failed — showing Apollo data ({sfSync.error})</span>}
          {sfSync.state === "idle" && (
            <span onClick={syncSalesforce} style={{ color: GOLD, cursor: "pointer", fontWeight: 600 }}>
              Sync Salesforce
            </span>
          )}
          {sfSync.state !== "loading" && sfSync.state !== "idle" && (
            <span onClick={syncSalesforce} style={{ color: GOLD, cursor: "pointer", fontWeight: 600 }}>
              Refresh
            </span>
          )}
        </div>
      </div>

      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {/* Left: company filters */}
        <div style={{ width: 220, borderRight: "1px solid #D8D7D2", padding: "16px 14px", overflowY: "auto", fontFamily: "system-ui, sans-serif" }}>
          <div
            onClick={toggleAll}
            style={{ cursor: "pointer", fontSize: 12, fontWeight: 600, color: GOLD, marginBottom: 10, userSelect: "none" }}
          >
            {activeCompanies.size === COMPANIES.length ? "Clear all" : "Select all"}
          </div>

          <div
            onClick={toggleIntentMode}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "8px 8px",
              marginBottom: 14,
              borderRadius: 4,
              cursor: "pointer",
              background: intentMode ? NAVY : "#E4E3DF",
              color: intentMode ? "#FFFFFF" : INK,
              fontSize: 12.5,
              fontWeight: 600,
            }}
          >
            <span>Intent signals only</span>
            <span style={{ fontSize: 11, opacity: 0.85 }}>{intentMode ? "On" : "Off"}</span>
          </div>

          {COMPANIES.map((c) => {
            const on = activeCompanies.has(c);
            const n = intentMode ? signalCountByCompany[c] || 0 : SITES.filter((s) => s.company === c).length;
            const dim = intentMode && n === 0;
            const manuallyPicked = intentMode && hasManualIntentPick && on;
            return (
              <div
                key={c}
                onClick={() => toggleCompany(c)}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "6px 8px",
                  marginBottom: 2,
                  borderRadius: 4,
                  cursor: "pointer",
                  background: manuallyPicked ? GOLD : on && !dim ? "#E4E3DF" : "transparent",
                  color: manuallyPicked ? "#FFFFFF" : dim ? "#C9C2B2" : on ? INK : "#A39C8C",
                  fontWeight: manuallyPicked ? 700 : 400,
                  fontSize: 13,
                }}
              >
                <span>{c}</span>
                <span style={{ fontSize: 11, color: manuallyPicked ? "#FFFFFF" : dim ? "#D8D3C8" : "#9A9382" }}>{n}</span>
              </div>
            );
          })}

          <div style={{ marginTop: 22, fontSize: 12, fontWeight: 600, color: NAVY, marginBottom: 8 }}>
            Headcount trend
          </div>
          {Object.entries(TREND_COLOR).map(([k, v]) => (
            <div key={k} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, marginBottom: 5, color: "#4A453B", textTransform: "capitalize" }}>
              <span style={{ width: 10, height: 10, borderRadius: "50%", background: v, display: "inline-block" }} />
              {k}
            </div>
          ))}
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, marginTop: 10, color: "#4A453B" }}>
            <span style={{ width: 14, height: 14, borderRadius: "50%", border: `1.3px solid ${GOLD}`, display: "inline-block" }} />
            Site-level insight available
          </div>
        </div>

        {/* Center: map */}
        <div style={{ flex: 1, position: "relative", padding: 12, minWidth: 0 }}>
          <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block", boxShadow: "0 1px 4px rgba(31,56,100,0.10)", borderRadius: 3 }}>
            <rect x={0} y={0} width={W} height={H} fill="#EAEAE7" stroke="#C7C6C1" strokeWidth={1.2} />
            {Object.entries(STATE_PATHS).map(([abbr, d]) => (
              <path
                key={abbr}
                d={d}
                fill={(stateSiteCounts[abbr] || 0) > 0 ? "#F5F5F3" : "#E4E3DF"}
                stroke="#BFBEB9"
                strokeWidth={0.7}
              />
            ))}
            {Object.entries(STATE_CENTROIDS).map(([abbr, [x, y]]) => {
              const n = stateSiteCounts[abbr] || 0;
              return (
                <text
                  key={abbr}
                  x={x}
                  y={y}
                  fontSize={9}
                  fontFamily="system-ui, sans-serif"
                  fill={n > 0 ? "#B3AB96" : "#BFBEB9"}
                  textAnchor="middle"
                  style={{ pointerEvents: "none" }}
                >
                  {abbr}
                </text>
              );
            })}
            {visibleSites.map((s, i) => {
              const [x, y] = project(s.lat, s.lon);
              const r = Math.max(2.2, Math.min(9, Math.sqrt(s.employees || 3) * 1.1));
              const isSel = selectedSite && selectedSite.mine_id === s.mine_id;
              const hasNews = (s.news && s.news.length) || (s.isCluster && s.members.some((m) => m.news && m.news.length));
              return (
                <g key={s.mine_id + i}>
                  {hasNews && (
                    <circle
                      cx={x}
                      cy={y}
                      r={r + 4}
                      fill="none"
                      stroke={GOLD}
                      strokeWidth={1.3}
                      style={{ pointerEvents: "none" }}
                    />
                  )}
                  <circle
                    cx={x}
                    cy={y}
                    r={isSel ? r + 2 : r}
                    fill={TREND_COLOR[s.trend_class]}
                    fillOpacity={isSel ? 1 : 0.72}
                    stroke={isSel ? NAVY : "#FFFFFF"}
                    strokeWidth={isSel ? 1.5 : 0.6}
                    style={{ cursor: "pointer" }}
                    onMouseEnter={() => setHoverSite(s)}
                    onMouseLeave={() => setHoverSite(null)}
                    onClick={() => { setSelectedSite(s); setShowAllContacts(false); }}
                  />
                </g>
              );
            })}
          </svg>
          <div style={{ position: "absolute", bottom: 20, left: 24, fontFamily: "system-ui, sans-serif", fontSize: 11, color: "#B3AC9C" }}>
            Dot size ≈ site headcount · continental US only (1 Puerto Rico site not shown)
          </div>
        </div>

        {/* Right: detail panel */}
        <div style={{ width: 320, borderLeft: "1px solid #D8D7D2", padding: "16px 16px", overflowY: "auto", fontFamily: "system-ui, sans-serif" }}>
          {!displaySite && (
            <div style={{ fontSize: 13, color: "#9A9382", marginTop: 40, textAlign: "center" }}>
              Click a site on the map to see its detail and nearby contacts.
            </div>
          )}
          {displaySite && (
            <div>
              <div style={{ fontSize: 11, color: GOLD, fontWeight: 600 }}>{displaySite.company}</div>
              <div style={{ fontSize: 17, fontWeight: 700, color: NAVY, marginTop: 2, fontFamily: "Georgia, serif" }}>
                {displaySite.isCluster ? `${displaySite.members.length} nearby sites` : displaySite.name}
              </div>
              <div style={{ fontSize: 12, color: "#6B655A", marginTop: 2 }}>
                {displaySite.isCluster
                  ? Array.from(new Set(displaySite.members.map((m) => m.state))).join(", ")
                  : `${displaySite.county ? displaySite.county + " County, " : ""}${displaySite.state}`}
              </div>

              {displaySite.isCluster ? (
                <>
                  <div style={{ marginTop: 12, fontSize: 12, color: "#6B655A" }}>
                    Combined {displaySite.employees.toLocaleString()} employees across {displaySite.members.length} sites. Zoomed in on the map to keep dense areas legible — individual sites below.
                  </div>
                  <div style={{ marginTop: 10 }}>
                    {displaySite.members.map((m, i) => (
                      <div key={i} style={{ padding: "7px 0", borderBottom: "1px solid #F0EDE5" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, fontWeight: 600 }}>
                          <span>{m.name}{m.news && m.news.length ? " \u2726" : ""}</span>
                          <span style={{ width: 8, height: 8, borderRadius: "50%", background: TREND_COLOR[m.trend_class], display: "inline-block", marginTop: 3 }} />
                        </div>
                        <div style={{ fontSize: 11, color: "#9A9382" }}>
                          {m.county ? `${m.county} County, ` : ""}{m.state} · {m.employees ?? "—"} employees · {fmtPct(m.trend_last3)}
                        </div>
                        {m.news && m.news.map((n, ni) => <NewsCard key={ni} news={n} compact />)}
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 14 }}>
                    <Stat label="Employees" value={displaySite.employees ?? "\u2014"} />
                    <Stat label="Off peak" value={fmtPct(displaySite.pct_off_peak)} />
                    <Stat label="3yr trend" value={fmtPct(displaySite.trend_last3)} />
                    <Stat label="Type" value={displaySite.mine_type || "\u2014"} />
                  </div>
                  <div style={{ marginTop: 10, fontSize: 12, color: "#6B655A" }}>
                    {displaySite.material || "\u2014"}{displaySite.portable ? " \u00b7 portable equipment" : ""}
                  </div>
                  {displaySite.news && displaySite.news.map((n, i) => <NewsCard key={i} news={n} />)}
                </>
              )}

              <div style={{ marginTop: 20, fontSize: 12, fontWeight: 600, color: NAVY, borderTop: "1px solid #D8D7D2", paddingTop: 12 }}>
                Contacts near {displaySite.isCluster ? Array.from(new Set(displaySite.members.map((m) => m.state))).join("/") : displaySite.state} ({selectedSite ? selectedStateContacts.length : "click to load"})
              </div>
              <div style={{ fontSize: 10.5, color: "#9A9382", marginTop: 2 }}>
                Tier 1 reaches 2 states out, Tier 2 reaches 1 state out, Tier 3 is this state only
              </div>
              {selectedSite &&
                (selectedStateContacts.length === 0 ? (
                  <div style={{ fontSize: 12, color: "#B3AC9C", marginTop: 8 }}>No contacts on file in this state yet.</div>
                ) : (
                  (() => {
                    const TOP_N = 5;
                    const top = selectedStateContacts.slice(0, TOP_N);
                    const rest = selectedStateContacts.slice(TOP_N);
                    const restByTier = ["Tier 1", "Tier 2", "Tier 3"].map((tier) => ({
                      tier,
                      list: rest.filter((c) => c.tier === tier),
                    })).filter((g) => g.list.length > 0);
                    return (
                      <div>
                        <div style={{ marginTop: 10 }}>
                          <div style={{ fontSize: 10.5, fontWeight: 600, color: GOLD, textTransform: "uppercase", letterSpacing: 0.4 }}>
                            Best matches
                          </div>
                          <div style={{ fontSize: 10, color: "#B3AC9C", marginTop: 1, marginBottom: 4 }}>
                            Ranked on proximity, tier, and title fit — site/area roles lead over broad corporate titles
                          </div>
                          {top.map((c, i) => (
                            <ContactRow key={i} c={c} sf={sfStatus[c.email]} />
                          ))}
                        </div>
                        {rest.length > 0 && (
                          <div style={{ marginTop: 10 }}>
                            <div
                              onClick={() => setShowAllContacts((v) => !v)}
                              style={{ fontSize: 11.5, color: GOLD, cursor: "pointer", fontWeight: 600 }}
                            >
                              {showAllContacts ? "Hide" : `Show ${rest.length} more contact${rest.length === 1 ? "" : "s"} in reach`}
                            </div>
                            {showAllContacts &&
                              restByTier.map(({ tier, list }) => (
                                <div key={tier} style={{ marginTop: 10 }}>
                                  <div style={{ fontSize: 10.5, fontWeight: 600, color: GOLD, textTransform: "uppercase", letterSpacing: 0.4 }}>
                                    {TIER_LABEL[tier]}
                                  </div>
                                  {list.map((c, i) => (
                                    <ContactRow key={i} c={c} sf={sfStatus[c.email]} />
                                  ))}
                                </div>
                              ))}
                          </div>
                        )}
                      </div>
                    );
                  })()
                ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function NewsCard({ news, compact }) {
  const [expanded, setExpanded] = useState(!compact);
  return (
    <div
      onClick={compact ? () => setExpanded((e) => !e) : undefined}
      style={{
        marginTop: compact ? 6 : 14,
        padding: compact ? "8px 10px" : "10px 12px",
        background: "#FBF8F1",
        border: "1px solid #E7DCC4",
        borderRadius: 4,
        cursor: compact ? "pointer" : "default",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div style={{ fontSize: 10, color: "#9A9382" }}>{news.date}</div>
        {compact && (
          <div style={{ fontSize: 10, color: "#8A6D2E" }}>{expanded ? "Collapse \u2212" : "Expand +"}</div>
        )}
      </div>
      <div style={{ fontSize: compact ? 12 : 13, fontWeight: 700, color: "#4A3B1F", marginTop: 2 }}>
        {news.headline}
      </div>
      {expanded && (
        <>
          <div style={{ fontSize: 12, color: "#4A453B", marginTop: 6, lineHeight: 1.45 }}>{news.summary}</div>
          <div style={{ fontSize: 11.5, color: "#8A6D2E", marginTop: 8, fontStyle: "italic" }}>
            {news.sales_angle}
          </div>
          <a
            href={news.source}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            style={{ fontSize: 11, color: "#8A6D2E", marginTop: 6, display: "inline-block", textDecoration: "underline" }}
          >
            Read the source article →
          </a>
        </>
      )}
    </div>
  );
}
function ContactRow({ c, sf }) {
  const [open, setOpen] = useState(false);
  const hasDetail = c.email || c.mobile || c.work_phone || c.linkedin;
  return (
    <div
      onClick={() => hasDetail && setOpen((o) => !o)}
      style={{ padding: "7px 0", borderBottom: "1px solid #F0EDE5", cursor: hasDetail ? "pointer" : "default" }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div style={{ fontSize: 13, fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}>
          {c.first_name} {c.last_name}
          <span style={{ fontSize: 9, fontWeight: 700, color: "#8A6D2E", background: "#F0E9D6", borderRadius: 3, padding: "1px 4px" }}>
            {c.tier === "Tier 1" ? "T1" : c.tier === "Tier 2" ? "T2" : "T3"}
          </span>
        </div>
        {hasDetail && <div style={{ fontSize: 10, color: GOLD }}>{open ? "\u2212" : "+"}</div>}
      </div>
      <div style={{ fontSize: 11.5, color: "#6B655A" }}>{c.title}</div>
      <div style={{ fontSize: 11, color: "#9A9382", marginTop: 1, display: "flex", gap: 6, alignItems: "center" }}>
        <span>{c.company}</span>
        <span>· {c.state}</span>
        {sf ? (
          <>
            {sf.outbound && <Badge text="Outbound" color="#1F3864" />}
            {sf.stage && <Badge text={sf.stage} color="#3E7A4C" />}
          </>
        ) : (
          <>
            {c.replied && <Badge text="Replied" color="#3E7A4C" />}
            {!c.replied && c.email_sent && <Badge text="Sent" color="#9A9382" />}
          </>
        )}
      </div>
      {open && (
        <div style={{ marginTop: 6, padding: "8px 10px", background: "#F7F5EE", borderRadius: 4, fontSize: 11.5 }}>
          <div style={{ fontSize: 10, color: "#B3AC9C", marginBottom: 5 }}>
            {sf ? "Live from Salesforce" : "From Apollo (last sync)"}
          </div>
          {c.email && (
            <div style={{ marginBottom: 4 }}>
              <span style={{ color: "#9A9382" }}>Email </span>
              <a href={`mailto:${c.email}`} onClick={(e) => e.stopPropagation()} style={{ color: NAVY }}>
                {c.email}
              </a>
            </div>
          )}
          {c.mobile && (
            <div style={{ marginBottom: 4 }}>
              <span style={{ color: "#9A9382" }}>Mobile </span>
              <a href={`tel:${c.mobile}`} onClick={(e) => e.stopPropagation()} style={{ color: NAVY }}>
                {c.mobile}
              </a>
            </div>
          )}
          {c.work_phone && (
            <div style={{ marginBottom: 4 }}>
              <span style={{ color: "#9A9382" }}>Work </span>
              <a href={`tel:${c.work_phone}`} onClick={(e) => e.stopPropagation()} style={{ color: NAVY }}>
                {c.work_phone}
              </a>
            </div>
          )}
          {c.linkedin && (
            <div>
              <a
                href={c.linkedin}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                style={{ color: NAVY, textDecoration: "underline" }}
              >
                LinkedIn profile →
              </a>
            </div>
          )}
        </div>
      )}
      {!hasDetail && <div style={{ fontSize: 10.5, color: "#C9C2B2", marginTop: 3 }}>No contact details on file</div>}
    </div>
  );
}
function Stat({ label, value }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: "#9A9382", textTransform: "uppercase", letterSpacing: 0.3 }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 700, color: "#2A2A28" }}>{value}</div>
    </div>
  );
}
function Badge({ text, color }) {
  return (
    <span style={{ fontSize: 9.5, color: "#fff", background: color, borderRadius: 3, padding: "1px 5px" }}>
      {text}
    </span>
  );
}

// Data loader: fetches the four JSON files from /data/ at runtime instead of
// bundling them into the JS build. This means updating the site/contact/news
// data later is just replacing those JSON files (public/data/*.json) and
// redeploying — no rebuild of app logic needed, and diffs stay clean.
export default function AggregateMap() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetch("/data/sites.json").then((r) => {
        if (!r.ok) throw new Error(`sites.json: ${r.status}`);
        return r.json();
      }),
      fetch("/data/contacts.json").then((r) => {
        if (!r.ok) throw new Error(`contacts.json: ${r.status}`);
        return r.json();
      }),
      fetch("/data/state-centroids.json").then((r) => {
        if (!r.ok) throw new Error(`state-centroids.json: ${r.status}`);
        return r.json();
      }),
      fetch("/data/state-paths.json").then((r) => {
        if (!r.ok) throw new Error(`state-paths.json: ${r.status}`);
        return r.json();
      }),
    ])
      .then(([sites, contacts, centroids, paths]) => {
        if (cancelled) return;
        setData({ SITES: sites, CONTACTS: contacts, STATE_CENTROIDS: centroids, STATE_PATHS: paths });
      })
      .catch((err) => {
        if (!cancelled) setError(String(err && err.message ? err.message : err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div style={{ padding: 40, fontFamily: "system-ui, sans-serif", color: "#B0453E" }}>
        Failed to load map data: {error}. Check that the /data/*.json files deployed correctly.
      </div>
    );
  }
  if (!data) {
    return (
      <div style={{ padding: 40, fontFamily: "system-ui, sans-serif", color: "#6B655A" }}>
        Loading TMG Aggregate Intelligence Map…
      </div>
    );
  }
  return (
    <Dashboard
      SITES={data.SITES}
      CONTACTS={data.CONTACTS}
      STATE_CENTROIDS={data.STATE_CENTROIDS}
      STATE_PATHS={data.STATE_PATHS}
    />
  );
}
