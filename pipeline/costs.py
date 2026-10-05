"""Per-run cost log (pipeline/state/cost_log.json).

Prices come from config.MODEL_PRICES and are estimates: they don't include
taxes, and the Serper rate depends on the credit pack bought. Gemini Google
Search is free for the first config.GEMINI_SEARCH_FREE_PER_MONTH requests in
a calendar month, so searches are only charged once the month's running
total (from this log) passes that allowance.
"""
import config
import llm
from util import load_json, now_iso, save_json

LOG_FILE = config.STATE_DIR / "cost_log.json"
KEEP_RUNS = 500


def record(steps):
    u = llm.usage
    if not u["models"] and not u["serper_queries"]:
        return None

    stamp = now_iso()
    month = stamp[:7]
    log = load_json(LOG_FILE, [])
    searches_before = sum(r.get("gemini_searches", 0) for r in log if r["at"].startswith(month))
    billable = max(0, searches_before + u["gemini_searches"] - config.GEMINI_SEARCH_FREE_PER_MONTH)
    billable = min(billable, u["gemini_searches"])

    model_cost = 0.0
    models = {}
    for name, m in u["models"].items():
        price = config.MODEL_PRICES.get(name)
        cost = (m["input_tokens"] * price["input"] + m["output_tokens"] * price["output"]) / 1e6 if price else None
        models[name] = {**m, "cost_usd": round(cost, 4) if cost is not None else None}
        model_cost += cost or 0

    search_cost = billable * config.GEMINI_SEARCH_PER_1K / 1000
    serper_cost = u["serper_queries"] * config.SERPER_PER_1K / 1000
    entry = {
        "at": stamp,
        "steps": steps,
        "models": models,
        "gemini_searches": u["gemini_searches"],
        "gemini_searches_billable": billable,
        "serper_queries": u["serper_queries"],
        "cost_usd": {
            "models": round(model_cost, 4),
            "gemini_search": round(search_cost, 4),
            "serper": round(serper_cost, 4),
            "total": round(model_cost + search_cost + serper_cost, 4),
        },
    }
    log.append(entry)
    save_json(LOG_FILE, log[-KEEP_RUNS:], indent=1)

    month_total = sum(r["cost_usd"]["total"] for r in log if r["at"].startswith(month))
    print(f"[cost] this run ~${entry['cost_usd']['total']:.3f} "
          f"(models ${model_cost:.3f}, search ${search_cost:.3f}, serper ${serper_cost:.3f}); "
          f"{month} so far ~${month_total:.2f}")
    for name, m in models.items():
        print(f"  {name}: {m['calls']} calls, {m['input_tokens']:,} in / {m['output_tokens']:,} out tokens")
    return {"last_run_cost_usd": entry["cost_usd"]["total"], "month_cost_usd": round(month_total, 2)}
