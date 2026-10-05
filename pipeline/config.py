"""Shared configuration for the data pipeline.

Edit TARGETS to add or remove companies. `controllers` must match MSHA's
CURRENT_CONTROLLER_NAME exactly (case-insensitive) - that is how a mine gets
attributed to a company. `news_terms` drive the company-level news queries.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "public" / "data"
STATE_DIR = ROOT / "pipeline" / "state"

SITES_FILE = DATA_DIR / "sites.json"
CONTACTS_FILE = DATA_DIR / "contacts.json"
COMPANY_NEWS_FILE = DATA_DIR / "company-news.json"
PRIORITY_FILE = DATA_DIR / "priority.json"
META_FILE = DATA_DIR / "meta.json"

MSHA_BASE = "https://arlweb.msha.gov/OpenGovernmentData/DataSets/"

TARGETS = {
    "Vulcan Materials": {"controllers": ["Vulcan Materials Company"], "news_terms": ['"Vulcan Materials"']},
    "CRH/Oldcastle": {"controllers": ["CRH PLC", "Trap Rock Industries Inc; CRH PLC"], "news_terms": ['"CRH" aggregates', '"Oldcastle"', '"CRH Americas"']},
    "Heidelberg Materials": {"controllers": ["Heidelberg Materials AG"], "news_terms": ['"Heidelberg Materials" North America']},
    "Amrize": {"controllers": ["Amrize Ltd", "Amrize South Central"], "news_terms": ['"Amrize"']},
    "Cemex": {"controllers": ["Cemex S A", "Cementir Holding; Cemex SA", "Cemex SA; Barron Collier Companies"], "news_terms": ['"Cemex" USA']},
    "Rogers Group": {"controllers": ["Rogers Group Inc", "Northwest Arkansas Quarries LLC; Rogers Group Inc"], "news_terms": ['"Rogers Group" quarry']},
    "Summit Materials": {"controllers": ["Summit Materials LLC"], "news_terms": ['"Summit Materials"']},
    "Quikrete": {"controllers": ["Quikrete Holdings Inc."], "news_terms": ['"Quikrete"']},
    "Carmeuse": {"controllers": ["Carmeuse Holding SA"], "news_terms": ['"Carmeuse"']},
    "CalPortland": {"controllers": ["Taiheiyo Cement Corp"], "news_terms": ['"CalPortland"']},
    "Eagle Materials": {"controllers": ["Eagle Materials Inc", "Eagle Materials Inc & Heidelberger Zement Ag"], "news_terms": ['"Eagle Materials"']},
    "Titan America": {"controllers": ["Titan Cement International S A", "Titan America S A"], "news_terms": ['"Titan America"']},
    "Buzzi Unicem": {"controllers": ["Buzzi S p A"], "news_terms": ['"Buzzi" cement USA']},
}

# Words appended to company news queries so results skew toward operational
# signals rather than stock-price chatter.
NEWS_SIGNAL_WORDS = "(quarry OR plant OR expansion OR acquisition OR permit OR investment OR pit OR mine OR kiln)"

# Mines in these MSHA statuses stay on the map. Anything else (Abandoned) is
# dropped, and the drop is recorded as a site event.
KEEP_STATUSES = {"Active", "Intermittent", "New Mine", "Temporarily Idled", "NonProducing"}

# Trend thresholds (% change, same three quarters year over year).
TREND_GROWING = 10.0
TREND_DECLINING = -10.0

# How many individual sites get a targeted news search per run. Sites rotate
# so every site is covered over time without hammering the news feed.
SITE_QUERIES_PER_RUN = 40

CLAUDE_MODEL = "claude-opus-5-5"

# Priority engine knobs.
PRIORITY_TOP_N = 40
NEWS_HALF_LIFE_DAYS = 21
DIGEST_MIN_SCORE = 40  # new flags at or above this score go in the email digest

# Geography - identical to the adjacency map in src/AggregateMap.jsx.
STATE_ADJACENCY = {
    "AL": ["FL", "GA", "MS", "TN"], "AZ": ["CA", "CO", "NV", "NM", "UT"],
    "AR": ["LA", "MS", "MO", "OK", "TN", "TX"], "CA": ["AZ", "NV", "OR"],
    "CO": ["AZ", "KS", "NE", "NM", "OK", "UT", "WY"], "CT": ["MA", "NY", "RI"],
    "DE": ["MD", "NJ", "PA"], "FL": ["AL", "GA"], "GA": ["AL", "FL", "NC", "SC", "TN"],
    "ID": ["MT", "NV", "OR", "UT", "WA", "WY"], "IL": ["IN", "IA", "KY", "MO", "WI"],
    "IN": ["IL", "KY", "MI", "OH"], "IA": ["IL", "MN", "MO", "NE", "SD", "WI"],
    "KS": ["CO", "MO", "NE", "OK"], "KY": ["IL", "IN", "MO", "OH", "TN", "VA", "WV"],
    "LA": ["AR", "MS", "TX"], "ME": ["NH"], "MD": ["DE", "PA", "VA", "WV", "DC"],
    "MA": ["CT", "NH", "NY", "RI", "VT"], "MI": ["IN", "OH", "WI"],
    "MN": ["IA", "ND", "SD", "WI"], "MS": ["AL", "AR", "LA", "TN"],
    "MO": ["AR", "IL", "IA", "KS", "KY", "NE", "OK", "TN"], "MT": ["ID", "ND", "SD", "WY"],
    "NE": ["CO", "IA", "KS", "MO", "SD", "WY"], "NV": ["AZ", "CA", "ID", "OR", "UT"],
    "NH": ["ME", "MA", "VT"], "NJ": ["DE", "NY", "PA"], "NM": ["AZ", "CO", "OK", "TX", "UT"],
    "NY": ["CT", "MA", "NJ", "PA", "VT"], "NC": ["GA", "SC", "TN", "VA"],
    "ND": ["MN", "MT", "SD"], "OH": ["IN", "KY", "MI", "PA", "WV"],
    "OK": ["AR", "CO", "KS", "MO", "NM", "TX"], "OR": ["CA", "ID", "NV", "WA"],
    "PA": ["DE", "MD", "NJ", "NY", "OH", "WV"], "RI": ["CT", "MA"], "SC": ["GA", "NC"],
    "SD": ["IA", "MN", "MT", "ND", "NE", "WY"], "TN": ["AL", "AR", "GA", "KY", "MS", "MO", "NC", "VA"],
    "TX": ["AR", "LA", "NM", "OK"], "UT": ["AZ", "CO", "ID", "NV", "NM", "WY"],
    "VT": ["MA", "NH", "NY"], "VA": ["KY", "MD", "NC", "TN", "WV", "DC"],
    "WA": ["ID", "OR"], "WV": ["KY", "MD", "OH", "PA", "VA"], "WI": ["IL", "IA", "MI", "MN"],
    "WY": ["CO", "ID", "MT", "NE", "SD", "UT"], "DC": ["MD", "VA"],
}
