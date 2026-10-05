"""Scan news for target companies and sites, keep only real sales signals.

1. Search Serper's Google News endpoint (past week) with company-level
   queries plus a rotating batch of site-level queries.
2. Drop anything already seen (pipeline/state/seen_news.json).
3. Triage: the model reads each new item's title and snippet and decides
   whether it's a genuine operational signal, which site it concerns, how
   strong it is, and the sales angle for a contract mining provider.
4. Verify: items scoring VERIFY_MIN_STRENGTH or higher are re-checked
   against the full article (Gemini URL context) so the details that reach
   the queue and digest come from the article, not a two-line snippet.
5. Append relevant items to sites.json (site news) and company-news.json.

`ingest()` is shared with research.py, whose findings go through the same
triage, verification and dedupe.

Requires SERPER_API_KEY plus a model key (GEMINI_API_KEY by default).
"""
import hashlib
import json
import os
import urllib.request
from datetime import timedelta

import config
import llm
from util import load_json, now_iso, parse_date, save_json

SEEN_FILE = config.STATE_DIR / "seen_news.json"
ROTATION_FILE = config.STATE_DIR / "site_rotation.json"
SEEN_RETENTION_DAYS = 120
CLASSIFY_BATCH = 15

SIGNAL_TYPES = ["expansion", "new_site", "acquisition", "divestiture", "permit", "capital_investment",
                "leadership_change", "closure_or_idling", "contract_award", "safety_incident", "other"]

# Plain JSON Schema that both Gemini and Claude structured outputs accept.
# Empty string means "none" for mine_id / event_date.
VERDICT = {
    "type": "object",
    "properties": {
        "ref": {"type": "integer"},
        "relevant": {"type": "boolean"},
        "company": {"type": "string"},
        "mine_id": {"type": "string", "description": "matching site id from the candidate list, or empty"},
        "signal_type": {"type": "string", "enum": SIGNAL_TYPES},
        "strength": {"type": "integer", "description": "1 (weak) to 5 (concrete, near-term)"},
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "sales_angle": {"type": "string"},
        "event_date": {"type": "string", "description": "YYYY-MM-DD or empty"},
    },
    "required": ["ref", "relevant", "company", "mine_id", "signal_type", "strength",
                 "headline", "summary", "sales_angle", "event_date"],
    "additionalProperties": False,
}
CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": VERDICT}},
    "required": ["items"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You screen news for a sales team at Turner Mining Group, a contract mining services provider (drilling, loading, hauling, overburden removal, pit development) that sells to US aggregates, cement and lime producers.

For each article decide whether it is a genuine, recent operational signal about the named producer's US operations that would make a conversation with them timely: quarry or plant expansions, new sites, acquisitions or divestitures of sites, permits and zoning decisions, capital investment, leadership changes at the operating level, idling or closures, large contract awards, or serious safety events. Stock-price commentary, analyst ratings, earnings previews, unrelated companies that share a name, and non-US operations are not relevant.

When an article concerns a specific site, set mine_id to the matching site id from the candidate list (match on name and place, not just company); otherwise use an empty string. strength is 1 (weak, generic) to 5 (concrete, near-term, directly creates demand for contract mining). headline is a short factual rewrite, summary is one or two sentences, sales_angle is one sentence on why and how to reach out now. event_date is YYYY-MM-DD if the article states or implies when it happened, else an empty string. Return one entry per article, keyed by its ref."""

VERIFY_PROMPT = SYSTEM_PROMPT + """

You are now checking one item that an earlier pass judged from its headline and snippet only. Open the article URL and judge it from the full text. Correct anything the earlier pass got wrong: relevance, which site, whether something is proposed vs. approved vs. completed, the date, and the strength. If the article cannot be opened, keep the earlier judgment but lower strength by one. Use ref 0."""


def _key(item):
    basis = (item.get("link") or "") + "|" + (item.get("title") or "").lower()
    return hashlib.sha1(basis.encode()).hexdigest()[:16]


def _serper(query, api_key):
    req = urllib.request.Request(
        "https://google.serper.dev/news",
        data=json.dumps({"q": query, "gl": "us", "hl": "en", "tbs": "qdr:w", "num": 20}).encode(),
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp).get("news", [])


def _queries(sites):
    queries = []
    for company, cfg in config.TARGETS.items():
        for term in cfg["news_terms"]:
            queries.append({"q": f"{term} {config.NEWS_SIGNAL_WORDS}", "company": company, "mine_id": None})

    # Site-level queries rotate through every site, least recently searched first.
    rotation = load_json(ROTATION_FILE, {})
    ordered = sorted(sites, key=lambda s: rotation.get(s["mine_id"], ""))
    picked = ordered[: config.SITE_QUERIES_PER_RUN]
    stamp = now_iso()
    for s in picked:
        rotation[s["mine_id"]] = stamp
        place = s.get("county") or ""
        queries.append({"q": f'"{s["name"]}" {place} {s["state"]} quarry OR plant', "company": s["company"], "mine_id": s["mine_id"]})
    return queries, rotation


def candidate_sites(sites, company, limit=400):
    rows = [f'{s["mine_id"]}: {s["name"]} ({s.get("county") or "?"} County, {s["state"]})' for s in sites if s["company"] == company]
    return "\n".join(rows[:limit])


def _describe(i, b):
    return (f'ref {i}\ncompany searched: {b["company"]}\ntitle: {b.get("title")}\nurl: {b.get("link")}\n'
            f'source: {b.get("source")}\ndate: {b.get("date")}\nsnippet: {b.get("snippet")}')


def _triage(batch, sites):
    companies = sorted({b["company"] for b in batch})
    candidates = "\n\n".join(f"Sites for {c}:\n{candidate_sites(sites, c)}" for c in companies)
    articles = "\n\n".join(_describe(i, b) for i, b in enumerate(batch))
    data, _ = llm.generate_json(SYSTEM_PROMPT, f"{candidates}\n\nArticles:\n\n{articles}", CLASSIFY_SCHEMA,
                                model=config.TRIAGE_MODEL)
    return data["items"]


def _verify(item, verdict, sites):
    prompt = (f"Sites for {item['company']}:\n{candidate_sites(sites, item['company'])}\n\n"
              f"Article:\n{_describe(0, item)}\n\nEarlier judgment:\n{json.dumps({**verdict, 'ref': 0})}")
    data, _ = llm.generate_json(VERIFY_PROMPT, prompt, VERDICT, model=config.RESEARCH_MODEL, read_urls=True)
    return {**data, "ref": verdict["ref"], "verified": True}


def ingest(fresh, sites, company_news, seen, stamp):
    """Triage, verify and store `fresh` ({key: item}). Returns count added."""
    by_id = {s["mine_id"]: s for s in sites}
    keys = list(fresh)
    added = 0
    for start in range(0, len(keys), CLASSIFY_BATCH):
        batch_keys = keys[start:start + CLASSIFY_BATCH]
        batch = [fresh[k] for k in batch_keys]
        try:
            verdicts = _triage(batch, sites)
        except Exception as err:  # leave these unseen so the next run retries them
            print(f"  triage failed: {err}")
            continue
        for v in verdicts:
            if not 0 <= v["ref"] < len(batch):
                continue
            k = batch_keys[v["ref"]]
            src = batch[v["ref"]]
            seen[k] = stamp
            v["strength"] = max(1, min(5, int(v["strength"])))
            if v["relevant"] and v["strength"] >= config.VERIFY_MIN_STRENGTH and src.get("link") and llm.available(grounded=True):
                try:
                    v = _verify(src, v, sites)
                    v["strength"] = max(1, min(5, int(v["strength"])))
                except Exception as err:
                    print(f"  verification failed for {src.get('link')}: {err}")
            if not v["relevant"]:
                continue
            entry = {
                "headline": v["headline"],
                "date": v["event_date"] or stamp[:10],
                "summary": v["summary"],
                "sales_angle": v["sales_angle"],
                "signal_type": v["signal_type"],
                "strength": v["strength"],
                "verified": bool(v.get("verified")),
                "source": src.get("link"),
                "publisher": src.get("source"),
                "found_by": src.get("found_by", "news"),
                "first_seen": stamp,
            }
            site = by_id.get(v["mine_id"] or "")
            if site and site["company"] == v["company"]:
                site.setdefault("news", [])
                if not any(n.get("source") == entry["source"] for n in site["news"]):
                    site["news"].insert(0, {"site_match": site["name"], **entry})
                    added += 1
            elif v["company"] in config.TARGETS:
                bucket = company_news.setdefault(v["company"], [])
                if not any(n.get("source") == entry["source"] for n in bucket):
                    bucket.insert(0, entry)
                    added += 1
    return added


def load_stores():
    return (load_json(config.SITES_FILE, []), load_json(config.COMPANY_NEWS_FILE, {}), load_json(SEEN_FILE, {}))


def save_stores(sites, company_news, seen, stamp):
    cutoff = (parse_date(stamp) - timedelta(days=SEEN_RETENTION_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    save_json(config.SITES_FILE, sites)
    save_json(config.COMPANY_NEWS_FILE, company_news, indent=1)
    save_json(SEEN_FILE, seen)


def unseen(items, seen):
    out = {}
    for item in items:
        k = _key(item)
        if k not in seen and k not in out:
            out[k] = item
    return out


def run():
    serper_key = os.environ.get("SERPER_API_KEY")
    if not serper_key or not llm.available():
        print("  SERPER_API_KEY or model key not set - skipping news scan")
        return {}

    sites, company_news, seen = load_stores()
    queries, rotation = _queries(sites)
    found = []
    for q in queries:
        try:
            results = _serper(q["q"], serper_key)
        except Exception as err:  # one bad query shouldn't sink the run
            print(f"  search failed for {q['q']!r}: {err}")
            continue
        found += [{**item, "company": q["company"], "found_by": "news"} for item in results]
    fresh = unseen(found, seen)
    print(f"  {len(queries)} queries, {len(fresh)} unseen articles")

    stamp = now_iso()
    added = ingest(fresh, sites, company_news, seen, stamp)
    save_stores(sites, company_news, seen, stamp)
    save_json(ROTATION_FILE, rotation)
    print(f"  added {added} relevant news items")
    return {"news_scanned_at": stamp}
