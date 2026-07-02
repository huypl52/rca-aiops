// RCA demo UI — alert-first incident console.
// Vanilla JS, no build. Polls the FastAPI read-store. Read-only: no action controls,
// no free-text chat. Preset Q&A answers are derived ONLY from report/state_snapshot;
// missing data is shown honestly, never invented.
(function () {
  "use strict";

  // Same-origin when served from the FastAPI /ui mount; override via ?api= for local files.
  var params = new URLSearchParams(location.search);
  var API = params.get("api") || ""; // e.g. "http://localhost:8000"

  var INBOX_MS = 3000;
  var DETAIL_MS = 1500;

  var inboxEl = document.getElementById("inbox-list");
  var inboxEmpty = document.getElementById("inbox-empty");
  var countEl = document.getElementById("incident-count");
  var connEl = document.getElementById("conn-state");

  var detailWrap = document.getElementById("detail");
  var detailPlaceholder = document.getElementById("detail-placeholder");

  var chatScope = document.getElementById("chat-scope");
  var chatLog = document.getElementById("chat-log");

  var seenIds = new Set(); // for arrival emphasis only
  var selectedId = null;
  var lastDetail = null;

  // ---- small helpers ----
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function fmtStatus(s) { return (s || "—").toLowerCase(); }
  function sevClass(s) {
    s = (s || "").toLowerCase();
    return s === "critical" ? "critical" : s === "warning" ? "warning" : s === "info" ? "info" : "";
  }
  function setText(id, v) { document.getElementById(id).textContent = v || "—"; }

  // ---- inbox ----
  async function refreshInbox() {
    try {
      var res = await fetch(API + "/api/investigations");
      if (!res.ok) throw new Error("HTTP " + res.status);
      var data = await res.json();
      connEl.textContent = "live";
      connEl.classList.remove("pill-muted");
      renderInbox(data.items || []);
    } catch (e) {
      connEl.textContent = "offline";
      connEl.classList.add("pill-muted");
    }
  }

  function renderInbox(items) {
    countEl.textContent = items.length + (items.length === 1 ? " incident" : " incidents");
    inboxEl.innerHTML = "";
    if (!items.length) {
      inboxEmpty.classList.remove("hidden");
      return;
    }
    inboxEmpty.classList.add("hidden");

    items.forEach(function (it) {
      var isNew = !seenIds.has(it.investigation_id);
      seenIds.add(it.investigation_id);
      var row = el("li", "inbox-row");
      if (isNew && items.length > 0) row.classList.add("unread", "flash");
      if (it.investigation_id === selectedId) row.classList.add("selected");
      row.addEventListener("click", function () { selectIncident(it.investigation_id); });

      row.appendChild(el("span", "sev-dot " + sevClass(it.severity)));
      var main = el("div", "ir-main");
      main.appendChild(el("div", "ir-alert", it.alert_name || it.canonical_trigger || "(unnamed alert)"));
      main.appendChild(el("div", "ir-sub", [it.service, it.source].filter(Boolean).join(" · ") || "—"));
      row.appendChild(main);
      row.appendChild(el("div", "ir-status", fmtStatus(it.status)));
      inboxEl.appendChild(row);
    });
  }

  // ---- detail ----
  function selectIncident(id) {
    selectedId = id;
    chatLog.innerHTML = "";
    // selected highlight re-applied on next inbox render.
    detailPlaceholder.classList.add("hidden");
    detailWrap.classList.remove("hidden");
    chatScope.textContent = "About incident " + id;
    // greet as agent, grounded only in selection
    agentBubble("Opening incident " + id + ". I’ll narrate the investigation as it runs.");
    pollDetail();
  }

  async function pollDetail() {
    if (!selectedId) return;
    try {
      var res = await fetch(API + "/api/investigations/" + encodeURIComponent(selectedId));
      if (res.status === 404) { renderMissing(); return; }
      if (!res.ok) throw new Error("HTTP " + res.status);
      var data = await res.json();
      connEl.textContent = "live";
      renderDetail(data);
    } catch (e) {
      connEl.textContent = "offline";
    } finally {
      if (selectedId) setTimeout(pollDetail, DETAIL_MS);
    }
  }

  function renderMissing() {
    detailWrap.classList.add("hidden");
    detailPlaceholder.classList.remove("hidden");
    detailPlaceholder.textContent = "Investigation " + selectedId + " was not found in the read-store.";
  }

  function renderDetail(d) {
    var snap = d.state_snapshot || {};
    // Trigger-derived display fields (same source as the inbox row). The live runner's
    // state_snapshot only carries {context, next_action, evidence_count, tool_calls_count},
    // so header/meta come from trigger_summary, with snap.context.* as a defensive fallback.
    var ts = d.trigger_summary || {};
    var ctx = snap.context || {};
    var labels = (ctx && ctx.labels) || {};
    var svc = ts.service || ctx.service || "";
    var ns = ts.namespace || ctx.namespace || "";
    var sev = ts.severity || labels.severity || "";
    var alertName = ts.alert_name || labels.alertname || "";
    var canonical = ts.canonical_trigger || "";
    var startedAt = ts.started_at || "";
    var source = ts.source || "";
    var affected = Array.isArray(ts.affected_services) ? ts.affected_services : [];
    var prev = lastDetail;
    lastDetail = d;

    setText("d-alert-name", alertName || canonical || ts.title || d.investigation_id);
    document.getElementById("d-sub").textContent =
      [canonical, svc].filter(Boolean).join(" · ") || alertName || d.investigation_id;

    var chip = document.getElementById("d-status");
    chip.textContent = fmtStatus(d.status);
    chip.className = "status-chip " + (d.status || "");

    // meta grid — trigger_summary (truthful), fallback to nested snapshot context.
    var meta = document.getElementById("d-meta");
    meta.innerHTML = "";
    var rows = [
      ["severity", sev],
      ["namespace", ns],
      ["source", source],
      ["service", svc],
      ["started_at", startedAt],
      ["affected", affected.length ? affected.join(", ") : ""],
    ];
    rows.forEach(function (r) {
      var item = el("div", "meta-item");
      item.appendChild(el("span", "k", r[0] + ": "));
      item.appendChild(el("span", "v", r[1] != null && r[1] !== "" ? String(r[1]) : "—"));
      meta.appendChild(item);
    });

    renderProgress(d);
    renderTimeline(d, prev);
    renderReport(d);
    maybeNarrate(d, prev);
  }

  function renderProgress(d) {
    var terminal = ["success", "failed", "partial"].indexOf(d.status) >= 0;
    var cur = { running: "execute", success: "report", failed: "report", partial: "report" }[d.status] || "plan";
    var order = ["plan", "execute", "reflect", "report"];
    var curIdx = order.indexOf(cur);
    Array.prototype.forEach.call(document.querySelectorAll(".progress .step"), function (s) {
      var idx = order.indexOf(s.getAttribute("data-step"));
      s.classList.remove("active", "done");
      if (terminal || idx < curIdx) s.classList.add("done");
      else if (idx === curIdx) s.classList.add("active");
    });
  }

  // Coarse, honest timeline: only events we can actually derive from status + snapshot.
  function renderTimeline(d, prev) {
    var snap = d.state_snapshot || {};
    var ts = d.trigger_summary || {};
    var svc = ts.service || (snap.context && snap.context.service) || "";
    var tl = document.getElementById("timeline");
    var empty = document.getElementById("timeline-empty");
    var events = [];

    if (snap.hypotheses || snap.plan) {
      var hyp = snap.hypotheses;
      events.push({
        label: "Plan",
        detail: Array.isArray(hyp) && hyp.length
          ? "investigating " + (svc || "candidate") + " as a likely cause"
          : (snap.plan ? "plan promoted" : "planning"),
      });
    }
    if (snap.evidence_count != null && snap.evidence_count > 0) {
      events.push({ label: "Execute", detail: snap.evidence_count + " evidence item(s) gathered" });
    } else if (snap.evidence_count === 0) {
      events.push({ label: "Execute", detail: "evidence collector not yet run (deferred runtime support)" });
    }
    if (d.status === "partial") {
      events.push({ label: "Reflect", detail: "inconclusive — reached max iterations without sufficient confidence" });
    }
    if (["success", "failed", "partial"].indexOf(d.status) >= 0) {
      events.push({ label: "Report", detail: "RCA report written" });
    }

    tl.innerHTML = "";
    if (!events.length) { empty.classList.remove("hidden"); return; }
    empty.classList.add("hidden");
    events.forEach(function (ev) {
      var li = el("li", "tl-item");
      li.appendChild(el("div", "tl-label", ev.label));
      li.appendChild(el("div", "tl-detail", ev.detail));
      tl.appendChild(li);
    });
  }

  function renderReport(d) {
    var box = document.getElementById("report");
    box.innerHTML = "";
    if (!d.report) {
      box.appendChild(el("p", "r-empty",
        d.status === "running"
          ? "Investigation still running — report appears on completion."
          : "No report available for this run."));
      return;
    }
    var r = d.report || {};
    // Root cause + confidence are rendered via the shared unwrap helpers (same source
    // as chat) so the tile is human-readable, never raw JSON for these structured fields.
    var candidates = rankedCandidates(r.root_cause);
    if (candidates.length) {
      fieldList(box, "Root cause", candidates);
    } else {
      field(box, "Root cause", r.root_cause);
    }
    var conf = confidenceText(r.confidence);
    if (conf) {
      field(box, "Confidence", conf, "confidence");
    } else {
      field(box, "Confidence", r.confidence, "confidence");
    }
    field(box, "Evidence backing", r.evidence_backing, null, true);
    field(box, "Uncertainty", r.uncertainty, null, true);
    field(box, "Open questions", r.open_questions, null, true);
    // remediation is intentionally omitted from the UI (read-only boundary).
  }

  // Like field(), but for a pre-formatted list of human-readable strings (no JSON).
  function fieldList(parent, k, items) {
    var wrap = el("div", "r-field");
    wrap.appendChild(el("div", "r-k", k));
    var body = el("div", "r-v");
    items.forEach(function (s) { body.appendChild(el("div", null, "• " + s)); });
    wrap.appendChild(body);
    parent.appendChild(wrap);
  }

  function field(parent, k, v, extra, block) {
    var wrap = el("div", "r-field");
    wrap.appendChild(el("div", "r-k", k));
    var body;
    if (v == null || v === "" || (Array.isArray(v) && v.length === 0)) {
      body = el("div", "r-v r-empty", "not available in this run");
    } else if (Array.isArray(v)) {
      body = el("div", "r-v");
      v.forEach(function (x) { body.appendChild(el("div", null, "• " + (typeof x === "string" ? x : JSON.stringify(x)))); });
    } else if (typeof v === "object") {
      body = el("div", "r-v", JSON.stringify(v));
    } else {
      body = el("div", "r-v" + (extra ? " " + extra : ""), String(v));
    }
    wrap.appendChild(body);
    parent.appendChild(wrap);
  }

  // One-way narrated bubble when status transitions (grounded, no invention).
  // C2: the "report is ready" wording is gated on an actual report — a success that
  // produced no report (common in the default runner) gets honest status-only wording.
  function maybeNarrate(d, prev) {
    if (!prev || prev.status === d.status) return;
    var msg;
    if (d.status === "success") {
      msg = d.report
        ? "Investigation complete — RCA report is ready."
        : "Investigation complete — no RCA report was produced this run.";
    } else if (d.status === "failed") {
      msg = "Investigation ended without a confident conclusion.";
    } else if (d.status === "partial") {
      msg = "Reached the iteration limit inconclusively (partial). The report reflects that honestly.";
    }
    if (msg) agentBubble(msg);
  }

  // ---- chat ----
  function agentBubble(text) {
    var b = el("div", "bubble agent", text);
    chatLog.appendChild(b);
    chatLog.scrollTop = chatLog.scrollHeight;
  }
  function userBubble(text) {
    var b = el("div", "bubble q", text);
    chatLog.appendChild(b);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  document.querySelectorAll(".preset").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (!lastDetail) return;
      var q = btn.getAttribute("data-q");
      userBubble(PRESET_TEXT[q]);
      agentBubble(answer(q, lastDetail));
    });
  });

  var PRESET_TEXT = {
    what: "What happened?",
    cause: "Which service looks implicated?",
    confidence: "How confident is the result?",
    evidence: "What evidence is available?",
  };

  // ---- structured-field unwrap helpers (grounded, honest) ----
  // rca_writer emits root_cause as a list of {rank, hypothesis_id, priority, citations}
  // and confidence as {ceiling_confidence, categorical}. These unwrap them into
  // human-readable strings without inventing content; missing → null. Shared by the
  // chat answers AND the report tile (DRY) so the two never diverge.
  function formatCandidate(item) {
    if (!item || typeof item !== "object") return null;
    var id = item.hypothesis_id;
    if (!id) return null;
    var cits = Array.isArray(item.citations) ? item.citations.length : 0;
    return String(id) + (cits ? " (" + cits + " citation" + (cits === 1 ? "" : "s") + ")" : "");
  }
  function rankedCandidates(rootCause) {
    if (!Array.isArray(rootCause) || !rootCause.length) return [];
    return rootCause
      .slice()
      .sort(function (a, b) { return (a.rank || 99) - (b.rank || 99); })
      .map(formatCandidate)
      .filter(function (s) { return s; });
  }
  function topRootCause(rootCause) {
    var ranked = rankedCandidates(rootCause);
    return ranked.length ? ranked[0] : null;
  }
  function confidenceText(conf) {
    if (conf == null) return null;
    if (typeof conf === "string" || typeof conf === "number") return String(conf);
    if (typeof conf === "object") {
      var cat = conf.categorical;
      var ceil = conf.ceiling_confidence;
      var parts = [];
      if (cat) parts.push(String(cat));
      if (ceil != null && ceil !== "") parts.push("ceiling " + ceil);
      return parts.length ? parts.join(" · ") : null;
    }
    return null;
  }

  // Answers derived ONLY from report/state_snapshot/trigger_summary. Missing → honest
  // "not available". Structured fields are unwrapped, never stringified as [object Object].
  function answer(q, d) {
    var r = d.report || {};
    var snap = d.state_snapshot || {};
    var ts = d.trigger_summary || {};
    var svc = ts.service || (snap.context && snap.context.service) || "";
    var canonical = ts.canonical_trigger || "";
    if (q === "what") {
      var rc = topRootCause(r.root_cause);
      if (rc) return "Most likely root cause: " + rc + ".";
      if (canonical) {
        return "Trigger under investigation: " + canonical + " on " + (svc || "(service unknown)") + ".";
      }
      return "Not available in this run — no root cause has been written yet.";
    }
    if (q === "cause") {
      if (svc) return "The investigation is centered on " + svc + ".";
      return "Not available in this run — no primary service recorded.";
    }
    if (q === "confidence") {
      var ct = confidenceText(r.confidence);
      if (ct) return "Reported confidence: " + ct + ".";
      if (d.status === "partial") return "Low — the run ended partial (inconclusive).";
      return "Not available in this run — no confidence value written.";
    }
    if (q === "evidence") {
      var n = snap.evidence_count;
      var eb = r.evidence_backing;
      var hasBacking = Array.isArray(eb) ? eb.length : eb;
      if (n != null && n > 0) {
        return n + " evidence item(s) back the report" + (hasBacking ? " (see Evidence backing)." : ".");
      }
      if (hasBacking) return "Evidence backing is recorded in the report.";
      if (n === 0) {
        return "No evidence gathered in this run — the evidence collector is deferred runtime support.";
      }
      return "Not available in this run.";
    }
    return "Not available in this run.";
  }

  // ---- boot ----
  refreshInbox();
  setInterval(refreshInbox, INBOX_MS);
})();
