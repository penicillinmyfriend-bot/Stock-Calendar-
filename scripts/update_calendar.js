#!/usr/bin/env node
/*
 * Stock Calendar — update routine.
 *
 * Trigger word: "Calendar"  (see .claude/skills/calendar/SKILL.md)
 *
 * What it does:
 *   1. Reads every unprocessed file in ./import/ (*.md, *.txt).
 *   2. Extracts events (tickers, dates, IPOs, earnings, catalysts) via the
 *      shared parser, computes stable ids, dedupes, and merges them into
 *      data/calendar-events.json — NEVER overwriting manual events.
 *   3. Optionally refreshes live market data when API keys are configured.
 *   4. Moves processed files to ./import/processed/.
 *   5. Logs a short summary of what was added / updated / filtered.
 *
 * Run:  node scripts/update_calendar.js
 * Usage flags:
 *   --dry-run   parse & report, but do not write the store or move files
 */
"use strict";

const fs = require("fs");
const path = require("path");
const parse = require("./lib/parse.js");
const { fetchLiveEvents } = require("./lib/providers.js");

const ROOT = path.resolve(__dirname, "..");
const DATA_FILE = path.join(ROOT, "data", "calendar-events.json");
const IMPORT_DIR = path.join(ROOT, "import");
const PROCESSED_DIR = path.join(IMPORT_DIR, "processed");

const DRY_RUN = process.argv.includes("--dry-run");

function log(...args) {
  console.log(...args);
}

function loadConfig() {
  const local = path.join(ROOT, "config.local.json");
  const example = path.join(ROOT, "config.example.json");
  for (const file of [local, example]) {
    if (fs.existsSync(file)) {
      try {
        const cfg = JSON.parse(fs.readFileSync(file, "utf8"));
        if (file === example) {
          log("• No config.local.json found — using config.example.json defaults.");
        }
        return cfg;
      } catch (err) {
        log(`! Could not parse ${path.basename(file)}: ${err.message}`);
      }
    }
  }
  log("• No config file found — using built-in defaults (MIN_IPO_PRICE=10).");
  return { MIN_IPO_PRICE: 10, trackedTickers: [] };
}

function loadStore() {
  if (!fs.existsSync(DATA_FILE)) {
    return { version: 1, updatedAt: null, events: [] };
  }
  try {
    const raw = JSON.parse(fs.readFileSync(DATA_FILE, "utf8"));
    if (Array.isArray(raw)) return { version: 1, updatedAt: null, events: raw };
    raw.events = Array.isArray(raw.events) ? raw.events : [];
    return raw;
  } catch (err) {
    log(`! Could not parse ${DATA_FILE}: ${err.message}. Starting fresh.`);
    return { version: 1, updatedAt: null, events: [] };
  }
}

function saveStore(store) {
  store.updatedAt = new Date().toISOString();
  store.events = parse.sortEvents(store.events);
  fs.mkdirSync(path.dirname(DATA_FILE), { recursive: true });
  fs.writeFileSync(DATA_FILE, JSON.stringify(store, null, 2) + "\n", "utf8");
}

function listImportFiles() {
  if (!fs.existsSync(IMPORT_DIR)) return [];
  return fs
    .readdirSync(IMPORT_DIR, { withFileTypes: true })
    .filter((d) => d.isFile() && /\.(md|txt)$/i.test(d.name))
    .map((d) => d.name)
    .sort();
}

function moveToProcessed(filename) {
  fs.mkdirSync(PROCESSED_DIR, { recursive: true });
  let target = path.join(PROCESSED_DIR, filename);
  // Avoid clobbering an existing processed file with the same name.
  if (fs.existsSync(target)) {
    const ext = path.extname(filename);
    const base = path.basename(filename, ext);
    target = path.join(PROCESSED_DIR, `${base}.${Date.now()}${ext}`);
  }
  fs.renameSync(path.join(IMPORT_DIR, filename), target);
  return path.relative(ROOT, target);
}

async function main() {
  log("┌─ Stock Calendar update routine" + (DRY_RUN ? " (dry run)" : ""));

  const config = loadConfig();
  const minIpo = config.MIN_IPO_PRICE != null ? config.MIN_IPO_PRICE : 10;
  const store = loadStore();
  const startCount = store.events.length;

  let totalAdded = 0;
  let totalUpdated = 0;
  let totalSkippedManual = 0;
  let ipoBelowMin = 0;
  const processedFiles = [];

  const countBelowMin = (events) =>
    events.filter(
      (e) => e.type === "ipo" && e.expectedPrice != null && e.expectedPrice < minIpo
    ).length;

  // --- 1 & 2: parse import files ------------------------------------------
  const files = listImportFiles();
  if (files.length === 0) {
    log("• No new files in ./import/ to process.");
  }

  for (const filename of files) {
    const full = path.join(IMPORT_DIR, filename);
    const text = fs.readFileSync(full, "utf8");
    const sourceRef = path.posix.join("import", filename);

    const parsed = parse.extractEvents(text, {
      source: "chat",
      sourceRef,
      config,
    });

    // Below-threshold IPOs are KEPT in the store (never deleted) but counted so
    // the summary is honest; the UI hides them by default and can reveal them.
    ipoBelowMin += countBelowMin(parsed);

    const result = parse.mergeEvents(store.events, parsed, { preserveManual: true });
    store.events = result.events;
    totalAdded += result.added;
    totalUpdated += result.updated;
    totalSkippedManual += result.skippedManual;

    log(
      `• Parsed ${filename}: +${result.added} added, ${result.updated} updated` +
        (result.skippedManual ? `, ${result.skippedManual} manual kept` : "")
    );

    if (!DRY_RUN) {
      const dest = moveToProcessed(filename);
      processedFiles.push(dest);
    } else {
      processedFiles.push(sourceRef + " (not moved — dry run)");
    }
  }

  // --- 3: optional live data ----------------------------------------------
  try {
    const live = await fetchLiveEvents(config, log);
    if (live.length) {
      ipoBelowMin += countBelowMin(live);
      const result = parse.mergeEvents(store.events, live, { preserveManual: true });
      store.events = result.events;
      totalAdded += result.added;
      totalUpdated += result.updated;
      totalSkippedManual += result.skippedManual;
      log(`• Live data: +${result.added} added, ${result.updated} updated.`);
    }
  } catch (err) {
    log(`• Live data skipped: ${err.message}`);
  }

  // --- 4 & 5: persist + summarize -----------------------------------------
  if (!DRY_RUN) {
    saveStore(store);
  }

  log("├─ Summary");
  log(`│  events in store: ${startCount} → ${store.events.length}`);
  log(`│  added:   ${totalAdded}`);
  log(`│  updated: ${totalUpdated}`);
  log(`│  manual events preserved (untouched): ${totalSkippedManual}`);
  log(`│  IPOs below $${minIpo} (kept in store, hidden by default in UI): ${ipoBelowMin}`);
  if (processedFiles.length) {
    log(`│  files processed: ${processedFiles.length}`);
    processedFiles.forEach((f) => log(`│    → ${f}`));
  }
  log("└─ Done." + (DRY_RUN ? " (dry run — nothing written)" : ""));
}

main().catch((err) => {
  console.error("Update routine failed:", err);
  process.exit(1);
});
