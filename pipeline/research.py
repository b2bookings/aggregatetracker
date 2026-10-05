"""Weekly deep research per target company (Gemini + Google Search).

General news search misses many of the best signals for a contract miner:
rezoning hearings, county planning agendas, state mining-permit notices,
and specific US sites named in earnings calls or investor decks. Once a week
Gemini searches for those per company. Every URL it returns is checked to
actually load (dropping invented links), and the findings then go through
the same triage, full-article verification and dedupe as the news scan.

Requires GEMINI_API_KEY.
"""
import urllib.error
import urllib.request
from datetime import date, timedelta

import config
import llm
import news
from util import now_iso

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "publisher": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD or empty"},
                    "snippet": {"type": "string", "description": "2-3 factual sentences from the source"},
                },
                "required": ["title", "url", "publisher", "date", "snippet"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

SYSTEM = """You are a research analyst for Turner Mining Group, a contract mining services provider (drilling, loading, hauling, overburden removal, pit development) that sells to US aggregates, cement and lime producers.

Use Google Search to find concrete, recent developments at the named company's US quarries, pits, cement and lime plants. Look specifically for:
- rezoning, conditional-use, special-use or mining-permit applications, hearings and decisions (county and city planning agendas, state environmental or mining agencies, local papers)
- new quarries, pit expansions, reserve additions, plant upgrades or kiln projects
- acquisitions or divestitures of specific sites
- specific US sites or capital projects named in earnings calls, investor presentations or SEC filings
- plant- or region-level leadership changes, idlings, closures, reopenings

Only report items published or dated within the window given, each backed by a specific source you actually found in this search session; never invent or guess a URL. Skip stock commentary, analyst ratings and non-US operations. Quality matters more than quantity: return an empty list if nothing qualifies."""


def _resolves(url):
    """Return a usable URL, or None when the link clearly doesn't exist.

    Many publishers block automated requests (401/403/429), so only a
    missing page (404/410) or an unreachable host counts as an invented link.
    """
    if not url.startswith("http"):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.geturl()
    except urllib.error.HTTPError as err:
        return None if err.code in (404, 410) else url
    except Exception:
        return None


def run():
    if not llm.available(grounded=True):
        print("  GEMINI_API_KEY not set - skipping research")
        return {}

    since = date.today() - timedelta(days=config.RESEARCH_LOOKBACK_DAYS)
    sites, company_news, seen = news.load_stores()
    found = []
    for company, cfg in config.TARGETS.items():
        site_names = ", ".join(sorted({s["name"] for s in sites if s["company"] == company})[:150])
        prompt = (f"Company: {company} (search terms: {', '.join(cfg['news_terms'])})\n"
                  f"Window: {since.isoformat()} to {date.today().isoformat()}\n"
                  f"Known US sites (for context; new sites count too): {site_names}")
        try:
            data, _ = llm.generate_json(SYSTEM, prompt, FINDINGS_SCHEMA, model=config.RESEARCH_MODEL,
                                        search=True)
        except Exception as err:
            print(f"  research failed for {company}: {err}")
            continue
        kept = 0
        for f in data["findings"]:
            url = _resolves(f["url"])
            if not url:
                continue
            found.append({"title": f["title"], "link": url, "source": f["publisher"], "date": f["date"],
                          "snippet": f["snippet"], "company": company, "found_by": "research"})
            kept += 1
        print(f"  {company}: {len(data['findings'])} findings, {kept} with working links")

    fresh = news.unseen(found, seen)
    stamp = now_iso()
    added = news.ingest(fresh, sites, company_news, seen, stamp)
    news.save_stores(sites, company_news, seen, stamp)
    print(f"  added {added} items from research")
    return {"research_ran_at": stamp}
