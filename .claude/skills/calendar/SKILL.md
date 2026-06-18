---
name: calendar
description: Update the Stock Calendar from chat exports. Use this WHENEVER the user sends a message containing the word "Calendar", or asks to update/refresh/sync the calendar from chats or import new events. Runs scripts/update_calendar.js, which parses ./import/*.md|*.txt for tickers/dates/IPOs/earnings/catalysts, dedupes and merges them into data/calendar-events.json (never overwriting manual events), moves processed files into ./import/processed/, and optionally refreshes live market data when API keys are configured.
---

# Calendar — update from chats

When this skill runs, perform the Stock Calendar update routine.

## Steps

1. From the repository root, run the update routine:

   ```bash
   node scripts/update_calendar.js
   ```

2. Read the script's summary output (it prints how many events were added,
   updated, skipped, and which files were processed).

3. Report a short, honest summary back to the user, e.g.
   "1 IPO and 2 catalysts added, 1 below-threshold IPO filtered out,
   1 file processed." Do not claim any stock will go up — events carry an
   optional, clearly-labeled `signal` only when concrete data supports it.

4. If the routine reports that live-data providers were skipped because no API
   keys are configured, mention that this is expected and the app still works
   fully offline from the local JSON store.

## Notes

- The canonical data store is `data/calendar-events.json`. The routine is the
  authoritative writer of that file; the browser UI reflects changes on reload.
- Manually-added events (`"source": "manual"`) are never overwritten or deleted
  by this routine.
- IPOs priced below `MIN_IPO_PRICE` (config.local.json, default $10) are kept in
  the store but hidden by default in the UI.
- The trigger word is **"Calendar"** — any message containing it should run this
  routine. The UI's "Update from chats" button invokes the same parsing logic
  (shared via scripts/lib/parse.js) on files dropped into the browser.
