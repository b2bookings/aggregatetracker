"""Rebuild sites.json from MSHA open data and record site-level events.

MSHA republishes Mines.zip and MinesProdQuarterly.zip every week. A mine is
attributed to a target company by its current controller (see config.TARGETS).

Metrics (per mine, summed across subunits):
  employees     average employee count in the latest complete quarter
  trend_last3   % change in hours worked, last 3 quarters vs. the same 3
                quarters a year earlier (year over year, so quarry seasonality
                cancels out)
  pct_off_peak  trailing-4-quarter hours vs. the best trailing-4-quarter
                stretch since 2010
  trend_class   growing / flat / declining / unknown from trend_last3

Events (written to pipeline/state/site_events.json, consumed by priority.py)
are dated by MSHA's own dates, so a first run doesn't flood the queue with
stale changes.
"""
import io
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta

import config
from util import load_json, now_iso, save_json

EVENTS_FILE = config.STATE_DIR / "site_events.json"
EVENT_WINDOW_DAYS = 180


def _download(name, cache_dir):
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / name
    if not dest.exists():
        print(f"  downloading {name}")
        urllib.request.urlretrieve(config.MSHA_BASE + name, dest)
    return dest


def _rows(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        member = next(n for n in z.namelist() if n.lower().endswith(".txt"))
        with z.open(member) as raw:
            header = None
            for line in io.TextIOWrapper(raw, encoding="latin-1"):
                parts = [p.strip().strip('"') for p in line.rstrip("\r\n").split("|")]
                if header is None:
                    header = parts
                    continue
                yield dict(zip(header, parts))


def _norm(s):
    return " ".join((s or "").lower().split())


def _msha_date(s):
    try:
        return datetime.strptime(s, "%m/%d/%Y").date()
    except (TypeError, ValueError):
        return None


def _qidx(year, qtr):
    return year * 4 + (qtr - 1)


def _qlabel(idx):
    return f"{idx // 4} Q{idx % 4 + 1}"


def _qend(idx):
    y, q = idx // 4, idx % 4 + 1
    return date(y, q * 3, 30 if q in (2, 3) else 31)


def _company_for_controller():
    lookup = {}
    for company, cfg in config.TARGETS.items():
        for c in cfg["controllers"]:
            lookup[_norm(c)] = company
    return lookup


def _material(r):
    canvass = r.get("PRIMARY_CANVASS") or ""
    return {"Sand & Gravel": "SandAndGravel", "Sand and Gravel": "SandAndGravel"}.get(canvass, canvass.replace(" ", "") or None)


def run(cache_dir):
    today = date.today()
    window_start = today - timedelta(days=EVENT_WINDOW_DAYS)
    controller_map = _company_for_controller()
    prev_sites = load_json(config.SITES_FILE, [])
    prev_by_id = {s["mine_id"]: s for s in prev_sites}

    mines_zip = _download("Mines.zip", cache_dir)
    prod_zip = _download("MinesProdQuarterly.zip", cache_dir)

    # 1. Target mines from the mine registry.
    mines = {}
    for r in _rows(mines_zip):
        if r.get("COAL_METAL_IND") != "M":
            continue
        company = controller_map.get(_norm(r.get("CURRENT_CONTROLLER_NAME")))
        if company:
            mines[r["MINE_ID"]] = (company, r)
    print(f"  {len(mines)} mines under target controllers")

    # 2. Quarterly hours/employees for those mines.
    hours = defaultdict(lambda: defaultdict(float))
    emps = defaultdict(lambda: defaultdict(float))
    for r in _rows(prod_zip):
        mid = r.get("MINE_ID")
        if mid not in mines:
            continue
        try:
            idx = _qidx(int(r["CAL_YR"]), int(r["CAL_QTR"]))
        except (KeyError, ValueError):
            continue
        hours[mid][idx] += float(r.get("HOURS_WORKED") or 0)
        emps[mid][idx] += float(r.get("AVG_EMPLOYEE_CNT") or 0)

    # Latest *complete* quarter: the newest quarter where reporting mines are
    # at least 80% of the quarter before (MSHA backfills late filers).
    reporting = defaultdict(int)
    for per_q in hours.values():
        for idx in per_q:
            reporting[idx] += 1
    latest = max(reporting)
    while latest - 1 in reporting and reporting[latest] < 0.8 * reporting[latest - 1]:
        latest -= 1
    print(f"  latest complete quarter: {_qlabel(latest)}")

    events = load_json(EVENTS_FILE, {})
    seen_at = now_iso()

    def add_event(eid, **payload):
        if eid not in events:
            events[eid] = {"id": eid, "first_seen": seen_at, **payload}

    sites = []
    for mid, (company, r) in mines.items():
        site_id = mid.lstrip("0")
        status = r.get("CURRENT_MINE_STATUS")
        status_dt = _msha_date(r.get("CURRENT_STATUS_DT"))
        ctrl_dt = _msha_date(r.get("CURRENT_CONTROLLER_BEGIN_DT"))
        base = {"company": company, "mine_id": site_id, "name": (r.get("CURRENT_MINE_NAME") or "").strip(), "state": r.get("STATE")}

        if status_dt and status_dt >= window_start and status in ("New Mine", "Active", "Temporarily Idled", "Abandoned", "NonProducing"):
            add_event(f"status:{site_id}:{status}:{status_dt}", type="status_change", status=status, date=str(status_dt), **base)
        if ctrl_dt and ctrl_dt >= window_start:
            add_event(f"controller:{site_id}:{ctrl_dt}", type="controller_change", controller=r.get("CURRENT_CONTROLLER_NAME"), date=str(ctrl_dt), **base)

        if status not in config.KEEP_STATUSES:
            continue

        h = hours.get(mid, {})
        e = emps.get(mid, {})
        last3 = sum(h.get(latest - i, 0) for i in range(3))
        prior3 = sum(h.get(latest - 4 - i, 0) for i in range(3))
        if last3 == 0 and prior3 == 0:
            trend, trend_class = None, "unknown"
        elif prior3 == 0:
            trend, trend_class = None, "growing"
        else:
            trend = round((last3 - prior3) / prior3 * 100, 1)
            trend_class = "growing" if trend >= config.TREND_GROWING else "declining" if trend <= config.TREND_DECLINING else "flat"

        t4_now = sum(h.get(latest - i, 0) for i in range(4))
        start = _qidx(2010, 1)
        peak = max((sum(h.get(q - i, 0) for i in range(4)) for q in range(start + 3, latest + 1)), default=0)
        pct_off_peak = round((t4_now / peak - 1) * 100, 1) if peak else None
        employees = int(round(e.get(latest, 0) or e.get(latest - 1, 0)))

        try:
            lat, lon = float(r.get("LATITUDE")), float(r.get("LONGITUDE"))
        except (TypeError, ValueError):
            prev = prev_by_id.get(site_id, {})
            lat, lon = prev.get("lat"), prev.get("lon")
        if lon is not None and lon > 0:  # a handful of MSHA rows drop the minus sign
            lon = -lon

        site = {
            **base,
            "county": r.get("FIPS_CNTY_NM"),
            "mine_type": r.get("CURRENT_MINE_TYPE"),
            "material": _material(r),
            "operator": r.get("CURRENT_OPERATOR_NAME"),
            "status": status,
            "employees": employees,
            "pct_off_peak": pct_off_peak,
            "trend_last3": trend,
            "trend_class": trend_class,
            "lat": lat,
            "lon": lon,
            "portable": r.get("PORTABLE_OPERATION") == "Y",
        }
        if prev_by_id.get(site_id, {}).get("news"):
            site["news"] = prev_by_id[site_id]["news"]
        sites.append(site)

        qtag = _qlabel(latest).replace(" ", "")
        if site_id not in prev_by_id and prev_sites:
            add_event(f"new:{site_id}", type="new_site", status=status, date=str(status_dt or today), **base)
        if trend is not None and trend >= 25 and employees >= 10:
            add_event(f"ramp:{site_id}:{qtag}", type="ramp_up", trend=trend, employees=employees, date=str(_qend(latest)), **base)
        elif trend is not None and trend <= -40 and prior3 >= 10 * 520:  # ~10 people's worth of hours
            add_event(f"slowdown:{site_id}:{qtag}", type="slowdown", trend=trend, employees=employees, date=str(_qend(latest)), **base)

    sites.sort(key=lambda s: (s["company"], s["state"] or "", s["name"] or ""))
    # Prune events older than a year so the state file stays small.
    cutoff = str(today - timedelta(days=365))
    events = {k: v for k, v in events.items() if v.get("date", "9999") >= cutoff}

    save_json(config.SITES_FILE, sites)
    save_json(EVENTS_FILE, events, indent=1)
    dropped = len([s for s in prev_sites if s["mine_id"] not in {x["mine_id"] for x in sites}])
    print(f"  wrote {len(sites)} sites ({dropped} dropped since last build), {len(events)} tracked events")
    return {"latest_quarter": _qlabel(latest), "msha_refreshed_at": now_iso(), "site_count": len(sites)}
