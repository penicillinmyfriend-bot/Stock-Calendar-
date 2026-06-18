/*
 * Pluggable live-data providers (optional enhancement).
 *
 * Every provider is graceful: if it is not enabled, has no API key, or the
 * network call fails, it logs a short note and returns []. The app NEVER
 * depends on live data — it is purely additive on top of the local JSON store.
 *
 * Each provider returns normalized event objects compatible with the store:
 *   { id, date, ticker, type, title, expectedPrice?, notes, source:'api', sourceRef, signal? }
 *
 * Node 18+ provides a global `fetch`.
 */
const { makeId } = require("./parse.js");

function daysFromNow(n) {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

async function safeFetchJSON(url) {
  if (typeof fetch !== "function") {
    throw new Error("global fetch unavailable (requires Node 18+)");
  }
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/* -------------------------------------------------------------------------- */
/* Finnhub — IPO calendar + earnings calendar                                  */
/* https://finnhub.io/docs/api                                                 */
/* -------------------------------------------------------------------------- */
async function finnhub(cfg, providerCfg, log) {
  const key = providerCfg.apiKey;
  if (!key) {
    log('  · finnhub: enabled but no apiKey set — skipping.');
    return [];
  }
  const events = [];
  const from = today();
  const ipoTo = daysFromNow(cfg.liveData?.ipoHorizonDays || 60);
  const earnTo = daysFromNow(cfg.liveData?.earningsHorizonDays || 45);

  // IPO calendar
  try {
    const data = await safeFetchJSON(
      `https://finnhub.io/api/v1/calendar/ipo?from=${from}&to=${ipoTo}&token=${key}`
    );
    for (const ipo of (data.ipoCalendar || [])) {
      const price = parsePriceRange(ipo.price);
      const ticker = (ipo.symbol || "").toUpperCase() || null;
      const ev = {
        date: ipo.date,
        ticker,
        type: "ipo",
        title: `${ipo.name || ticker || "Company"} IPO`,
        notes: [ipo.exchange, ipo.numberOfShares ? `${ipo.numberOfShares} shares` : null]
          .filter(Boolean)
          .join(" · "),
        source: "api",
        sourceRef: "https://finnhub.io (IPO calendar)",
      };
      if (price != null) ev.expectedPrice = price;
      ev.id = makeId(ev);
      if (ev.date) events.push(ev);
    }
    log(`  · finnhub IPO: ${events.length} entries fetched.`);
  } catch (err) {
    log(`  · finnhub IPO: skipped (${err.message}).`);
  }

  // Earnings calendar (filtered to tracked tickers to stay relevant)
  try {
    const before = events.length;
    const data = await safeFetchJSON(
      `https://finnhub.io/api/v1/calendar/earnings?from=${from}&to=${earnTo}&token=${key}`
    );
    const tracked = new Set((cfg.trackedTickers || []).map((t) => t.toUpperCase()));
    for (const e of (data.earningsCalendar || [])) {
      const ticker = (e.symbol || "").toUpperCase();
      if (tracked.size && !tracked.has(ticker)) continue;
      const ev = {
        date: e.date,
        ticker,
        type: "earnings",
        title: `${ticker} Earnings`,
        notes: [e.epsEstimate != null ? `EPS est ${e.epsEstimate}` : null, e.hour ? `(${e.hour})` : null]
          .filter(Boolean)
          .join(" "),
        source: "api",
        sourceRef: "https://finnhub.io (earnings calendar)",
      };
      ev.id = makeId(ev);
      if (ev.date && ticker) events.push(ev);
    }
    log(`  · finnhub earnings: ${events.length - before} tracked-ticker entries fetched.`);
  } catch (err) {
    log(`  · finnhub earnings: skipped (${err.message}).`);
  }

  return events;
}

/* -------------------------------------------------------------------------- */
/* Alpha Vantage — earnings calendar (CSV). Stubbed graceful integration.      */
/* https://www.alphavantage.co/documentation/                                  */
/* -------------------------------------------------------------------------- */
async function alphaVantage(cfg, providerCfg, log) {
  const key = providerCfg.apiKey;
  if (!key) {
    log('  · alphaVantage: enabled but no apiKey set — skipping.');
    return [];
  }
  // Alpha Vantage returns CSV for calendars; full parsing is left as a hook.
  // Kept graceful so enabling it never breaks the routine.
  log('  · alphaVantage: provider stub — returning no events (extend in providers.js).');
  return [];
}

function parsePriceRange(str) {
  if (str == null) return null;
  const m = String(str).match(/(\d+(?:\.\d+)?)/);
  return m ? parseFloat(m[1]) : null;
}

const REGISTRY = {
  finnhub,
  alphaVantage,
};

/**
 * Run every enabled provider and return a flat array of normalized events.
 * Always resolves (never throws) — failures degrade to fewer events.
 */
async function fetchLiveEvents(config, log) {
  log = log || (() => {});
  if (!config.liveData || !config.liveData.enabled) {
    log("• Live data disabled (config.liveData.enabled = false). Using local store only.");
    return [];
  }
  const providers = config.providers || {};
  const all = [];
  for (const [name, providerCfg] of Object.entries(providers)) {
    if (!providerCfg || !providerCfg.enabled) continue;
    const fn = REGISTRY[name];
    if (!fn) {
      log(`  · ${name}: no implementation registered — skipping.`);
      continue;
    }
    try {
      const evs = await fn(config, providerCfg, log);
      all.push(...evs);
    } catch (err) {
      log(`  · ${name}: failed (${err.message}) — skipping.`);
    }
  }
  return all;
}

module.exports = { fetchLiveEvents, REGISTRY };
