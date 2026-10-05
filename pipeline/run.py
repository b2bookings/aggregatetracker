"""Pipeline entry point.

  python pipeline/run.py                     # news + salesforce + priority + digest
  python pipeline/run.py --steps msha,priority
  python pipeline/run.py --steps research,priority   # weekly deep research
  python pipeline/run.py --digest summary    # morning summary instead of new-only

Each step merges what it reports into public/data/meta.json so the tracker
can show when each source last refreshed.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from util import load_json, save_json  # noqa: E402

ALL_STEPS = ["msha", "news", "research", "salesforce", "priority", "digest"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", default="news,salesforce,priority,digest",
                        help=f"comma-separated subset of {','.join(ALL_STEPS)}")
    parser.add_argument("--digest", default="new", choices=["new", "summary"])
    parser.add_argument("--cache", default=str(config.ROOT / "pipeline" / ".cache"),
                        help="where MSHA downloads are kept")
    args = parser.parse_args()

    meta = load_json(config.META_FILE, {})
    for step in [s.strip() for s in args.steps.split(",") if s.strip()]:
        print(f"[{step}]")
        if step == "msha":
            import msha
            meta.update(msha.run(Path(args.cache)))
        elif step == "news":
            import news
            meta.update(news.run())
        elif step == "research":
            import research
            meta.update(research.run())
        elif step == "salesforce":
            import salesforce
            meta.update(salesforce.run())
        elif step == "priority":
            import priority
            meta.update(priority.run())
        elif step == "digest":
            import digest
            digest.run(args.digest)
        else:
            parser.error(f"unknown step {step!r}")
    import costs
    meta.update(costs.record(args.steps) or {})
    save_json(config.META_FILE, meta, indent=1)


if __name__ == "__main__":
    main()
