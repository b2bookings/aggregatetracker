"""Turn site events, news and engagement into a ranked priority queue.

Every signal has a stable id, a point value and a date; points decay with age.
  site score    = sum of that site's decayed signals
  account score = best site + 30% of the next four + decayed company news
  contact score = engagement (reply, open, recent Salesforce activity)
                  + half the score of the best flagged site they can reach

A flag is "new" when it carries a signal id that has never appeared in the
queue before (pipeline/state/flag_history.json). The digest step emails new
flags; the UI badges them.
"""
from datetime import datetime, timezone

import config
from util import load_json, now_iso, parse_date, save_json

HISTORY_FILE = config.STATE_DIR / "flag_history.json"
EVENTS_FILE = config.STATE_DIR / "site_events.json"
MSHA_HALF_LIFE_DAYS = 60
SITE_FLAG_MIN = 15
TOP_SITES_PER_ACCOUNT = 5
CONTACTS_PER_SITE = 3

TIER_HOPS = {"Tier 1": 2, "Tier 2": 1, "Tier 3": 0}
DEMOTE = ["excellence", "technology", "talent", "golf", "marketing", "finance", "analyst",
          "coordinator", "recruit", "human resources", " hr ", "it manager"]
PROMOTE = ["general manager", "plant manager", "quarry manager", "site manager", "operations manager",
           "regional manager", "area manager", "district manager", "vice president operations",
           "vp operations", "president"]

EVENT_TEXT = {
    "new_site": lambda e: f"New site on MSHA record ({e.get('status')})",
    "controller_change": lambda e: f"Ownership changed - controller now {e.get('controller')}",
    "status_change": lambda e: f"MSHA status changed to {e.get('status')}",
    "ramp_up": lambda e: f"Hours up {e.get('trend'):+.0f}% year over year ({e.get('employees')} employees)",
    "slowdown": lambda e: f"Hours down {e.get('trend'):+.0f}% year over year",
}


def _event_points(e):
    t = e["type"]
    if t == "ramp_up":
        return 20 + min(e.get("trend") or 0, 100) / 10
    if t == "status_change":
        return {"New Mine": 30, "Active": 25, "Temporarily Idled": 15}.get(e.get("status"), 10)
    return {"new_site": 30, "controller_change": 30, "slowdown": 10}.get(t, 5)


def _decay(points, when, half_life, now):
    d = parse_date(when)
    if not d:
        return points * 0.5
    age = max((now - d).days, 0)
    return points * 0.5 ** (age / half_life)


def _hops(a, b):
    if a == b:
        return 0
    seen, frontier = {a}, [a]
    for h in (1, 2):
        frontier = [n for s in frontier for n in config.STATE_ADJACENCY.get(s, []) if n not in seen]
        seen.update(frontier)
        if b in seen:
            return h
    return 3


def _title_signal(title):
    t = " " + (title or "").lower() + " "
    if any(k in t for k in DEMOTE):
        return -3
    if any(k in t for k in PROMOTE):
        return 2
    return 0


def _contact_fit(contact, site):
    hops = _hops(site["state"], contact.get("state"))
    if contact.get("company") != site["company"] or hops > TIER_HOPS.get(contact.get("tier"), 0):
        return None
    return (3 - hops) + (1 if contact.get("tier") == "Tier 1" else 3) + _title_signal(contact.get("title"))


def _reason(rid, rtype, text, date, points, **extra):
    return {"id": rid, "type": rtype, "text": text, "date": date, "points": round(points, 1), **extra}


def run():
    now = datetime.now(timezone.utc)
    stamp = now_iso()
    sites = load_json(config.SITES_FILE, [])
    contacts = load_json(config.CONTACTS_FILE, [])
    company_news = load_json(config.COMPANY_NEWS_FILE, {})
    events = load_json(EVENTS_FILE, {})
    history = load_json(HISTORY_FILE, {})
    by_id = {s["mine_id"]: s for s in sites}

    # Site-level signals.
    site_reasons = {}
    for e in events.values():
        site = by_id.get(e["mine_id"])
        if not site and e["type"] not in ("status_change", "controller_change"):
            continue
        pts = _event_points(e)
        if site and site.get("portable"):
            pts *= 0.3  # portable plants move around; a "new" one is rarely a new pit
        # Quarterly metrics only become knowable when MSHA publishes them, so
        # they age from when we first saw them rather than the quarter end.
        when = e.get("first_seen") if e["type"] in ("ramp_up", "slowdown") else e.get("date")
        pts = _decay(pts, when, MSHA_HALF_LIFE_DAYS, now)
        site_reasons.setdefault(e["mine_id"], []).append(
            _reason(e["id"], e["type"], EVENT_TEXT.get(e["type"], lambda _: e["type"])(e), e.get("date"), pts))
    for s in sites:
        for n in s.get("news") or []:
            pts = _decay((n.get("strength") or 2.5) * 10, n.get("date") or n.get("first_seen"), config.NEWS_HALF_LIFE_DAYS, now)
            site_reasons.setdefault(s["mine_id"], []).append(
                _reason("news:" + (n.get("source") or n.get("headline", "")), "news", n.get("headline"), n.get("date"), pts,
                        source=n.get("source"), sales_angle=n.get("sales_angle")))

    flagged_sites = []
    for mid, reasons in site_reasons.items():
        score = sum(r["points"] for r in reasons)
        site = by_id.get(mid)
        if score < SITE_FLAG_MIN or not site:
            continue
        reasons.sort(key=lambda r: -r["points"])
        flagged_sites.append({"mine_id": mid, "name": site["name"], "company": site["company"], "state": site["state"],
                              "county": site.get("county"), "score": round(score, 1), "reasons": reasons})
    flagged_sites.sort(key=lambda s: -s["score"])

    # Recommended contacts per flagged site.
    for fs in flagged_sites:
        site = by_id[fs["mine_id"]]
        ranked = sorted(((fit, c) for c in contacts if (fit := _contact_fit(c, site)) is not None), key=lambda x: -x[0])
        fs["contacts"] = [c["email"] for _, c in ranked[:CONTACTS_PER_SITE] if c.get("email")]

    # Accounts.
    accounts = []
    for company in config.TARGETS:
        mine = [s for s in flagged_sites if s["company"] == company]
        news_reasons = []
        for n in company_news.get(company, []):
            pts = _decay((n.get("strength") or 2.5) * 8, n.get("date") or n.get("first_seen"), config.NEWS_HALF_LIFE_DAYS, now)
            news_reasons.append(_reason("cnews:" + (n.get("source") or n.get("headline", "")), "company_news",
                                        n.get("headline"), n.get("date"), pts, source=n.get("source"),
                                        sales_angle=n.get("sales_angle")))
        site_part = (mine[0]["score"] + 0.3 * sum(s["score"] for s in mine[1:TOP_SITES_PER_ACCOUNT])) if mine else 0
        score = site_part + sum(r["points"] for r in news_reasons)
        if score <= 0:
            continue
        news_reasons = sorted((r for r in news_reasons if r["points"] >= 1), key=lambda r: -r["points"])
        accounts.append({"company": company, "score": round(score, 1), "flagged_site_count": len(mine),
                         "sites": mine[:TOP_SITES_PER_ACCOUNT], "company_news": news_reasons[:5]})
    accounts.sort(key=lambda a: -a["score"])

    # Contacts.
    best_site_for = {}
    for fs in flagged_sites:
        for email in fs["contacts"]:
            if email not in best_site_for or best_site_for[email]["score"] < fs["score"]:
                best_site_for[email] = fs
    contact_flags = []
    for c in contacts:
        email = c.get("email")
        reasons = []
        if c.get("replied"):
            reasons.append(_reason(f"reply:{email}", "replied", "Replied to outreach", None, 40))
        elif c.get("email_open"):
            reasons.append(_reason(f"open:{email}", "opened", "Opened outreach email", None, 10))
        last = (c.get("sf") or {}).get("last_activity")
        if last:
            pts = _decay(10, last, 14, now)
            if pts >= 2:
                reasons.append(_reason(f"sfact:{email}:{last}", "sf_activity", f"Salesforce activity {last}", last, pts))
        fs = best_site_for.get(email)
        if fs:
            reasons.append(_reason(f"site:{email}:{fs['mine_id']}", "site_signal",
                                   f"Best-placed contact for {fs['name']} ({fs['state']}) - {fs['reasons'][0]['text']}",
                                   fs["reasons"][0]["date"], fs["score"] * 0.5))
        if not reasons:
            continue
        contact_flags.append({
            "email": email, "name": f"{c.get('first_name', '')} {c.get('last_name', '')}".strip(),
            "title": c.get("title"), "company": c.get("company"), "tier": c.get("tier"), "state": c.get("state"),
            "linkedin": c.get("linkedin"), "sf_id": (c.get("sf") or {}).get("id"),
            "linked_site": fs["mine_id"] if fs else None,
            "score": round(sum(r["points"] for r in reasons), 1), "reasons": reasons,
        })
    contact_flags.sort(key=lambda c: -c["score"])

    accounts = accounts[: config.PRIORITY_TOP_N]
    contact_flags = contact_flags[: config.PRIORITY_TOP_N]

    # Newness: a flag is new if any of its signal ids is appearing for the first time.
    def mark(flag, reason_lists):
        new = False
        firsts = []
        for reasons in reason_lists:
            for r in reasons:
                if r["id"] not in history:
                    history[r["id"]] = stamp
                    new = True
                r["first_flagged"] = history[r["id"]]
                firsts.append(history[r["id"]])
        flag["first_flagged"] = min(firsts) if firsts else stamp
        flag["latest_signal_at"] = max(firsts) if firsts else stamp
        flag["is_new"] = new

    for a in accounts:
        mark(a, [s["reasons"] for s in a["sites"]] + [a["company_news"]])
    for c in contact_flags:
        mark(c, [c["reasons"]])

    save_json(HISTORY_FILE, history, indent=1)
    save_json(config.PRIORITY_FILE, {"generated_at": stamp, "accounts": accounts, "contacts": contact_flags}, indent=1)
    print(f"  {len(accounts)} accounts, {len(flagged_sites)} flagged sites, {len(contact_flags)} contacts "
          f"({sum(a['is_new'] for a in accounts)} accounts / {sum(c['is_new'] for c in contact_flags)} contacts with new signals)")
    return {"priority_generated_at": stamp}
