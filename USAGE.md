# Stock Calendar — How to run & use it

A practical, step-by-step guide. For the feature overview and design notes, see
[`README.md`](README.md).

---

## 1. What you need

- **[Node.js](https://nodejs.org) 18 or newer** — for the update routine, the
  optional local server, and the tests. Check with:

  ```bash
  node --version
  ```

That's it. There are **no dependencies to install** (`npm install` is not
required) and **no backend/server-side code**.

---

## 2. Run it (3 ways)

The browser reads `data/calendar-events.json` with `fetch()`, which browsers
block on `file://`. So the recommended way is to serve the folder over HTTP —
this is still a static site, not a backend.

### A. Bundled static server (simplest)

```bash
node scripts/serve.js        # then open http://localhost:8080
# or choose a port:  node scripts/serve.js 3000
# or via npm:        npm run serve
```

### B. Any other static server

```bash
python3 -m http.server 8080      # http://localhost:8080
# or
npx serve .
```

### C. Open the file directly (no server)

Double-click `index.html` (opens as `file://…`). The app **still works**, but in
a degraded mode: it can't read/write the JSON file or auto-load config, so it
keeps a working copy in your browser's `localStorage` and shows a small notice.
Fine for a quick look; use A or B for the full experience.

> **First run:** the app loads the 13 sample events from
> `data/calendar-events.json` so you immediately see the Month and Upcoming views
> populated.

---

## 3. Everyday tasks

### Add an event
Click **➕ Add event** → fill in date, type, ticker (optional), title (auto-filled
if blank), notes, optional signal → **Save**. It's stored immediately and
survives reloads (saved in `localStorage`).

### Edit or delete an event
Click any event → the detail panel opens → **Edit** or **Delete**. Editing marks
the event as user-curated so the update routine will never overwrite it.

### Import events from a chat export
Two equivalent ways:

1. **In the app:** click **⤓ Update from chats** and pick `.md`/`.txt` files —
   or just **drag-and-drop** them anywhere on the window.
2. **From the terminal (canonical):** drop files into `./import/` and run the
   update routine (see §4). This writes the committed `data/calendar-events.json`.

### Filter what you see
- **Type chips** (IPO / Earnings / Catalyst / Custom) — click to toggle; each
  shows a live **count**.
- **Ticker** dropdown — focus on one symbol.
- **Show low-price IPOs** — reveals IPOs priced below `MIN_IPO_PRICE` (hidden by
  default).
- **Month / Upcoming** — switch between the grid and the week-grouped agenda.

### Export
**⤓ Export** menu:
- **Download JSON** — get a `calendar-events.json` to drop into `data/`.
- **Save JSON to file…** — write directly to disk (Chrome/Edge File System
  Access API; falls back to a download elsewhere).
- **Calendar file (.ics)** — subscribe to your events in Google / Apple /
  Outlook Calendar.

### Re-sync after editing the file
If you ran the update routine (or edited `data/calendar-events.json` by hand),
click **↻ Sync file** (or just reload) to pull those changes into the app —
your manually-added events are preserved.

---

## 4. The "Calendar" update routine

This is the engine that turns chat exports into calendar events.

```bash
node scripts/update_calendar.js          # ingest ./import/, merge the store
node scripts/update_calendar.js --dry-run  # preview only: nothing written/moved
# or:  npm run update
```

What it does, in order:
1. Reads every `.md`/`.txt` in `./import/`.
2. Extracts tickers, dates, IPOs, earnings, and catalysts; computes a stable
   `id`; **dedupes and merges** into `data/calendar-events.json` — **never**
   overwriting events whose `"source"` is `"manual"`.
3. Optionally pulls live market data if you configured API keys (§5).
4. Moves processed files into `./import/processed/`.
5. Prints a summary: added / updated / preserved / below-threshold / files.

### Trigger word
Sending a message containing the word **"Calendar"** runs this routine — it's
registered as a Claude Code skill in `.claude/skills/calendar/SKILL.md` (also
invokable as `/calendar`). The in-app **Update from chats** button runs the same
parser in the browser.

### Try it now
A sample export ships in `import/2026-06-10-chat.md`:

```bash
node scripts/update_calendar.js --dry-run
```

You'll see it find an ACME IPO, a TSLA earnings date, a jobs-report catalyst, a
BIIB FDA date, and a sub-$10 IPO flagged as hidden-by-default.

---

## 5. Configuration

Copy the template (the real file is gitignored, so your keys never get
committed):

```bash
cp config.example.json config.local.json
```

| Key | What it does |
|---|---|
| `MIN_IPO_PRICE` | IPOs priced below this (default **10**) are kept but hidden by default in the UI. |
| `trackedTickers` | Symbols used for earnings relevance and to seed the ticker filter. |
| `disclaimer` | Footer text. |
| `liveData.enabled` | Master switch for fetching live market data. |
| `providers.finnhub` / `providers.alphaVantage` | Set `enabled: true` and add an `apiKey` to pull live IPO/earnings data. Free keys: [Finnhub](https://finnhub.io), [Alpha Vantage](https://www.alphavantage.co). |

Live data is purely additive — with no keys, the app works fully offline from
the local JSON store.

---

## 6. What each file does

| Path | Role | Do you edit it? |
|---|---|---|
| `index.html` | App markup (header, toolbar, views, modal, panel). | Only to change structure. |
| `styles.css` | The green-and-white theme. | To restyle. |
| `app.js` | All UI logic: rendering, filtering, add/edit/delete, import, export, storage. | To change app behavior. |
| `data/calendar-events.json` | **The event store** — the single source of truth, git-friendly. Written by the update routine; read by the app. | Usually no — let the routine/app manage it (hand-editing is fine if you keep valid JSON). |
| `config.example.json` | Config template (committed). | Reference. |
| `config.local.json` | **Your** settings + API keys (gitignored). | **Yes** — your knobs live here. |
| `import/` | Drop chat exports (`.md`/`.txt`) here to be ingested. | **Yes** — you add files here. |
| `import/processed/` | Where the routine moves files after ingesting them (gitignored). | No — managed for you. |
| `scripts/update_calendar.js` | The "Calendar" update routine (parse → merge → move → log). | Rarely. |
| `scripts/serve.js` | Zero-dependency static server for local viewing. | No. |
| `scripts/lib/parse.js` | **Shared** parsing/merge logic used by both Node and the browser. | To tune extraction. |
| `scripts/lib/providers.js` | Pluggable live-data providers (Finnhub, Alpha Vantage). | To add a provider. |
| `scripts/parse.test.js` | Unit tests for the parser/merge logic. | When changing the parser. |
| `.claude/skills/calendar/SKILL.md` | Registers the **"Calendar"** trigger. | No. |
| `.github/workflows/ci.yml` | CI: runs the tests + a dry-run on push/PR. | No. |
| `package.json` | npm scripts (`update`, `serve`, `test`) and metadata. | Rarely. |

### How the data flows

```
   chat export (.md/.txt)                manual add / edit (in browser)
        │                                         │
        ▼                                         ▼
  ./import/  ──►  update_calendar.js  ──►  data/calendar-events.json  ◄── canonical store
                  (parse, dedupe,            │           ▲
                   merge, move)              │           │  Export (JSON / Save to file)
                                             ▼           │
                                      browser app (app.js)
                                   localStorage working copy
                                   merges file on load, never
                                   discarding manual events
```

The **Node routine is the authoritative writer** of the JSON file. The **browser
keeps a working copy** in `localStorage`, merges the file on load (so file-side
additions appear on reload while your manual events are preserved), and lets you
**Export** the merged result back to the file to commit.

---

## 7. Command reference

```bash
npm run serve     # static server at http://localhost:8080  (node scripts/serve.js)
npm run update    # ingest ./import/ and merge the store     (node scripts/update_calendar.js)
npm test          # run parser/merge unit tests              (node --test)

node scripts/update_calendar.js --dry-run   # preview an ingest without writing
node scripts/serve.js 3000                  # serve on a custom port
```

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| Calendar is empty / "No data server detected" notice | You opened `index.html` as a `file://`. Run a server (§2 A/B) so it can `fetch` the JSON. |
| Edits disappear after clearing browser data | The browser working copy lives in `localStorage`. Use **Export** to save them into `data/calendar-events.json` and commit. |
| A sub-$10 IPO isn't showing | That's by design — toggle **Show low-price IPOs**, or lower `MIN_IPO_PRICE`. |
| Live data isn't appearing | Set `liveData.enabled: true` and add a provider `apiKey` in `config.local.json`, then re-run the update routine. No keys = offline mode (expected). |
| A chat event wasn't picked up | Each event needs a **date** and a stock/macro cue (ticker, "IPO", "earnings", "FOMC", "FDA", …). Tip: one event per line/bullet parses most reliably. |
| `npm test` says it can't find a module | Use `npm test` (which runs `node --test`); passing a bare directory to `node --test` is interpreted as a script on some Node versions. |

---

## 9. A note on honesty

This tool **does not predict** prices. Events may carry an optional, clearly
labeled `signal` (positive / neutral / caution) derived only from concrete inputs
— it's a *signal, not a prediction* — and a disclaimer is always shown:
**For informational purposes only — not financial advice.**
