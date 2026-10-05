"""Scan news for target companies and sites, keep only real sales signals.

1. Search Serper's Google News endpoint (past week) with company-level
   queries plus a rotating batch of site-level queries.
2. Drop anything already seen (pipeline/state/seen_news.json).
3. Ask Claude to judge each new item: is it a genuine operational signal for
   that company's US aggregates/cement business, which site (if any) does it
   concern, how strong is it, and what is the sales angle for a contract
   mining provider.
4. Append relevant items to sites.json (site news) and company-news.json.

Requires SERPER_API_KEY and ANTHROPIC_API_KEY. Without them the step is
skipped and the rest of the pipeline still runs.
"""
import hashlib
import json
import os
import urllib.request
from datetime import timedelta

import config
from util import load_json, now_iso, parse_date, save_json

SEEN_FILE = config.STATE_DIR / "seen_news.json"
ROTATION_FILE = config.STATE_DIR / "site_rotation.json"
SEEN_RETENTION_DAYS = 120
CLASSIFY_BATCH = 15

SIGNAL_TYPES = ["expansion", "new_site", "acquisition", "divestiture", "permit", "capital_investment",
                "leadership_change", "closure_or_idling", "contract_award", "safety_incident", "other"]

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "integer"},
                    "relevant": {"type": "boolean"},
                    "company": {"type": "string"},
                    "mine_id": {"type": ["string", "null"]},
                    "signal_type": {"type": "string", "enum": SIGNAL_TYPES},
                    "strength": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
                    "headline": {"type": "string"},
                    "summary": {"type": "string"},
                    "sales_angle": {"type": "string"},
                    "event_date": {"type": ["string", "null"]},
                },
                "required": ["ref", "relevant", "company", "mine_id", "signal_type", "strength",
                             "headline", "summary", "sales_angle", "event_date"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You screen news for a sales team at Turner Mining Group, a contract mining services provider (drilling, loading, hauling, overburden removal, pit development) that sells to US aggregates, cement and lime producers.

For each article decide whether it is a genuine, recent operational signal about the named producer's US operations that would make a conversation with them timely: quarry or plant expansions, new sites, acquisitions or divestitures of sites, permits and zoning decisions, capital investment, leadership changes at the operating level, idling or closures, large contract awards, or serious safety events. Stock-price commentary, analyst ratings, earnings previews, unrelated companies that share a name, and non-US operations are not relevant.

When an article concerns a specific site, set mine_id to the matching site from the candidate list (match on name and place, not just company); otherwise null. strength is 1 (weak, generic) to 5 (concrete, near-term, directly creates demand for contract mining). headline is a short factual rewrite, summary is one or two sentences, sales_angle is one sentence on why and how to reach out now. event_date is YYYY-MM-DD if the article states or implies when it happened, else null. Return one entry per article, keyed by its ref."""


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


def _candidate_sites(sites, company, limit=400):
    rows = [f'{s["mine_id"]}: {s["name"]} ({s.get("county") or "?"} County, {s["state"]})' for s in sites if s["company"] == company]
    return "\n".join(rows[:limit])


def _classify(client, batch, sites):
    companies = sorted({b["company"] for b in batch})
    candidates = "\n\n".join(f"Sites for {c}:\n{_candidate_sites(sites, c)}" for c in companies)
    articles = "\n\n".join(
        f'ref {i}\ncompany searched: {b["company"]}\ntitle: {b.get("title")}\nsource: {b.get("source")}\ndate: {b.get("date")}\nsnippet: {b.get("snippet")}'
        for i, b in enumerate(batch)
    )
    response = client.beta.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": CLASSIFY_SCHEMA}},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"{candidates}\n\nArticles:\n\n{articles}"}],
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        print(f"  classification batch stopped: {response.stop_reason}")
        return []
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)["items"]


def run():
    serper_key = os.environ.get("SERPER_API_KEY")
    if not serper_key or not os.environ.get("ANTHROPIC_API_KEY"):
        print("  SERPER_API_KEY / ANTHROPIC_API_KEY not set - skipping news scan")
        return {}

    sites = load_json(config.SITES_FILE, [])
    company_news = load_json(config.COMPANY_NEWS_FILE, {})
    seen = load_json(SEEN_FILE, {})
    queries, rotation = _queries(sites)

    fresh = {}
    for q in queries:
        try:
            results = _serper(q["q"], serper_key)
        except Exception as err:  # one bad query shouldn't sink the run
            print(f"  search failed for {q['q']!r}: {err}")
            continue
        for item in results:
            k = _key(item)
            if k in seen or k in fresh:
                continue
            fresh[k] = {**item, "company": q["company"], "searched_mine_id": q["mine_id"]}
    print(f"  {len(queries)} queries, {len(fresh)} unseen articles")

    import anthropic  # only needed once keys are present

    client = anthropic.Anthropic()
    keys = list(fresh)
    by_id = {s["mine_id"]: s for s in sites}
    stamp = now_iso()
    added = 0
    for start in range(0, len(keys), CLASSIFY_BATCH):
        batch_keys = keys[start:start + CLASSIFY_BATCH]
        batch = [fresh[k] for k in batch_keys]
        try:
            verdicts = _classify(client, batch, sites)
        except (anthropic.APIError, json.JSONDecodeError, StopIteration) as err:
            print(f"  classification failed: {err}")
            continue  # leave these unseen so the next run retries them
        for v in verdicts:
            if not 0 <= v["ref"] < len(batch):
                continue
            k = batch_keys[v["ref"]]
            seen[k] = stamp
            if not v["relevant"]:
                continue
            src = batch[v["ref"]]
            entry = {
                "headline": v["headline"],
                "date": v["event_date"] or stamp[:10],
                "summary": v["summary"],
                "sales_angle": v["sales_angle"],
                "signal_type": v["signal_type"],
                "strength": v["strength"],
                "source": src.get("link"),
                "publisher": src.get("source"),
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

    cutoff = (parse_date(stamp) - timedelta(days=SEEN_RETENTION_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    save_json(config.SITES_FILE, sites)
    save_json(config.COMPANY_NEWS_FILE, company_news, indent=1)
    save_json(SEEN_FILE, seen)
    save_json(ROTATION_FILE, rotation)
    print(f"  added {added} relevant news items")
    return {"news_scanned_at": stamp}
