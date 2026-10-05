# TMG Aggregate Intelligence Map

The interactive US map of aggregate sites, contacts and site-level signals
across the 13 target companies, plus a live **Priority Queue** of the
accounts and contacts to work right now.

## How it fits together

```
GitHub Actions (scheduled)            Netlify
┌──────────────────────────┐   push   ┌─────────────────────────────────┐
│ pipeline/run.py          │ ───────▶ │ static site (public/data/*.json)│
│  msha       weekly       │          │ /.netlify/functions/salesforce  │──▶ Salesforce
│  news       4x weekdays  │          └─────────────────────────────────┘
│  research   Mondays      │
│  salesforce 4x weekdays  │
│  priority   every run    │ ──▶ email digest (new flags + 7am summary)
└──────────────────────────┘
```

- `src/AggregateMap.jsx`: the app (map, filters, contact reach, Priority
  Queue, Salesforce actions).
- `public/data/*.json`: the content the app fetches at load. The pipeline
  rewrites `sites.json`, `company-news.json`, `contacts.json` (Salesforce
  status), `priority.json` and `meta.json`. `state-*.json` is static geography.
- `pipeline/`: the refresh pipeline (Python). `pipeline/state/` holds its
  memory between runs (events seen, articles seen, flag history) and is
  committed so each run picks up where the last left off.
- `netlify/functions/salesforce.mjs`: server-side Salesforce actions
  (lookup, log follow-up task, create lead).

### Pipeline steps

| Step | Source | What it does |
|---|---|---|
| `msha` | MSHA open data (Mines.zip, MinesProdQuarterly.zip) | Rebuilds every site under a target controller, recomputes headcount/hours trends, drops abandoned mines, records dated events: new sites, ownership changes, status changes, ramp-ups, slowdowns |
| `news` | Serper (Google News), past week | Company queries + 40 rotating site queries per run. Gemini triages each new snippet (relevant? which site? strength 1-5, sales angle); anything scoring 3+ is re-checked against the full article before it's stored |
| `research` | Gemini + Google Search, last 14 days | Weekly per-company research for permits, rezoning and planning agendas, earnings-call site mentions and other signals news search misses. Links that don't exist are dropped; findings then go through the same triage and full-article check |
| `salesforce` | Salesforce REST API | Pulls owner, last activity and engagement fields for every tracked contact |
| `priority` | everything above | Scores sites, accounts and contacts with time decay, marks flags carrying never-seen signals as new |
| `digest` | priority.json | Emails new flags above the score threshold; the 7am run sends a full summary |

Metric definitions: **YoY hours** is hours worked in the last 3 complete
quarters vs. the same 3 quarters a year earlier (seasonality cancels out);
**Off peak** is trailing-4-quarter hours vs. the best stretch since 2010.

Each run appends its token, search and query counts with an estimated cost
to `pipeline/state/cost_log.json` (prices in `config.MODEL_PRICES`); the
latest run and month-to-date totals also land in `public/data/meta.json`.

The same event reported by several outlets is stored once, with the other
links under `also_reported_by`. Items whose link is a homepage or data portal
are tagged **Check source** in the app and score one point lower.

Tuning lives in `pipeline/config.py` (companies, controller names, news
terms, thresholds, model ids: `TRIAGE_MODEL`, `RESEARCH_MODEL`) and the point values at the top of `pipeline/priority.py`.

## Setup

### 1. GitHub Actions secrets

Repo → Settings → Secrets and variables → Actions.

| Secret | Needed for |
|---|---|
| `GEMINI_API_KEY` | news triage, full-article checks, weekly research (Google AI Studio → Get API key; enable billing for paid-tier limits) |
| `SERPER_API_KEY` | news search (serper.dev) |
| `ANTHROPIC_API_KEY` | optional: only if the `LLM_PROVIDER` variable is set to `anthropic` |
| `SF_LOGIN_URL`, `SF_CLIENT_ID`, `SF_CLIENT_SECRET` | Salesforce sync (connected app with client-credentials flow; e.g. `https://yourorg.my.salesforce.com`) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `DIGEST_TO`, `DIGEST_FROM` | email digest (Google Workspace: `smtp.gmail.com`, port 587, an app password) |

Variables (same page, Variables tab): `SITE_URL` (link in the digest) and
optionally `SF_CONTACT_FIELDS` (default
`Outbound_Contact__c,Account.Engagement_Stage__c`).

Any step whose secrets are missing is skipped; the rest still run. Run it
by hand from the Actions tab → **Refresh tracker data** → Run workflow.

### 2. Netlify environment variables

Site settings → Environment variables: `SF_LOGIN_URL`, `SF_CLIENT_ID`,
`SF_CLIENT_SECRET`, `TRACKER_ACCESS_KEY` (any long random string; each
person enters it once in their browser via **Connect Salesforce**), and
optionally `SF_CONTACT_FIELDS`.

### 3. Salesforce connected app

Create a connected app with **Enable Client Credentials Flow**, assign a
"run as" integration user that can read Contacts/Leads/Accounts and create
Tasks and Leads, and use its consumer key/secret above.

## Running locally

```
npm install
npm run dev
```

Pipeline (Python 3.9+):

```
pip install -r pipeline/requirements.txt
python3 pipeline/run.py --steps msha,priority
```

Set the same environment variables locally to exercise news, Salesforce or
the digest.
