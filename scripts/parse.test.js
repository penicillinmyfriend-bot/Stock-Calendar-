/*
 * Tests for the shared parser/merge logic. Run: node --test scripts/
 * Uses Node's built-in test runner (node:test) — no dependencies.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert");
const parse = require("./lib/parse.js");

const REF = "2026-06-18"; // fixed reference date for deterministic tests

test("extractDate handles ISO, month-name, and numeric forms", () => {
  assert.equal(parse.extractDate("IPO on 2026-07-15", new Date(REF)), "2026-07-15");
  assert.equal(parse.extractDate("earnings July 31, 2026", new Date(REF)), "2026-07-31");
  assert.equal(parse.extractDate("jobs report 7/2/2026", new Date(REF)), "2026-07-02");
  assert.equal(parse.extractDate("event 15 August 2026", new Date(REF)), "2026-08-15");
});

test("extractEvents pulls an IPO with price and a stable id", () => {
  const events = parse.extractEvents(
    "$ACME is going public on 2026-07-15. Expected price around $18.50.",
    { sourceRef: "import/x.md", referenceDate: REF }
  );
  const ipo = events.find((e) => e.type === "ipo");
  assert.ok(ipo, "expected an IPO event");
  assert.equal(ipo.ticker, "ACME");
  assert.equal(ipo.expectedPrice, 18.5);
  assert.equal(ipo.id, "acme-ipo-2026-07-15");
  assert.equal(ipo.source, "chat");
});

test("extractEvents detects earnings, macro catalysts, and FDA dates", () => {
  const text = [
    "$TSLA reports earnings on 2026-07-23.",
    "The next jobs report (nonfarm payrolls) lands 7/2/2026.",
    "$BIIB has a PDUFA / FDA decision date on August 5, 2026.",
  ].join("\n");
  const events = parse.extractEvents(text, { sourceRef: "import/x.md", referenceDate: REF });
  assert.ok(events.find((e) => e.type === "earnings" && e.ticker === "TSLA"));
  assert.ok(events.find((e) => e.type === "catalyst" && /Jobs Report/.test(e.title)));
  const fda = events.find((e) => /FDA/.test(e.title));
  assert.ok(fda && fda.type === "catalyst");
});

test("signal is only attached from explicit cues, never guessed", () => {
  const upgraded = parse.extractEvents("$NVDA upgraded to Buy, earnings 2026-08-27", {
    referenceDate: REF,
  });
  assert.equal(upgraded[0].signal, "positive");

  const plain = parse.extractEvents("$NVDA earnings 2026-08-27", { referenceDate: REF });
  assert.equal(plain[0].signal, undefined, "no signal without a concrete cue");
});

test("applyIpoPriceFilter hides IPOs below the threshold but keeps others", () => {
  const events = [
    { type: "ipo", expectedPrice: 4, id: "a" },
    { type: "ipo", expectedPrice: 22, id: "b" },
    { type: "ipo", id: "c" }, // unknown price -> kept
    { type: "earnings", id: "d" },
  ];
  const kept = parse.applyIpoPriceFilter(events, 10);
  assert.deepEqual(kept.map((e) => e.id).sort(), ["b", "c", "d"]);
});

test("mergeEvents dedupes, counts, and NEVER overwrites manual events", () => {
  const existing = [
    { id: "acme-ipo-2026-07-15", type: "ipo", ticker: "ACME", date: "2026-07-15", source: "manual", notes: "my note" },
    { id: "old-api", type: "earnings", ticker: "AAPL", date: "2026-07-31", source: "api", notes: "" },
  ];
  const incoming = [
    // Same id as a manual event — must be preserved untouched.
    { id: "acme-ipo-2026-07-15", type: "ipo", ticker: "ACME", date: "2026-09-09", source: "chat", notes: "changed!" },
    // Updates a non-manual event.
    { id: "old-api", type: "earnings", ticker: "AAPL", date: "2026-08-01", source: "api", notes: "fresh" },
    // Brand new.
    { id: "new-1", type: "catalyst", ticker: null, date: "2026-07-29", source: "chat", notes: "FOMC" },
  ];
  const res = parse.mergeEvents(existing, incoming, { preserveManual: true });
  const acme = res.events.find((e) => e.id === "acme-ipo-2026-07-15");
  assert.equal(acme.date, "2026-07-15", "manual event date unchanged");
  assert.equal(acme.notes, "my note", "manual event notes unchanged");
  assert.equal(res.added, 1);
  assert.equal(res.skippedManual, 1);
  assert.ok(res.updated >= 1);
});

test("makeId is stable for ticker events and unique for macro events", () => {
  const a = parse.makeId({ ticker: "ACME", type: "ipo", date: "2026-07-15" });
  const b = parse.makeId({ ticker: "ACME", type: "ipo", date: "2026-07-15" });
  assert.equal(a, b);
  assert.equal(a, "acme-ipo-2026-07-15");

  const m1 = parse.makeId({ ticker: null, type: "catalyst", date: "2026-07-15", title: "CPI" });
  const m2 = parse.makeId({ ticker: null, type: "catalyst", date: "2026-07-15", title: "FOMC" });
  assert.notEqual(m1, m2, "different macro events on same day get distinct ids");
});
