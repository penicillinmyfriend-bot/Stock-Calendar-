# 📈 Stock Calendar

A polished, **local-first** calendar that tracks stock-relevant events — upcoming
**IPOs**, **earnings** dates, and **catalysts** (FOMC, CPI, jobs reports,
ex-dividends, lock-up expirations, FDA dates, product launches, analyst days…).

Events come from two sources:

1. **Your chat / conversation exports** (primary) — drop `.md`/`.txt` files into
   `./import/` and run the update routine, which extracts tickers, dates, IPOs,
   earnings, and catalysts and merges them into a single JSON store.
2. **Optional live market data** (enhancement) — pluggable providers (Finnhub,
   Alpha Vantage, …). The app works **fully offline** from the local store; live
   data is never a dependency.

No backend, no build step. Vanilla HTML/CSS/JS plus a small Node routine.

> 📖 **New here? See [`USAGE.md`](USAGE.md)** for a step-by-step guide to running
> the app and what every file does.

> **For informational purposes only — not financial advice.** The app never
> claims a stock "will" move. Events may carry an optional, clearly-labeled
> `signal` (positive / neutral / caution) derived **only** from concrete inputs —
> it's a *signal, not a prediction*.

---

## Quick start

The app reads `data/calendar-events.json`. Browsers block `fetch()` from
`file://`, so serve the folder with any static file server (there is **no**
server-side code):

```bash
# Option A — the bundled zero-dependency server (Node 18+)
node scripts/serve.js          # → http://localhost:8080
# or: npm run serve

# Option B — anything else you already have
python3 -m http.server 8080
npx serve .
```

Then open **http://localhost:8080**.

> You *can* also open `index.html` directly via `file://`. It still runs, but it
> can't read/write the JSON file or auto-load config — it falls back to a working
> copy in your browser's `localStorage`. Serving the folder is recommended.

---

## The import workflow ("update from chats")

1. Export a conversation and save it as `./import/2026-06-10-chat.md` (or `.txt`).
   Tip: **one event per line / bullet** parses most reliably.
2. Run the update routine:

   ```bash
   node scripts/update_calendar.js
   # or: npm run update
   ```

3. The routine:
   - parses every unprocessed file in `./import/` for tickers, dates, IPO /
     earnings / catalyst mentions, and clearly-labeled signal cues;
   - computes a **stable id** per event and **dedupes / merges** into
     `data/calendar-events.json` — **manually-added events are never overwritten
     or deleted**;
   - optionally refreshes live data if API keys are configured (see below);
   - **moves processed files** to `./import/processed/`;
   - prints a short summary (added / updated / preserved / below-threshold).
4. Reload the app — the new events appear. (Click **Sync file** to re-read the
   store without a full reload.)

A sample export ships in `import/2026-06-10-chat.md`. Running the routine against
it adds an ACME IPO, a TSLA earnings date, a jobs-report catalyst, and a BIIB FDA
date, and flags one sub-$10 IPO as hidden-by-default. Try it:

```bash
node scripts/update_calendar.js --dry-run   # preview without writing/moving
```

### In the browser

The **"Update from chats"** button runs the **exact same parser**
(`scripts/lib/parse.js` is shared between Node and the browser). It opens a file
picker — or just **drag-and-drop** your `.md`/`.txt` exports anywhere on the
window — and they're parsed and merged into the in-browser store. Use **Export →
Download JSON / Save JSON to file…** to write the merged store back to
`calendar-events.json` (direct save via the File System Access API where
supported, otherwise a download) so you can commit it, or **Export → Calendar
file (.ics)** to subscribe in your calendar app.

---

## The "Calendar" trigger word

Sending a message containing the word **"Calendar"** runs the update routine.

This is registered as a Claude Code skill in
[`.claude/skills/calendar/SKILL.md`](.claude/skills/calendar/SKILL.md). When the
skill runs it executes `node scripts/update_calendar.js` and reports the summary.
You can also invoke it explicitly with `/calendar`.

> Example: you message **"Calendar"** → the routine scans `./import/`, finds the
> ACME mention, adds it (price ≥ $10), logs *"1 IPO added"*, and the UI shows it
> on reload.

To make the trigger fully automatic in your own environment, add a
`UserPromptSubmit` hook in `.claude/settings.json` that runs the script when the
prompt matches `/\bcalendar\b/i`.

---

## Configuration

Settings and secrets live in **`config.local.json`** (gitignored). Copy the
template to get started:

```bash
cp config.example.json config.local.json
```

```jsonc
{
  "MIN_IPO_PRICE": 10,                    // IPOs priced below this are hidden by default
  "trackedTickers": ["NVDA", "AAPL", ...],// used for earnings relevance + the ticker filter
  "disclaimer": "For informational purposes only — not financial advice.",
  "liveData": { "enabled": false, "ipoHorizonDays": 60, "earningsHorizonDays": 45 },
  "providers": {
    "finnhub":      { "enabled": false, "apiKey": "" },
    "alphaVantage": { "enabled": false, "apiKey": "" }
  }
}
```

- **API keys never leave `config.local.json`**, which is gitignored. The app is
  fully usable with no keys at all.
- `MIN_IPO_PRICE` (default **$10**): below-threshold IPOs are **kept in the
  store** but **hidden in the UI by default**. Toggle **"Show low-price IPOs"** to
  reveal them.

### Live data (optional)

Set a provider's `apiKey`, flip `enabled: true`, and set `liveData.enabled: true`.
On the next `update_calendar.js` run, live IPO/earnings events are fetched and
merged (graceful: if a key is missing or a request fails, it's skipped and the
local store is used). Free keys: [Finnhub](https://finnhub.io),
[Alpha Vantage](https://www.alphavantage.co). Add your own provider by extending
`scripts/lib/providers.js`.

---

## Honest signal framing

The app **does not predict** prices. For earnings/catalysts it may show an
optional `signal` badge:

- **positive / neutral / caution** — attached **only** from concrete, labeled
  inputs (e.g. an explicit analyst upgrade/downgrade in your chat, or live
  provider data). If there's no such input, **no badge is shown** — it is never
  guessed.
- Every signal is labeled *"signal, not a prediction."*
- A persistent footer reads: **"For informational purposes only — not financial
  advice."**

---

## Data model

Single source of truth: **`data/calendar-events.json`** (git-friendly).

```jsonc
{
  "id": "acme-ipo-2026-07-15",        // stable: slug of ticker + type + date
  "date": "2026-07-15",               // ISO; optional "endDate" for ranges
  "ticker": "ACME",                   // null for macro events
  "type": "ipo",                      // ipo | earnings | catalyst | custom
  "title": "ACME Corp IPO",
  "expectedPrice": 18.5,              // IPO only
  "notes": "From 6/10 chat — watching for cloud-infra exposure",
  "source": "chat",                   // chat | manual | api
  "sourceRef": "import/2026-06-10-chat.md",
  "signal": "neutral"                 // optional: positive | neutral | caution
}
```

Events are deduped on `id`; updates merge rather than duplicate; manual events
are always preserved.

---

## UI

- **Month grid** and **Upcoming agenda** (grouped by week, with relative-date
  hints like *“in 5 days”*) — toggle between them.
- Header: **Add event**, **Update from chats**, **Export**, **Sync file**.
- Filter **chips** by type (IPO / Earnings / Catalyst / Custom) with live
  **counts**, a **ticker** filter, and a **low-price IPO** toggle.
- Click any event → a detail panel with notes, source, signal, and **Edit /
  Delete** actions.
- **Add / edit modal** writes to the store (localStorage + Export to file).
  Editing an event marks it user-curated so the update routine won't overwrite it.
- **Drag-and-drop** `.md`/`.txt` chat exports anywhere on the window to import
  them (same parser as the Node routine).
- **Export** menu: download `calendar-events.json`, save it straight to disk
  (File System Access API), or export an **iCalendar `.ics`** feed to subscribe
  in Google / Apple / Outlook Calendar.
- Responsive (desktop & mobile), green-and-white theme, persistent disclaimer.

---

## Project structure

```
.
├── index.html                     # app shell
├── styles.css                     # green & white theme
├── app.js                         # UI + storage + in-browser import/export
├── data/calendar-events.json      # canonical event store (committed)
├── config.example.json            # config template (committed)
├── config.local.json              # your keys/settings (gitignored)
├── import/                        # drop chat exports here
│   └── processed/                 # routine moves processed files here
├── scripts/
│   ├── update_calendar.js         # the "Calendar" update routine
│   ├── serve.js                   # optional zero-dep static server
│   ├── parse.test.js              # tests (node --test)
│   └── lib/
│       ├── parse.js               # shared parsing/merge logic (Node + browser)
│       └── providers.js           # pluggable live-data providers
├── .claude/skills/calendar/SKILL.md   # "Calendar" trigger registration
└── .github/workflows/ci.yml           # CI: runs `node --test` on push / PR
```

---

## Scripts

```bash
npm run update     # node scripts/update_calendar.js  (ingest ./import/, merge store)
npm run serve      # node scripts/serve.js            (static server on :8080)
npm test           # node --test                      (parser/merge unit tests)
```

Requires **Node 18+** (uses the built-in `fetch` and test runner).

---

## License

MIT
