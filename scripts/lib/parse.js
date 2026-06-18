/*
 * Stock Calendar — shared parsing & merge logic.
 *
 * This module is intentionally dependency-free and environment-agnostic so the
 * *exact same* logic runs in two places:
 *   - Node:    scripts/update_calendar.js  (reads ./import/*, writes the JSON store)
 *   - Browser: app.js                      ("Update from chats" button)
 *
 * It is exposed via a small UMD wrapper: CommonJS (require) for Node, and a
 * `window.StockCalendarParse` global for the browser (works from file:// too).
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api; // Node / CommonJS
  } else {
    root.StockCalendarParse = api; // Browser global
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const EVENT_TYPES = ["ipo", "earnings", "catalyst", "custom"];
  const SIGNALS = ["positive", "neutral", "caution"];

  const DEFAULTS = {
    MIN_IPO_PRICE: 10,
    trackedTickers: [],
  };

  // --- tiny utilities --------------------------------------------------------

  function slugify(str) {
    return String(str || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60);
  }

  // FNV-1a 32-bit hash -> base36. Deterministic, no crypto dependency.
  function shortHash(str) {
    let h = 0x811c9dc5;
    const s = String(str || "");
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    return (h >>> 0).toString(36).slice(0, 6);
  }

  // Stable id from ticker + type + date (matches the spec's example slug form).
  // Macro events (no ticker) get a short title hash so two macro events on the
  // same day don't collide.
  function makeId({ ticker, type, date, title }) {
    if (ticker) {
      return `${slugify(ticker)}-${slugify(type)}-${date}`;
    }
    return `mkt-${slugify(type)}-${date}-${shortHash(title || "")}`;
  }

  function pad2(n) {
    return String(n).padStart(2, "0");
  }

  function toISO(y, m, d) {
    return `${y}-${pad2(m)}-${pad2(d)}`;
  }

  const MONTHS = {
    jan: 1, january: 1, feb: 2, february: 2, mar: 3, march: 3, apr: 4, april: 4,
    may: 5, jun: 6, june: 6, jul: 7, july: 7, aug: 8, august: 8, sep: 9,
    sept: 9, september: 9, oct: 10, october: 10, nov: 11, november: 11,
    dec: 12, december: 12,
  };

  // Given a month/day with no year, pick the next occurrence relative to `ref`.
  function resolveYear(month, day, ref) {
    const refY = ref.getUTCFullYear();
    const candidate = Date.UTC(refY, month - 1, day);
    // If the date already passed (more than ~1 day ago), roll to next year.
    if (candidate < Date.UTC(refY, ref.getUTCMonth(), ref.getUTCDate()) - 86400000) {
      return refY + 1;
    }
    return refY;
  }

  function validISO(y, m, d) {
    if (m < 1 || m > 12 || d < 1 || d > 31) return false;
    const dt = new Date(Date.UTC(y, m - 1, d));
    return (
      dt.getUTCFullYear() === y &&
      dt.getUTCMonth() === m - 1 &&
      dt.getUTCDate() === d
    );
  }

  /**
   * Extract the first usable date from a string, returned as ISO YYYY-MM-DD.
   * Supports: ISO (2026-07-15), M/D[/YYYY], and month-name forms
   * ("July 15, 2026", "Jul 15", "15 July 2026"). Returns null if none found.
   */
  function extractDate(text, ref) {
    ref = ref || new Date();

    // 1) ISO
    let m = text.match(/\b(\d{4})-(\d{2})-(\d{2})\b/);
    if (m) {
      const y = +m[1], mo = +m[2], d = +m[3];
      if (validISO(y, mo, d)) return toISO(y, mo, d);
    }

    // 2) Month name first: "July 15, 2026" / "Jul 15"
    m = text.match(
      /\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b/
    );
    if (m && MONTHS[m[1].toLowerCase()]) {
      const mo = MONTHS[m[1].toLowerCase()];
      const d = +m[2];
      const y = m[3] ? +m[3] : resolveYear(mo, d, ref);
      if (validISO(y, mo, d)) return toISO(y, mo, d);
    }

    // 3) Day first: "15 July 2026"
    m = text.match(/\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?(?:,?\s+(\d{4}))?\b/);
    if (m && MONTHS[m[2].toLowerCase()]) {
      const mo = MONTHS[m[2].toLowerCase()];
      const d = +m[1];
      const y = m[3] ? +m[3] : resolveYear(mo, d, ref);
      if (validISO(y, mo, d)) return toISO(y, mo, d);
    }

    // 4) Numeric M/D/YYYY or M/D (assume next occurrence)
    m = text.match(/\b(\d{1,2})\/(\d{1,2})(?:\/(\d{2,4}))?\b/);
    if (m) {
      const mo = +m[1], d = +m[2];
      let y;
      if (m[3]) {
        y = +m[3];
        if (y < 100) y += 2000;
      } else {
        y = resolveYear(mo, d, ref);
      }
      if (validISO(y, mo, d)) return toISO(y, mo, d);
    }

    return null;
  }

  // Collect candidate tickers: $CASHTAGS plus any tracked tickers appearing as
  // standalone uppercase words. Cashtags are the reliable signal.
  function extractTickers(text, trackedTickers) {
    const found = new Set();
    let m;
    const re = /\$([A-Za-z]{1,5})\b/g;
    while ((m = re.exec(text)) !== null) {
      found.add(m[1].toUpperCase());
    }
    (trackedTickers || []).forEach((t) => {
      const re2 = new RegExp(`\\b${t}\\b`);
      if (re2.test(text)) found.add(t.toUpperCase());
    });
    return Array.from(found);
  }

  // Keyword detectors --------------------------------------------------------

  const MACRO_PATTERNS = [
    { re: /\bFOMC\b|\brate decision\b|\bfed (?:meeting|decision)\b/i, label: "FOMC Rate Decision" },
    { re: /\bCPI\b|\binflation (?:report|print|data)\b/i, label: "CPI Inflation Report" },
    { re: /\bPCE\b/i, label: "PCE Inflation Data" },
    { re: /\b(?:jobs report|nonfarm|non-farm|payrolls)\b/i, label: "Jobs Report (Payrolls)" },
    { re: /\bGDP\b/i, label: "GDP Release" },
    { re: /\bretail sales\b/i, label: "Retail Sales" },
  ];

  function detectMacro(text) {
    for (const p of MACRO_PATTERNS) {
      if (p.re.test(text)) return p.label;
    }
    return null;
  }

  function detectCatalystLabel(text) {
    if (/\block-?up\b/i.test(text)) return "Lock-up Expiration";
    if (/\bex-?div(?:idend)?\b/i.test(text)) return "Ex-Dividend Date";
    if (/\b(?:FDA|PDUFA)\b/i.test(text)) return "FDA / PDUFA Decision";
    if (/\b(?:product launch|launch event|unveil|reveal event|keynote)\b/i.test(text)) return "Product Launch / Event";
    if (/\b(?:analyst day|investor day)\b/i.test(text)) return "Analyst / Investor Day";
    if (/\bguidance\b/i.test(text)) return "Guidance Update";
    return null;
  }

  function detectType(text) {
    if (/\bIPO\b|\bgoing public\b|\bpublic offering\b|\bmarket debut\b/i.test(text)) return "ipo";
    if (/\bearnings\b|\bEPS\b|\bquarterly results\b|\breports?\s+(?:Q[1-4]|earnings|results)\b|\b(?:Q[1-4])\s+results\b/i.test(text)) return "earnings";
    return null;
  }

  // Conservative, clearly-labeled signal cues ONLY. We never guess: a signal is
  // attached only when the text contains an explicit analyst/data action.
  function detectSignal(text) {
    if (/\b(?:upgraded|upgrade to (?:buy|outperform)|raised (?:price )?target|initiated.{0,15}buy|outperform rating|buy rating)\b/i.test(text)) {
      return "positive";
    }
    if (/\b(?:downgraded|downgrade|cut (?:price )?target|lowered guidance|profit warning|investigation|sec probe|recall|lawsuit|delisting)\b/i.test(text)) {
      return "caution";
    }
    return null;
  }

  // Extract a dollar amount (used as IPO expected price). Handles "$18.50",
  // "priced at $18", and ranges "$12-$14" (uses the low end).
  function extractPrice(text) {
    const m = text.match(/\$\s?(\d+(?:\.\d{1,2})?)/);
    if (!m) return null;
    const val = parseFloat(m[1]);
    return Number.isFinite(val) ? val : null;
  }

  function truncate(str, n) {
    str = String(str || "").trim().replace(/\s+/g, " ");
    return str.length > n ? str.slice(0, n - 1).trimEnd() + "…" : str;
  }

  // Split text into "lines" — one event maps to one line/bullet. We split on
  // newlines only (not sentences) so an IPO and its price stated in adjacent
  // sentences of the same bullet stay together. Leading markdown markers
  // (headers, blockquotes, list bullets) are stripped without touching a
  // line that *starts* with a date.
  function toLines(text) {
    return String(text || "")
      .split(/\r?\n/)
      .map((l) =>
        l
          .replace(/^\s*#{1,6}\s+/, "") // markdown headers
          .replace(/^\s*>+\s?/, "") // blockquotes
          .replace(/^\s*(?:[-*•]|\d+[.)])\s+/, "") // list markers: "- ", "1. ", "2) "
          .trim()
      )
      .filter(Boolean);
  }

  /**
   * Parse free text into normalized event objects.
   * @returns {Array} events
   */
  function extractEvents(text, options) {
    options = options || {};
    const config = Object.assign({}, DEFAULTS, options.config || {});
    const source = options.source || "chat";
    const sourceRef = options.sourceRef || "";
    const ref = options.referenceDate ? new Date(options.referenceDate) : new Date();

    const out = [];

    for (const line of toLines(text)) {
      const date = extractDate(line, ref);
      if (!date) continue; // an event must have a date

      const tickers = extractTickers(line, config.trackedTickers);
      const macroLabel = detectMacro(line);
      const catalystLabel = detectCatalystLabel(line);
      let type = detectType(line);

      // Decide type & whether this line is event-worthy.
      if (!type) {
        if (macroLabel || catalystLabel) type = "catalyst";
        else if (tickers.length) type = "catalyst";
        else continue; // a bare date with no stock/macro context -> skip (no noise)
      }

      const ticker = tickers.length ? tickers[0] : null;
      const signal = detectSignal(line) || undefined;

      // Build a clean title.
      let title;
      if (type === "ipo") {
        title = ticker ? `${ticker} IPO` : "IPO";
      } else if (type === "earnings") {
        const q = line.match(/\bQ[1-4]\b/i);
        title = `${ticker || "Earnings"}${q ? " " + q[0].toUpperCase() : ""} Earnings`.replace(/^Earnings Earnings$/, "Earnings");
      } else if (type === "catalyst") {
        const label = macroLabel || catalystLabel || "Catalyst";
        title = ticker ? `${ticker} ${label}` : label;
      } else {
        title = truncate(line, 50);
      }

      const event = {
        date,
        ticker,
        type,
        title,
        notes: truncate(line, 220),
        source,
        sourceRef,
      };
      if (signal) event.signal = signal;

      if (type === "ipo") {
        const price = extractPrice(line);
        if (price != null) event.expectedPrice = price;
      }

      event.id = makeId(event);
      out.push(event);
    }

    // Dedupe within this single parse pass (merge same-id mentions).
    return dedupeById(out);
  }

  // Merge a list onto itself by id (later mention enriches earlier one).
  function dedupeById(events) {
    const map = new Map();
    for (const ev of events) {
      if (map.has(ev.id)) {
        map.set(ev.id, mergeOne(map.get(ev.id), ev));
      } else {
        map.set(ev.id, ev);
      }
    }
    return Array.from(map.values());
  }

  // Field-level merge: prefer existing values, fill gaps from incoming.
  function mergeOne(existing, incoming) {
    const merged = Object.assign({}, existing);
    for (const key of ["expectedPrice", "signal", "ticker", "endDate"]) {
      if (merged[key] == null && incoming[key] != null) merged[key] = incoming[key];
    }
    // Prefer the longer / more informative notes & title.
    if ((incoming.notes || "").length > (merged.notes || "").length) merged.notes = incoming.notes;
    if (!merged.title && incoming.title) merged.title = incoming.title;
    return merged;
  }

  function isManual(ev) {
    return ev && ev.source === "manual";
  }

  /**
   * Merge incoming (parsed/api) events into an existing store.
   *  - Dedupe on id.
   *  - NEVER overwrite manually-added events.
   *  - Otherwise update in place (merge fields) rather than duplicating.
   * @returns {{ events: Array, added: number, updated: number, skippedManual: number }}
   */
  function mergeEvents(existing, incoming, opts) {
    opts = opts || {};
    const preserveManual = opts.preserveManual !== false;
    const map = new Map((existing || []).map((e) => [e.id, e]));
    let added = 0;
    let updated = 0;
    let skippedManual = 0;

    for (const ev of dedupeById(incoming || [])) {
      const prior = map.get(ev.id);
      if (!prior) {
        map.set(ev.id, ev);
        added++;
        continue;
      }
      if (preserveManual && isManual(prior)) {
        skippedManual++;
        continue; // do not touch manual events
      }
      const merged = mergeOne(prior, ev);
      // Update mutable fields from the fresh source.
      merged.date = ev.date || merged.date;
      merged.title = ev.title || merged.title;
      merged.type = ev.type || merged.type;
      if (ev.expectedPrice != null) merged.expectedPrice = ev.expectedPrice;
      if (ev.signal) merged.signal = ev.signal;
      if (ev.sourceRef) merged.sourceRef = ev.sourceRef;
      if (JSON.stringify(merged) !== JSON.stringify(prior)) updated++;
      map.set(ev.id, merged);
    }

    return { events: Array.from(map.values()), added, updated, skippedManual };
  }

  // Sort by date ascending, then ticker/title for stability.
  function sortEvents(events) {
    return events.slice().sort((a, b) => {
      if (a.date !== b.date) return a.date < b.date ? -1 : 1;
      return (a.ticker || a.title || "").localeCompare(b.ticker || b.title || "");
    });
  }

  // Return events with below-threshold IPOs removed (used for default UI view).
  function applyIpoPriceFilter(events, minPrice) {
    const min = minPrice == null ? DEFAULTS.MIN_IPO_PRICE : minPrice;
    return events.filter((e) => {
      if (e.type !== "ipo") return true;
      if (e.expectedPrice == null) return true; // unknown price -> keep
      return e.expectedPrice >= min;
    });
  }

  return {
    DEFAULTS,
    EVENT_TYPES,
    SIGNALS,
    slugify,
    shortHash,
    makeId,
    extractDate,
    extractTickers,
    extractEvents,
    mergeEvents,
    dedupeById,
    sortEvents,
    applyIpoPriceFilter,
  };
});
