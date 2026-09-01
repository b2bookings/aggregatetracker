# TMG Aggregate Intelligence Map

The interactive US map of active aggregate sites, contacts, and site-level
news across your 13 target companies.

## Architecture

This is a static React app (Vite), but the **data is separate from the
code**:

- `src/AggregateMap.jsx` — all the app logic (map rendering, filtering,
  tiered contact reach, clustering, intent-signal filtering, etc.). This
  almost never needs to change.
- `public/data/*.json` — the actual content: `sites.json` (1,250 MSHA sites),
  `contacts.json` (182 people), `state-centroids.json` and `state-paths.json`
  (map geography, essentially static). The app fetches these at load time.

This split means **updating the news/site/contact data is just replacing a
JSON file — not touching or rebuilding the app itself.**

## Deploying to Netlify

**Recommended: connect a GitHub repo (this folder is already a git repo,
ready to push).**

1. Create a new empty repo on GitHub.
2. From this folder:
   ```
   git remote add origin <your-repo-url>
   git branch -M main
   git push -u origin main
   ```
3. In Netlify: **Add new site → Import an existing project**, pick the repo.
   It'll auto-detect the build command (`npm run build`) and publish
   directory (`dist`) from `netlify.toml`.
4. Add your custom domain under Site settings → Domain management.

Every time you push a change to this repo (including just a data file),
Netlify rebuilds and redeploys automatically — usually within a minute or
two.

**Alternative: drag-and-drop (no Git, but manual every time)**
```
npm install
npm run build
```
Then drag the `dist/` folder to app.netlify.com/drop. You'd need to repeat
this full process for every future update, which defeats the point of the
data/code split above — the GitHub route is strongly recommended.

## How future research updates reach the live site

1. Run a research pass with Claude (the aggregate-intel-scan workflow, or
   ad hoc site-by-site scans).
2. Claude gives you an updated `sites.json` (or `contacts.json`, if contact
   data changed).
3. Replace the file in `public/data/` with the new one.
4. `git add public/data/sites.json && git commit -m "Update site news" && git push`
5. Netlify rebuilds automatically. Live within a couple minutes.

No code changes, no manual Netlify dashboard steps. Steps 3-4 are literally
just "swap a file and push" — doable even from GitHub's web UI (upload
file, commit) without a terminal, if that's easier.

### Ceiling on "live"

This is push-to-publish, not autonomous. Every update still starts with
someone asking Claude to run a research pass — there's no scheduled job
pulling fresh news on its own. That would require a recurring process
feeding a real backend the app polls, a meaningfully bigger build.

## Running locally

```
npm install
npm run dev
```
Opens at http://localhost:5173

## Known limitation: the "Sync Salesforce" button

Calls api.anthropic.com using Claude's MCP support for Salesforce, which
only works inside Claude's own artifact preview (Claude injects auth there
automatically). On your own domain that call has no credentials and will
fail — but it already falls back cleanly to the Apollo-based contact
badges, so this doesn't break anything. Making it actually work on your
domain would need a small backend (a Netlify Function is the natural fit)
holding a real Salesforce token, with the fetch in syncSalesforce() (in
AggregateMap.jsx) pointed there instead. A separate follow-on project.
