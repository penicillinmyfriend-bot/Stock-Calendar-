/* =========================================================================
   Stock Calendar — front-end application (vanilla JS, no build step).

   Storage model
   -------------
   - data/calendar-events.json is the canonical, git-friendly store, written by
     the Node update routine (scripts/update_calendar.js).
   - The browser seeds from that file on load, then keeps a working copy in
     localStorage. Manual edits live in localStorage and are MERGED with the
     file on every load so that:
       * file-side changes (chat/api events) appear on reload, and
       * manually-added events are never overwritten or lost.
   - "Export" writes the working store back out to calendar-events.json (via the
     File System Access API when available, otherwise a download) so it can be
     committed to git.

   Parsing/merge logic is shared with Node via scripts/lib/parse.js
   (window.StockCalendarParse).
   ========================================================================= */
(function () {
  "use strict";

  var Parse = window.StockCalendarParse;
  var STORE_KEY = "stockCalendar.events.v1";
  var PREFS_KEY = "stockCalendar.prefs.v1";

  var DEFAULT_CONFIG = {
    MIN_IPO_PRICE: 10,
    trackedTickers: [],
    disclaimer: "For informational purposes only — not financial advice.",
  };

  // Tiny built-in fallback so the UI is never blank when opened from file://
  // with no localStorage and no server to fetch the JSON store.
  var FALLBACK_SAMPLE = [
    {
      id: "welcome-catalyst-2026-07-29",
      date: "2026-07-29",
      ticker: null,
      type: "catalyst",
      title: "FOMC Rate Decision",
      notes:
        "Sample event. Run a local server (see README) to load your real data/calendar-events.json.",
      source: "manual",
      sourceRef: "fallback",
      signal: "neutral",
    },
  ];

  // -------------------------------------------------------------- App state
  var state = {
    config: Object.assign({}, DEFAULT_CONFIG),
    events: [],
    view: "month", // 'month' | 'upcoming'
    cursor: startOfMonth(new Date()), // month being viewed
    filters: {
      types: { ipo: true, earnings: true, catalyst: true, custom: true },
      ticker: "",
      showBelowMin: false,
    },
    fileHandle: null, // File System Access API handle, if granted
    editingEvent: null, // event being edited in the modal, or null when adding
  };

  // ----------------------------------------------------------------- Helpers
  function $(sel) {
    return document.querySelector(sel);
  }
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "class") node.className = attrs[k];
        else if (k === "text") node.textContent = attrs[k];
        else if (k === "html") node.innerHTML = attrs[k];
        else if (k.indexOf("on") === 0 && typeof attrs[k] === "function")
          node.addEventListener(k.slice(2), attrs[k]);
        else if (attrs[k] != null) node.setAttribute(k, attrs[k]);
      });
    }
    (children || []).forEach(function (c) {
      if (c == null) return;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  function startOfMonth(d) {
    return new Date(d.getFullYear(), d.getMonth(), 1);
  }
  function isoDate(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }
  function parseISO(s) {
    var p = String(s).split("-");
    return new Date(+p[0], +p[1] - 1, +p[2]);
  }
  function todayISO() {
    return isoDate(new Date());
  }

  var MONTH_NAMES = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  var MONTH_ABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  var WEEKDAYS = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];

  function fmtLongDate(s) {
    var d = parseISO(s);
    return WEEKDAYS[d.getDay()] + ", " + MONTH_NAMES[d.getMonth()] + " " + d.getDate() + ", " + d.getFullYear();
  }

  // Human-friendly relative date: "Today", "Tomorrow", "in 5 days", "in 2 months".
  function relativeDate(iso) {
    var diff = Math.round((parseISO(iso) - parseISO(todayISO())) / 86400000);
    if (diff === 0) return "Today";
    if (diff === 1) return "Tomorrow";
    if (diff === -1) return "Yesterday";
    var abs = Math.abs(diff);
    var phrase = abs <= 45 ? abs + " days" : Math.round(abs / 30) + " months";
    return diff > 0 ? "in " + phrase : phrase + " ago";
  }
  // CSS modifier for the relative-date pill (soon / future / past).
  function relativeClass(iso) {
    var diff = Math.round((parseISO(iso) - parseISO(todayISO())) / 86400000);
    if (diff < 0) return "event-card__rel--past";
    if (diff <= 3) return "event-card__rel--soon";
    return "";
  }

  // --------------------------------------------------------------- Toasts
  function toast(msg, kind) {
    var t = el("div", { class: "toast" + (kind ? " toast--" + kind : ""), text: msg });
    $("#toasts").appendChild(t);
    setTimeout(function () {
      t.style.transition = "opacity .3s ease";
      t.style.opacity = "0";
      setTimeout(function () {
        t.remove();
      }, 300);
    }, 3200);
  }

  // --------------------------------------------------- Load config + events
  function fetchJSON(url) {
    return fetch(url, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  function loadConfig() {
    return fetchJSON("config.local.json")
      .catch(function () {
        return fetchJSON("config.example.json");
      })
      .then(function (cfg) {
        state.config = Object.assign({}, DEFAULT_CONFIG, cfg);
      })
      .catch(function () {
        /* defaults already set; offline/file:// is fine */
      });
  }

  function readLocalStore() {
    try {
      var raw = JSON.parse(localStorage.getItem(STORE_KEY) || "null");
      if (Array.isArray(raw)) return raw;
    } catch (e) {}
    return null;
  }

  function writeLocalStore() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(state.events));
    } catch (e) {
      toast("Could not save locally (storage full?)", "error");
    }
  }

  function loadEvents() {
    var local = readLocalStore();
    return fetchJSON("data/calendar-events.json")
      .then(function (data) {
        return Array.isArray(data) ? data : data.events || [];
      })
      .catch(function () {
        return null; // file:// or no server — fall back to local
      })
      .then(function (fileEvents) {
        if (local && fileEvents) {
          // Merge file (canonical) into local, preserving manual local events.
          var res = Parse.mergeEvents(local, fileEvents, { preserveManual: true });
          state.events = res.events;
        } else if (local) {
          state.events = local;
          if (!fileEvents) {
            showNotice(
              "Opened without a server — using your locally-saved events. " +
                "Run a local server (see README) to load data/calendar-events.json."
            );
          }
        } else if (fileEvents) {
          state.events = fileEvents;
        } else {
          state.events = FALLBACK_SAMPLE.slice();
          showNotice(
            "No data server detected. Showing a sample event. See the README to " +
              "run a local server and load your real calendar."
          );
        }
        writeLocalStore();
      });
  }

  function showNotice(text) {
    $("#notice-text").textContent = text;
    $("#notice").classList.remove("is-hidden");
  }

  // --------------------------------------------------------------- Prefs
  function loadPrefs() {
    try {
      var p = JSON.parse(localStorage.getItem(PREFS_KEY) || "null");
      if (p) {
        if (p.view) state.view = p.view;
        if (p.filters) state.filters = Object.assign(state.filters, p.filters);
      }
    } catch (e) {}
  }
  function savePrefs() {
    try {
      localStorage.setItem(
        PREFS_KEY,
        JSON.stringify({ view: state.view, filters: state.filters })
      );
    } catch (e) {}
  }

  // ----------------------------------------------------- Visible event set
  function visibleEvents() {
    var min = state.config.MIN_IPO_PRICE;
    var f = state.filters;
    return state.events.filter(function (e) {
      if (!f.types[e.type]) return false;
      if (f.ticker && e.ticker !== f.ticker) return false;
      if (
        !f.showBelowMin &&
        e.type === "ipo" &&
        e.expectedPrice != null &&
        e.expectedPrice < min
      ) {
        return false;
      }
      return true;
    });
  }

  function railClass(e) {
    var c = "event-card__rail event-card__rail--" + e.type;
    if (e.signal === "caution") c += " is-caution";
    return c;
  }
  function pillClass(e) {
    var c = "pill pill--" + e.type;
    if (e.signal === "caution") c += " is-caution";
    return c;
  }

  // --------------------------------------------------------- Render: month
  function renderMonth() {
    var container = $("#month-view");
    container.innerHTML = "";

    var cursor = state.cursor;
    $("#month-label").textContent =
      MONTH_NAMES[cursor.getMonth()] + " " + cursor.getFullYear();

    // Group visible events by date for quick lookup.
    var byDate = {};
    visibleEvents().forEach(function (e) {
      (byDate[e.date] = byDate[e.date] || []).push(e);
    });

    var grid = el("div", { class: "month-grid" });
    var weekdays = el("div", { class: "month-grid__weekdays" });
    WEEKDAYS.forEach(function (w) {
      weekdays.appendChild(el("div", { class: "month-grid__weekday", text: w }));
    });
    grid.appendChild(weekdays);

    var days = el("div", { class: "month-grid__days" });
    var first = startOfMonth(cursor);
    var startDay = first.getDay(); // 0=Sun
    var gridStart = new Date(first);
    gridStart.setDate(first.getDate() - startDay);
    var today = todayISO();

    for (var i = 0; i < 42; i++) {
      var d = new Date(gridStart);
      d.setDate(gridStart.getDate() + i);
      var ds = isoDate(d);
      var outside = d.getMonth() !== cursor.getMonth();

      var cell = el("div", {
        class:
          "day" +
          (outside ? " day--outside" : "") +
          (ds === today ? " day--today" : ""),
      });
      cell.dataset.date = ds;

      cell.appendChild(el("div", { class: "day__num", text: String(d.getDate()) }));

      var dayEvents = byDate[ds] || [];
      var shown = dayEvents.slice(0, 3);
      shown.forEach(function (e) {
        cell.appendChild(makePill(e));
      });
      if (dayEvents.length > 3) {
        cell.appendChild(
          el("button", {
            class: "pill__more",
            text: "+" + (dayEvents.length - 3) + " more",
          })
        );
      }

      // Clicking the day opens that day's events (if any).
      (function (events, label) {
        cell.addEventListener("click", function () {
          if (events.length) openDetail(events, fmtLongDate(label));
        });
      })(dayEvents, ds);

      days.appendChild(cell);
    }
    grid.appendChild(days);
    container.appendChild(grid);
  }

  function makePill(e) {
    var label = e.ticker ? e.ticker + " · " + shortType(e) : e.title;
    var pill = el("div", { class: pillClass(e), title: e.title });
    pill.textContent = label;
    pill.addEventListener("click", function (ev) {
      ev.stopPropagation();
      openDetail([e], e.title);
    });
    return pill;
  }
  function shortType(e) {
    return { ipo: "IPO", earnings: "Earnings", catalyst: "Catalyst", custom: "Note" }[e.type] || e.type;
  }

  // ------------------------------------------------------ Render: upcoming
  function renderUpcoming() {
    var container = $("#upcoming-view");
    container.innerHTML = "";

    var today = todayISO();
    var events = Parse.sortEvents(
      visibleEvents().filter(function (e) {
        return e.date >= today;
      })
    );

    if (!events.length) {
      container.appendChild(emptyState("No upcoming events match your filters."));
      return;
    }

    // Group by ISO week (Monday start).
    var groups = [];
    var map = {};
    events.forEach(function (e) {
      var key = weekKey(e.date);
      if (!map[key]) {
        map[key] = { key: key, label: weekLabel(e.date), items: [] };
        groups.push(map[key]);
      }
      map[key].items.push(e);
    });

    var agenda = el("div", { class: "agenda" });
    groups.forEach(function (g) {
      var section = el("div", {});
      section.appendChild(el("div", { class: "agenda__week-label", text: g.label }));
      var list = el("div", { class: "agenda__list" });
      g.items.forEach(function (e) {
        list.appendChild(makeEventCard(e));
      });
      section.appendChild(list);
      agenda.appendChild(section);
    });
    container.appendChild(agenda);
  }

  function weekKey(dateStr) {
    var d = parseISO(dateStr);
    var monday = new Date(d);
    var off = (d.getDay() + 6) % 7; // days since Monday
    monday.setDate(d.getDate() - off);
    return isoDate(monday);
  }
  function weekLabel(dateStr) {
    var monday = parseISO(weekKey(dateStr));
    var sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);
    var thisWeek = weekKey(todayISO());
    var prefix = weekKey(dateStr) === thisWeek ? "This week · " : "";
    return (
      prefix +
      "Week of " +
      MONTH_ABBR[monday.getMonth()] +
      " " +
      monday.getDate() +
      " – " +
      MONTH_ABBR[sunday.getMonth()] +
      " " +
      sunday.getDate()
    );
  }

  function makeEventCard(e) {
    var d = parseISO(e.date);
    var card = el("div", { class: "event-card" });
    card.appendChild(el("div", { class: railClass(e) }));
    card.appendChild(
      el("div", { class: "event-card__date" }, [
        el("div", { class: "d", text: String(d.getDate()) }),
        el("div", { class: "m", text: MONTH_ABBR[d.getMonth()] }),
      ])
    );

    var titleRow = el("div", { class: "event-card__title" }, [e.title]);
    titleRow.appendChild(el("span", { class: "badge badge--type", text: shortType(e) }));
    if (e.signal) titleRow.appendChild(signalBadge(e.signal));

    var meta = [];
    if (e.ticker) meta.push(e.ticker);
    if (e.type === "ipo" && e.expectedPrice != null)
      meta.push("Expected $" + e.expectedPrice);

    var body = el("div", { class: "event-card__body" }, [titleRow]);
    if (meta.length)
      body.appendChild(el("div", { class: "event-card__meta", text: meta.join(" · ") }));
    if (e.notes)
      body.appendChild(el("div", { class: "event-card__notes", text: e.notes }));

    card.appendChild(body);
    card.appendChild(
      el("div", {
        class: ("event-card__rel " + relativeClass(e.date)).trim(),
        text: relativeDate(e.date),
      })
    );
    card.addEventListener("click", function () {
      openDetail([e], e.title);
    });
    return card;
  }

  function signalBadge(signal) {
    var labels = { positive: "Positive", neutral: "Neutral", caution: "Caution" };
    return el("span", {
      class: "badge badge--signal badge--" + signal,
      text: labels[signal] || signal,
      title: "Signal, not a prediction",
    });
  }

  function emptyState(msg) {
    return el("div", { class: "empty" }, [
      el("h3", { text: "Nothing here yet" }),
      el("p", { text: msg }),
    ]);
  }

  // ------------------------------------------------------- Detail panel
  function openDetail(events, title) {
    var body = $("#panel-body");
    body.innerHTML = "";
    $("#panel-title").textContent = title || "Event";

    events.forEach(function (e) {
      body.appendChild(renderDetailCard(e));
    });

    $("#detail-panel").classList.add("is-open");
    $("#detail-panel").setAttribute("aria-hidden", "false");
  }
  function closeDetail() {
    $("#detail-panel").classList.remove("is-open");
    $("#detail-panel").setAttribute("aria-hidden", "true");
  }

  function renderDetailCard(e) {
    var card = el("div", { class: "detail" });
    card.appendChild(el("div", { class: "detail__title", text: e.title }));

    var row = el("div", { class: "detail__row" });
    row.appendChild(el("span", { class: "badge badge--type", text: shortType(e) }));
    if (e.ticker) row.appendChild(el("span", { class: "badge badge--ticker", text: e.ticker }));
    if (e.signal) row.appendChild(signalBadge(e.signal));
    card.appendChild(row);

    card.appendChild(el("div", { class: "detail__label", text: "Date" }));
    card.appendChild(el("div", { text: fmtLongDate(e.date) + " · " + relativeDate(e.date) }));

    if (e.type === "ipo" && e.expectedPrice != null) {
      card.appendChild(el("div", { class: "detail__label", text: "Expected price" }));
      card.appendChild(el("div", { text: "$" + e.expectedPrice }));
    }

    if (e.signal) {
      card.appendChild(
        el("div", {
          class: "signal-note",
          text: "Signal: " + e.signal + " — this is a labeled indicator, not a prediction.",
        })
      );
    }

    if (e.notes) {
      card.appendChild(el("div", { class: "detail__label", text: "Notes" }));
      card.appendChild(el("div", { class: "detail__notes", text: e.notes }));
    }

    card.appendChild(el("div", { class: "detail__label", text: "Source" }));
    var src = el("div", { class: "detail__source" });
    var srcText = (e.source || "—") + (e.sourceRef ? " · " + e.sourceRef : "");
    if (e.sourceRef && /^https?:\/\//.test(e.sourceRef)) {
      src.appendChild(document.createTextNode((e.source || "api") + " · "));
      src.appendChild(el("a", { href: e.sourceRef, target: "_blank", rel: "noopener", text: e.sourceRef }));
    } else {
      src.textContent = srcText;
    }
    card.appendChild(src);

    var actions = el("div", { class: "detail__actions" });
    actions.appendChild(
      el("button", {
        class: "btn",
        text: "Edit",
        onclick: function () {
          openModal(e);
        },
      })
    );
    actions.appendChild(
      el("button", {
        class: "btn btn--danger",
        text: "Delete",
        onclick: function () {
          deleteEvent(e.id);
        },
      })
    );
    card.appendChild(actions);
    return card;
  }

  function deleteEvent(id) {
    var ev = state.events.find(function (e) {
      return e.id === id;
    });
    if (!ev) return;
    if (!window.confirm("Delete “" + ev.title + "”? This removes it from your local store.")) return;
    state.events = state.events.filter(function (e) {
      return e.id !== id;
    });
    writeLocalStore();
    closeDetail();
    render();
    toast("Event deleted", "success");
  }

  // ------------------------------------------------------ Add / edit event
  function openModal(event) {
    $("#event-form").reset();
    state.editingEvent = event && event.id ? event : null;
    $("#modal-title").textContent = state.editingEvent ? "Edit event" : "Add event";
    $("#modal-submit").textContent = state.editingEvent ? "Save changes" : "Save event";

    if (state.editingEvent) {
      $("#f-date").value = event.date;
      $("#f-type").value = event.type;
      $("#f-ticker").value = event.ticker || "";
      $("#f-title").value = event.title || "";
      $("#f-notes").value = event.notes || "";
      $("#f-signal").value = event.signal || "";
      $("#f-price").value = event.expectedPrice != null ? event.expectedPrice : "";
      $("#f-source").value = event.source || "manual";
    } else {
      $("#f-source").value = "manual";
      $("#f-date").value = todayISO();
    }

    syncPriceField();
    closeDetail();
    $("#modal-backdrop").classList.add("is-open");
    setTimeout(function () {
      $("#f-date").focus();
    }, 50);
  }
  function closeModal() {
    $("#modal-backdrop").classList.remove("is-open");
    state.editingEvent = null;
  }
  function syncPriceField() {
    $("#field-price").classList.toggle("is-hidden", $("#f-type").value !== "ipo");
  }

  function submitEvent(ev) {
    ev.preventDefault();
    var editing = state.editingEvent;
    var type = $("#f-type").value;
    var ticker = $("#f-ticker").value.trim().toUpperCase() || null;
    var date = $("#f-date").value;
    if (!date) {
      toast("Please choose a date", "error");
      return;
    }
    var title = $("#f-title").value.trim();
    if (!title) title = autoTitle(type, ticker);

    var event = {
      date: date,
      ticker: ticker,
      type: type,
      title: title,
      notes: $("#f-notes").value.trim(),
      // A hand-edited event becomes user-curated ("manual") so the update
      // routine never overwrites it; its origin is preserved in sourceRef.
      source: "manual",
      sourceRef: editing ? editing.sourceRef || "manual" : "manual",
    };
    var signal = $("#f-signal").value;
    if (signal) event.signal = signal;
    if (type === "ipo") {
      var price = parseFloat($("#f-price").value);
      if (!isNaN(price)) event.expectedPrice = price;
    }
    event.id = Parse.makeId(event);

    // If editing and the key (ticker+type+date) changed, the id changes too —
    // drop the old entry so the event moves rather than duplicates.
    if (editing && editing.id !== event.id) {
      state.events = state.events.filter(function (e) {
        return e.id !== editing.id;
      });
    }

    var idx = state.events.findIndex(function (e) {
      return e.id === event.id;
    });
    if (idx >= 0) state.events[idx] = event;
    else state.events.push(event);

    writeLocalStore();
    closeModal();
    refreshTickerFilter();
    render();
    toast(editing ? "Event updated" : "Event added", "success");
  }

  function autoTitle(type, ticker) {
    if (type === "ipo") return (ticker || "Company") + " IPO";
    if (type === "earnings") return (ticker || "") + " Earnings".trim();
    if (type === "catalyst") return (ticker ? ticker + " " : "") + "Catalyst";
    return ticker ? ticker + " note" : "Custom event";
  }

  // ------------------------------------------------- Update from chats (UI)
  function triggerImport() {
    $("#import-input").click();
  }

  function handleImportFiles(fileList) {
    var files = Array.prototype.slice.call(fileList || []);
    if (!files.length) return;

    var readers = files.map(function (file) {
      return file.text
        ? file.text().then(function (text) {
            return { name: file.name, text: text };
          })
        : new Promise(function (resolve) {
            var fr = new FileReader();
            fr.onload = function () {
              resolve({ name: file.name, text: String(fr.result) });
            };
            fr.readAsText(file);
          });
    });

    Promise.all(readers).then(function (docs) {
      var added = 0,
        updated = 0,
        belowMin = 0;
      docs.forEach(function (doc) {
        var parsed = Parse.extractEvents(doc.text, {
          source: "chat",
          sourceRef: "import/" + doc.name,
          config: state.config,
        });
        belowMin += parsed.filter(function (e) {
          return (
            e.type === "ipo" &&
            e.expectedPrice != null &&
            e.expectedPrice < state.config.MIN_IPO_PRICE
          );
        }).length;
        var res = Parse.mergeEvents(state.events, parsed, { preserveManual: true });
        state.events = res.events;
        added += res.added;
        updated += res.updated;
      });

      writeLocalStore();
      refreshTickerFilter();
      render();

      var msg =
        added + " added, " + updated + " updated from " + docs.length + " file" +
        (docs.length === 1 ? "" : "s");
      if (belowMin)
        msg += " · " + belowMin + " low-price IPO" + (belowMin === 1 ? "" : "s") + " hidden";
      toast(msg, "success");
      showNotice(
        "Imported events are saved to your browser. Use Export to write them " +
          "into data/calendar-events.json, or run the Node routine for the canonical store."
      );
    });
  }

  // ------------------------------------------------------------- Export
  function serializeStore() {
    return (
      JSON.stringify(
        {
          version: 1,
          updatedAt: new Date().toISOString(),
          events: Parse.sortEvents(state.events),
        },
        null,
        2
      ) + "\n"
    );
  }

  function downloadBlob(data, filename, mime) {
    var blob = new Blob([data], { type: mime });
    var url = URL.createObjectURL(blob);
    var a = el("a", { href: url, download: filename });
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function downloadJSON() {
    downloadBlob(serializeStore(), "calendar-events.json", "application/json");
    toast("Downloaded calendar-events.json — move it into data/ to commit", "success");
  }

  // Save straight into the repo via the File System Access API where available.
  function saveJSONToFile() {
    if (!window.showSaveFilePicker) {
      downloadJSON();
      return;
    }
    var data = serializeStore();
    window
      .showSaveFilePicker({
        suggestedName: "calendar-events.json",
        types: [{ description: "JSON", accept: { "application/json": [".json"] } }],
      })
      .then(function (handle) {
        return handle.createWritable().then(function (w) {
          return w.write(data).then(function () {
            return w.close();
          });
        });
      })
      .then(function () {
        toast("Saved calendar-events.json", "success");
      })
      .catch(function (err) {
        if (err && err.name === "AbortError") return;
        downloadJSON();
      });
  }

  // Build an iCalendar (.ics) feed of the visible events as all-day entries so
  // the calendar can be imported into Google / Apple / Outlook.
  function buildICS(events) {
    function esc(s) {
      return String(s == null ? "" : s)
        .replace(/\\/g, "\\\\")
        .replace(/;/g, "\\;")
        .replace(/,/g, "\\,")
        .replace(/\r?\n/g, "\\n");
    }
    function dateOnly(iso) {
      return iso.replace(/-/g, "");
    }
    var now = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
    var out = [
      "BEGIN:VCALENDAR",
      "VERSION:2.0",
      "PRODID:-//Stock Calendar//EN",
      "CALSCALE:GREGORIAN",
      "METHOD:PUBLISH",
      "X-WR-CALNAME:Stock Calendar",
    ];
    Parse.sortEvents(events).forEach(function (e) {
      // All-day events use an exclusive DTEND (start + 1 day).
      var endExclusive = new Date(parseISO(e.endDate || e.date).getTime() + 86400000);
      var desc = ["Type: " + e.type];
      if (e.type === "ipo" && e.expectedPrice != null) desc.push("Expected price: $" + e.expectedPrice);
      if (e.signal) desc.push("Signal (a labeled indicator, not a prediction): " + e.signal);
      if (e.notes) desc.push(e.notes);
      desc.push("Source: " + (e.source || "") + (e.sourceRef ? " (" + e.sourceRef + ")" : ""));
      desc.push("For informational purposes only — not financial advice.");
      out.push(
        "BEGIN:VEVENT",
        "UID:" + e.id + "@stock-calendar",
        "DTSTAMP:" + now,
        "DTSTART;VALUE=DATE:" + dateOnly(e.date),
        "DTEND;VALUE=DATE:" + dateOnly(isoDate(endExclusive)),
        "SUMMARY:" + esc((e.ticker ? e.ticker + " — " : "") + e.title),
        "DESCRIPTION:" + esc(desc.join("\n")),
        "CATEGORIES:" + esc((e.type || "event").toUpperCase()),
        "END:VEVENT"
      );
    });
    out.push("END:VCALENDAR");
    return out.join("\r\n") + "\r\n";
  }

  function exportICS() {
    var events = visibleEvents();
    if (!events.length) {
      toast("No events to export with the current filters", "error");
      return;
    }
    downloadBlob(buildICS(events), "stock-calendar.ics", "text/calendar");
    toast("Exported " + events.length + " events to stock-calendar.ics", "success");
  }

  // Export dropdown menu --------------------------------------------------
  function toggleExportMenu(force) {
    var menu = $("#export-menu");
    var open = force != null ? force : menu.classList.contains("is-hidden");
    menu.classList.toggle("is-hidden", !open);
    $("#btn-export").setAttribute("aria-expanded", open ? "true" : "false");
  }

  // ------------------------------------------------------------ Ticker filter
  function refreshTickerFilter() {
    var sel = $("#ticker-filter");
    var current = state.filters.ticker;
    var tickers = {};
    (state.config.trackedTickers || []).forEach(function (t) {
      tickers[t] = true;
    });
    state.events.forEach(function (e) {
      if (e.ticker) tickers[e.ticker] = true;
    });
    var list = Object.keys(tickers).sort();
    sel.innerHTML = "";
    sel.appendChild(el("option", { value: "", text: "All tickers" }));
    list.forEach(function (t) {
      sel.appendChild(el("option", { value: t, text: t }));
    });
    sel.value = current && tickers[current] ? current : "";
    state.filters.ticker = sel.value;
  }

  // Show how many events of each type exist in the current ticker / price
  // scope (ignoring the type toggles themselves) next to each filter chip.
  function renderChipCounts() {
    var min = state.config.MIN_IPO_PRICE;
    var f = state.filters;
    var counts = {};
    state.events.forEach(function (e) {
      if (f.ticker && e.ticker !== f.ticker) return;
      if (!f.showBelowMin && e.type === "ipo" && e.expectedPrice != null && e.expectedPrice < min) return;
      counts[e.type] = (counts[e.type] || 0) + 1;
    });
    document.querySelectorAll("#type-chips .chip").forEach(function (chip) {
      var span = chip.querySelector(".chip__count");
      if (!span) {
        span = el("span", { class: "chip__count" });
        chip.appendChild(span);
      }
      span.textContent = counts[chip.dataset.type] || 0;
    });
  }

  // ------------------------------------------------------------------ Render
  function render() {
    renderChipCounts();
    if (state.view === "month") {
      $("#month-view").classList.remove("is-hidden");
      $("#upcoming-view").classList.add("is-hidden");
      $("#month-nav").style.visibility = "visible";
      renderMonth();
    } else {
      $("#month-view").classList.add("is-hidden");
      $("#upcoming-view").classList.remove("is-hidden");
      $("#month-nav").style.visibility = "hidden";
      renderUpcoming();
    }
  }

  function setView(view) {
    state.view = view;
    $("#view-month").classList.toggle("is-active", view === "month");
    $("#view-upcoming").classList.toggle("is-active", view === "upcoming");
    savePrefs();
    render();
  }

  // ------------------------------------------------------------------ Events
  function wireEvents() {
    $("#view-month").addEventListener("click", function () {
      setView("month");
    });
    $("#view-upcoming").addEventListener("click", function () {
      setView("upcoming");
    });

    $("#month-prev").addEventListener("click", function () {
      state.cursor = new Date(state.cursor.getFullYear(), state.cursor.getMonth() - 1, 1);
      render();
    });
    $("#month-next").addEventListener("click", function () {
      state.cursor = new Date(state.cursor.getFullYear(), state.cursor.getMonth() + 1, 1);
      render();
    });
    $("#month-today").addEventListener("click", function () {
      state.cursor = startOfMonth(new Date());
      render();
    });

    // Type chips
    document.querySelectorAll("#type-chips .chip").forEach(function (chip) {
      var type = chip.dataset.type;
      chip.classList.toggle("is-active", !!state.filters.types[type]);
      chip.addEventListener("click", function () {
        state.filters.types[type] = !state.filters.types[type];
        chip.classList.toggle("is-active", state.filters.types[type]);
        savePrefs();
        render();
      });
    });

    $("#ticker-filter").addEventListener("change", function (e) {
      state.filters.ticker = e.target.value;
      savePrefs();
      render();
    });

    var belowMin = $("#toggle-belowmin");
    belowMin.checked = state.filters.showBelowMin;
    belowMin.addEventListener("change", function (e) {
      state.filters.showBelowMin = e.target.checked;
      savePrefs();
      render();
    });

    // Header actions
    $("#btn-add").addEventListener("click", function () {
      openModal();
    });
    $("#btn-update").addEventListener("click", triggerImport);

    // Export dropdown menu
    $("#btn-export").addEventListener("click", function (e) {
      e.stopPropagation();
      toggleExportMenu();
    });
    $("#export-menu").addEventListener("click", function (e) {
      var act = e.target && e.target.getAttribute("data-act");
      if (!act) return;
      if (act === "json") downloadJSON();
      else if (act === "save") saveJSONToFile();
      else if (act === "ics") exportICS();
      toggleExportMenu(false);
    });
    document.addEventListener("click", function () {
      toggleExportMenu(false);
    });

    $("#btn-sync").addEventListener("click", function () {
      loadEvents().then(function () {
        refreshTickerFilter();
        render();
        toast("Synced with data file", "success");
      });
    });

    $("#import-input").addEventListener("change", function (e) {
      handleImportFiles(e.target.files);
      e.target.value = ""; // allow re-importing the same file
    });

    // Drag-and-drop import (drop .md/.txt anywhere on the window)
    var dropOverlay = $("#drop-overlay");
    var dragDepth = 0;
    function hasFiles(e) {
      return (
        e.dataTransfer &&
        Array.prototype.indexOf.call(e.dataTransfer.types || [], "Files") !== -1
      );
    }
    window.addEventListener("dragenter", function (e) {
      if (!hasFiles(e)) return;
      e.preventDefault();
      dragDepth++;
      dropOverlay.classList.remove("is-hidden");
    });
    window.addEventListener("dragover", function (e) {
      if (hasFiles(e)) e.preventDefault();
    });
    window.addEventListener("dragleave", function (e) {
      if (!hasFiles(e)) return;
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0) dropOverlay.classList.add("is-hidden");
    });
    window.addEventListener("drop", function (e) {
      if (!hasFiles(e)) return;
      e.preventDefault();
      dragDepth = 0;
      dropOverlay.classList.add("is-hidden");
      var files = Array.prototype.filter.call(e.dataTransfer.files, function (f) {
        return /\.(md|txt)$/i.test(f.name);
      });
      if (files.length) handleImportFiles(files);
      else toast("Drop .md or .txt chat exports", "error");
    });

    // Modal
    $("#modal-close").addEventListener("click", closeModal);
    $("#modal-cancel").addEventListener("click", closeModal);
    $("#f-type").addEventListener("change", syncPriceField);
    $("#event-form").addEventListener("submit", submitEvent);
    $("#modal-backdrop").addEventListener("click", function (e) {
      if (e.target === $("#modal-backdrop")) closeModal();
    });

    // Detail panel
    $("#panel-close").addEventListener("click", closeDetail);

    // Notice dismiss
    $("#notice-dismiss").addEventListener("click", function () {
      $("#notice").classList.add("is-hidden");
    });

    // Keyboard
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        closeDetail();
        closeModal();
      }
    });
  }

  // -------------------------------------------------------------------- Init
  function applyDisclaimer() {
    if (state.config.disclaimer) {
      $("#disclaimer").innerHTML =
        "<strong>" +
        escapeHTML(state.config.disclaimer) +
        "</strong> Signals are clearly-labeled indicators derived from concrete inputs, not predictions.";
    }
  }
  function escapeHTML(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function init() {
    if (!Parse) {
      document.body.innerHTML =
        '<p style="padding:40px;font-family:sans-serif">Failed to load parser (scripts/lib/parse.js).</p>';
      return;
    }
    loadPrefs();
    loadConfig()
      .then(loadEvents)
      .then(function () {
        applyDisclaimer();
        refreshTickerFilter();
        wireEvents();
        setView(state.view);
      });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
