# Marketing Automation Dashboard (GoHighLevel → GitHub)

A static dashboard showing enrollment, opens, and clicks for the Onboarding/Operations,
Marketing, and DLF automations, refreshed automatically once a day.

## Why it works this way

GoHighLevel's public API does not expose a "who's enrolled in this workflow" endpoint
or per-workflow email open/click stats. The only reliable way to get these numbers is
via **tags**: each workflow already tags a contact on entry (per PJ), and a
tag can similarly be added when a contact opens or clicks an email, using GHL's built-in
**Email Events** workflow trigger (Opened / Clicked, filterable by campaign). See:
https://help.gohighlevel.com/support/solutions/articles/155000002678-workflow-trigger-email-events

So the data flow is:

1. GHL workflow tags contact on entry → `<campaign>-enrolled`
2. A companion trigger (Email Events: Opened, filtered to that campaign) tags → `<campaign>-opened`
3. Same for Clicked → `<campaign>-clicked`
4. This script counts contacts per tag via the Contacts API and writes `data/dashboard-data.json`
5. GitHub Actions runs the script daily and commits the updated file
6. `dashboard/index.html` (served via GitHub Pages) reads that file and renders it

## One-time setup

### 1. In GoHighLevel

- **Confirm/add the engagement tags.** For each of the 3 workflows, add (if not already
  present) two small companion triggers using GHL's "Email Events" workflow trigger:
  one filtered to `Opened` on that campaign's emails → action "Add Tag" `<campaign>-opened`,
  and one filtered to `Clicked` → `<campaign>-clicked`. You said enrollment tagging
  already exists — just confirm the exact tag names and put them in `config.json`.
- **Create a Private Integration Token** (Settings → Private Integrations in the
  relevant sub-account). Scopes needed: `contacts.readonly` (required),
  `workflows.readonly` (optional, only if you want workflow names pulled live instead
  of typed into config).
- **Grab your Location ID** (Settings → Business Info, or it's in the URL of your
  sub-account).

### 2. Edit `config.json`

Replace `locationId` and the placeholder tag names (`onboarding-enrolled`, etc.) with
the real tags used in your workflows.

### 3. Create the GitHub repo

- Create a new repo (public or private — Pages works either way, private repos need
  GitHub Pro/Team/Enterprise for Pages).
- Push all files in this folder to it.
- Go to **Settings → Secrets and variables → Actions** and add two repository secrets:
  - `GHL_TOKEN` — the Private Integration Token from step 1
  - `GHL_LOCATION_ID` — your GHL location ID
- Go to **Settings → Pages** and set Source to "GitHub Actions" (or "Deploy from branch:
  main /root" if you'd rather keep it simple — either works since `dashboard/index.html`
  is a static file).
- Go to the **Actions** tab and manually run "Refresh GHL dashboard data" once to
  generate the first real `data/dashboard-data.json` and confirm it works end to end.

### 4. Share the link

Once Pages is live, the dashboard is at:
`https://<your-username>.github.io/<repo-name>/dashboard/`

## Verify before trusting it on autopilot

The GoHighLevel OpenAPI spec for `/contacts/search` doesn't fully document its request
body in public docs (it just links to an internal ClickUp doc). The filter shape used
in `scripts/fetch_stats.py` — `filters: [{field, operator, value}]` — is the commonly
documented v2 pattern, but **run it once with `DEBUG=1` locally** and sanity-check the
raw response against a tag you can verify by eye in the GHL UI, before relying on the
daily schedule:

```bash
pip install -r requirements.txt
GHL_TOKEN=xxx GHL_LOCATION_ID=xxx DEBUG=1 python scripts/fetch_stats.py
```

To preview the dashboard with fake data (no GHL account needed):

```bash
MOCK=1 python scripts/fetch_stats.py
cd dashboard && python3 -m http.server 8000
# open http://localhost:8000
```

## Files

- `config.json` — campaign labels + the GHL tags mapped to each
- `scripts/fetch_stats.py` — pulls stats from GHL, writes `data/dashboard-data.json`
- `.github/workflows/refresh.yml` — runs the script daily and commits the result
- `dashboard/index.html` — the dashboard the marketing team looks at
- `data/dashboard-data.json` — the data file (seeded with sample data until the first
  real run)

## Limitations to know about

- **"Responded"**: standard email metrics are sent/delivered/opened/clicked/bounced.
  A true "reply" metric isn't standard for one-way marketing emails — if you want it,
  set up a similar Email Events-style trigger for replies (or a "Customer Replied"
  trigger) with its own tag, and fill in `repliedTag` in `config.json`.
- **Tag-based counting is a workaround**, not a native GHL reporting feature. If a
  contact is removed from a tag later, counts will shift. If you want it, we can
  switch to snapshotting counts daily instead of re-counting live tag membership.
- Rate limits: GHL allows 100 requests/10 sec per resource. Fine for 3 campaigns ×
  3-4 tags once a day.
