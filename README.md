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
| `news` | Serper (Google News), past week | Company queries + 40 rotating site queries per run; Claude keeps only genuine operational signals, matches them to a site, scores strength 1-5 and writes a sales angle |
| `salesforce` | Salesforce REST API | Pulls owner, last activity and engagement fields for every tracked contact |
| `priority` | everything above | Scores sites, accounts and contacts with time decay, marks flags carrying never-seen signals as new |
| `digest` | priority.json | Emails new flags above the score threshold; the 7am run sends a full summary |

Metric definitions: **YoY hours** is hours worked in the last 3 complete
quarters vs. the same 3 quarters a year earlier (seasonality cancels out);
**Off peak** is trailing-4-quarter hours vs. the best stretch since 2010.

Tuning lives in `pipeline/config.py` (companies, controller names, news
terms, thresholds) and the point values at the top of `pipeline/priority.py`.

## Setup

### 1. GitHub Actions secrets

Repo → Settings → Secrets and variables → Actions.

| Secret | Needed for |
|---|---|
| `ANTHROPIC_API_KEY` | news classification |
| `SERPER_API_KEY` | news search (serper.dev) |
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
