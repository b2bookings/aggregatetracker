import json
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, data, indent=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


def parse_date(value):
    """Best-effort ISO date parse; returns an aware datetime or None."""
    if not value:
        return None
    value = str(value).strip()
    d = None
    try:
        d = datetime.fromisoformat(value)
    except ValueError:
        for fmt in ("%Y-%m", "%Y"):
            try:
                d = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
