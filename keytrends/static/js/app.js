/* Dashboard controller: fetches aggregates, renders every panel, and keeps the
   live counters ticking. */

import {
  lineChart, barChart, heatGrid, rampColor, rampSteps,
  fmt, fmtFull, showTip, positionTip, hideTip,
} from "./charts.js";

const $ = (sel) => document.querySelector(sel);
const state = { range: "30d", data: null, settings: {} };

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const RANGE_WORD = {
  today: "yesterday", "7d": "previous 7 days", "30d": "previous 30 days",
  "90d": "previous 90 days", "365d": "previous year", all: "previous period",
};

/* ---------------------------------------------------------------- theme */

function applyTheme(mode) {
  if (mode === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", mode);
  localStorage.setItem("kt-theme", mode);
}

function cycleTheme() {
  const order = ["system", "light", "dark"];
  const current = localStorage.getItem("kt-theme") || "system";
  const next = order[(order.indexOf(current) + 1) % order.length];
  applyTheme(next);
  toast(`Theme: ${next}`);
  if (state.data) renderCharts(state.data);
}

/* ---------------------------------------------------------------- helpers */

let toastTimer = null;
function toast(message) {
  let node = $(".toast");
  if (!node) {
    node = document.createElement("div");
    node.className = "toast";
    document.body.appendChild(node);
  }
  node.textContent = message;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.remove(), 2200);
}

function duration(seconds) {
  seconds = Math.round(seconds || 0);
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m`;
  return `${seconds}s`;
}

function deltaMarkup(pct, label) {
  if (pct === null || pct === undefined) {
    return `<span class="delta flat">— no prior data</span>`;
  }
  const cls = pct > 0.5 ? "up" : pct < -0.5 ? "down" : "flat";
  const arrow = pct > 0.5 ? "↑" : pct < -0.5 ? "↓" : "→";
  return `<span class="delta ${cls}">${arrow} ${Math.abs(pct).toFixed(0)}%</span>
          <span style="color:var(--text-muted)"> vs ${label}</span>`;
}

function dayLabel(iso, _i, long) {
  const d = new Date(iso + "T00:00:00");
  return long
    ? d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function hourLabel(h) {
  if (h === 0) return "12 AM";
  if (h < 12) return `${h} AM`;
  if (h === 12) return "12 PM";
  return `${h - 12} PM`;
}

function table(headers, rows) {
  return `<table class="data"><thead><tr>${
    headers.map((h) => `<th>${h}</th>`).join("")
  }</tr></thead><tbody>${
    rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")
  }</tbody></table>`;
}

function barList(host, items, { color, total }) {
  if (!items.length) {
    host.innerHTML = `<p class="empty">Nothing recorded in this range yet.</p>`;
    return;
  }
  const max = Math.max(...items.map((i) => i.value)) || 1;
  host.innerHTML = items.map((item) => {
    const pct = (item.value / max) * 100;
    const share = total ? ` · ${((item.value / total) * 100).toFixed(1)}%` : "";
    return `<div class="barrow" title="${item.label}${share}">
      <span class="name">${item.label}</span>
      <span class="bartrack"><span class="barfill" style="width:${pct.toFixed(2)}%;background:${color}"></span></span>
      <span class="num">${fmtFull(item.value)}</span>
    </div>`;
  }).join("");
}

/* ---------------------------------------------------------------- tiles */

function renderTiles(d) {
  const s = d.summary;
  const tiles = [
    {
      label: "Keystrokes", value: fmtFull(s.keystrokes),
      sub: deltaMarkup(s.change.keystrokes, RANGE_WORD[state.range]),
    },
    {
      label: "Clicks", value: fmtFull(s.clicks),
      sub: deltaMarkup(s.change.clicks, RANGE_WORD[state.range]),
    },
    {
      label: "Active time", value: s.active_label,
      sub: `${s.avg_active_per_day} per active day`,
    },
    {
      label: "Peak typing speed",
      value: `${s.peak_wpm.toFixed(0)} <span style="font-size:16px;color:var(--text-muted)">WPM</span>`,
      sub: `${s.keys_per_minute.toFixed(0)} keys/min average · ${fmtFull(s.words)} words`,
    },
    {
      label: "Keyboard vs mouse", value: `${s.keyboard_share.toFixed(0)}%`,
      sub: `keyboard share of all input`,
    },
    {
      label: "Correction rate", value: `${s.correction_rate.toFixed(1)}%`,
      sub: `${fmtFull(s.backspaces)} backspace / delete`,
    },
  ];
  $("#tiles").innerHTML = tiles.map((t) => `
    <div class="tile">
      <div class="label">${t.label}</div>
      <div class="value">${t.value}</div>
      <div class="sub">${t.sub}</div>
    </div>`).join("");
}

function renderInsights(d) {
  const host = $("#insights");
  if (!d.insights.length) { host.innerHTML = ""; return; }
  host.innerHTML = d.insights.map((i) => {
    const accent = i.direction === "down" ? "var(--series-2)" : "var(--series-1)";
    return `<article class="insight" style="border-left-color:${accent}">
      <h3>${i.title}</h3><p>${i.detail}</p></article>`;
  }).join("");
}

/* ---------------------------------------------------------------- charts */

function renderTrend(d) {
  const c1 = getComputedStyle(document.documentElement).getPropertyValue("--series-1").trim();
  const c2 = getComputedStyle(document.documentElement).getPropertyValue("--series-2").trim();
  const labels = d.daily.map((r) => r.day);
  const series = [
    { name: "Keystrokes", values: d.daily.map((r) => r.keystrokes || 0), color: c1 },
    { name: "Clicks", values: d.daily.map((r) => r.clicks || 0), color: c2 },
  ];

  $("#trendLegend").innerHTML = series.map((s) =>
    `<li><span class="swatch" style="background:${s.color}"></span>${s.name}</li>`).join("");

  lineChart($("#trendChart"), { labels, series, formatX: dayLabel });

  $("#trendTable").innerHTML = table(
    ["Date", "Keystrokes", "Clicks", "Scrolls", "Active"],
    d.daily.map((r) => [
      dayLabel(r.day, 0, true), fmtFull(r.keystrokes), fmtFull(r.clicks),
      fmtFull(r.scrolls), duration(r.active_seconds),
    ]),
  );
}

function renderHours(d) {
  const c1 = getComputedStyle(document.documentElement).getPropertyValue("--series-1").trim();
  const values = d.hourly.map((h) => h.keystrokes || 0);
  barChart($("#hourChart"), {
    labels: d.hourly.map((h) => h.hour),
    values,
    color: c1,
    formatLabel: (h) => (h % 3 === 0 ? hourLabel(h).replace(" ", "") : null),
    tipTitle: (h) => hourLabel(h),
  });
  $("#hourTable").innerHTML = table(
    ["Hour", "Keystrokes", "Clicks"],
    d.hourly.map((h) => [hourLabel(h.hour), fmtFull(h.keystrokes), fmtFull(h.clicks)]),
  );
}

function renderMatrix(d) {
  heatGrid($("#matrixChart"), {
    matrix: d.matrix,
    rowLabels: DOW,
    colLabels: Array.from({ length: 24 }, (_, h) => (h % 3 === 0 ? String(h) : null)),
    tipFor: (r, c, v) => ({
      title: `${DOW[r]} · ${hourLabel(c)}`,
      rows: [{ label: "Input events", value: fmtFull(v) }],
    }),
  });

  const max = Math.max(0, ...d.matrix.flat());
  $("#matrixScale").innerHTML =
    `<span>Less</span><span class="ramp">${
      rampSteps().map((c) => `<span style="background:${c}"></span>`).join("")
    }</span><span>More</span><span style="margin-left:auto">peak ${fmtFull(max)}</span>`;

  $("#matrixTable").innerHTML = table(
    ["Day", ...Array.from({ length: 24 }, (_, h) => String(h))],
    d.matrix.map((row, r) => [DOW[r], ...row.map((v) => fmtFull(v))]),
  );
}

/* ---------------------------------------------------------------- keyboard */

/* Shifted symbols count toward the physical key that produced them. */
const SHIFT_MAP = {
  "!": "1", "@": "2", "#": "3", $: "4", "%": "5", "^": "6", "&": "7", "*": "8",
  "(": "9", ")": "0", _: "-", "+": "=", "{": "[", "}": "]", "|": "\\", ":": ";",
  '"': "'", "<": ",", ">": ".", "?": "/", "~": "`",
};

const KEY_ROWS = [
  [["esc", "Esc", 1.6], ...Array.from({ length: 12 }, (_, i) => [`f${i + 1}`, `F${i + 1}`, 1])],
  [["`", "`", 1], ...["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"].map((k) => [k, k, 1]),
    ["-", "-", 1], ["=", "=", 1], ["backspace", "Bksp", 2]],
  [["tab", "Tab", 1.5], ...["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"].map((k) => [k, k.toUpperCase(), 1]),
    ["[", "[", 1], ["]", "]", 1], ["\\", "\\", 1.5]],
  [["caps_lock", "Caps", 1.8], ...["a", "s", "d", "f", "g", "h", "j", "k", "l"].map((k) => [k, k.toUpperCase(), 1]),
    [";", ";", 1], ["'", "'", 1], ["enter", "Enter", 2.2]],
  [["shift_l", "Shift", 2.4], ...["z", "x", "c", "v", "b", "n", "m"].map((k) => [k, k.toUpperCase(), 1]),
    [",", ",", 1], [".", ".", 1], ["/", "/", 1], ["shift_r", "Shift", 2.6]],
  [["ctrl_l", "Ctrl", 1.5], ["cmd", "Win", 1.25], ["alt_l", "Alt", 1.25], ["space", "Space", 6.5],
    ["alt_gr", "Alt", 1.25], ["cmd_r", "Win", 1.25], ["ctrl_r", "Ctrl", 1.5]],
];

function keyTotals(keys) {
  const totals = {};
  for (const row of keys) {
    const base = SHIFT_MAP[row.key] || row.key;
    totals[base] = (totals[base] || 0) + row.count;
  }
  return totals;
}

function renderKeyboard(d) {
  const totals = keyTotals(d.keys);
  const max = Math.max(0, ...Object.values(totals));
  const host = $("#kbd");
  host.innerHTML = "";

  for (const row of KEY_ROWS) {
    const rowNode = document.createElement("div");
    rowNode.className = "kbd-row";
    for (const [id, label, width] of row) {
      const count = totals[id] || 0;
      const key = document.createElement("div");
      key.className = "key" + (count ? "" : " inactive");
      key.style.flexGrow = String(width);
      key.style.background = rampColor(count, max);
      if (count) {
        // Keep the label legible against the darker end of the ramp.
        const strong = max > 0 && Math.sqrt(count / max) > 0.62;
        key.style.color = strong
          ? "var(--seq-ink-hi)"
          : "var(--text-primary)";
      }
      key.textContent = label;
      key.addEventListener("pointerenter", (evt) => showTip(evt, label, [
        { label: "Presses", value: fmtFull(count) },
        { label: "Share", value: max ? ((count / (Object.values(totals).reduce((a, b) => a + b, 0) || 1)) * 100).toFixed(2) + "%" : "0%" },
      ]));
      key.addEventListener("pointermove", positionTip);
      key.addEventListener("pointerleave", hideTip);
      rowNode.appendChild(key);
    }
    host.appendChild(rowNode);
  }

  $("#kbdScale").innerHTML =
    `<span>Less</span><span class="ramp">${
      rampSteps().map((c) => `<span style="background:${c}"></span>`).join("")
    }</span><span>More</span><span style="margin-left:auto">peak ${fmtFull(max)} presses</span>`;

  const sorted = Object.entries(totals).sort((a, b) => b[1] - a[1]);
  $("#kbdTable").innerHTML = sorted.length
    ? table(["Key", "Presses"], sorted.map(([k, v]) => [k, fmtFull(v)]))
    : `<p class="empty">Per-key detail is off, or nothing recorded yet.</p>`;
}

/* ---------------------------------------------------------------- lists */

function renderLists(d) {
  const css = getComputedStyle(document.documentElement);
  const c1 = css.getPropertyValue("--series-1").trim();
  const c2 = css.getPropertyValue("--series-2").trim();
  const c3 = css.getPropertyValue("--series-3").trim();
  const s = d.summary;

  const totalKeys = d.keys.reduce((a, k) => a + k.count, 0);
  barList($("#keyBars"),
    d.keys.slice(0, 12).map((k) => ({ label: k.label, value: k.count })),
    { color: c1, total: totalKeys });

  barList($("#appBars"),
    d.apps.map((a) => ({ label: a.app, value: a.keystrokes + a.clicks })),
    { color: c1 });

  barList($("#shortcutBars"),
    d.shortcuts.map((s2) => ({ label: s2.combo, value: s2.count })),
    { color: c1 });

  barList($("#mouseBars"), [
    { label: "Left click", value: s.left_clicks },
    { label: "Right click", value: s.right_clicks },
    { label: "Middle click", value: s.middle_clicks },
    { label: "Double click", value: s.double_clicks },
    { label: "Scroll", value: s.scrolls },
  ], { color: c1 });

  const metres = s.mouse_metres;
  $("#mouseKv").innerHTML = `
    <dt>Cursor distance</dt><dd>${metres >= 1000 ? (metres / 1000).toFixed(2) + " km" : metres.toFixed(0) + " m"}</dd>
    <dt>Clicks per active minute</dt><dd>${s.clicks_per_minute.toFixed(1)}</dd>
    <dt>Keys per active minute</dt><dd>${s.keys_per_minute.toFixed(1)}</dd>
    <dt>Shortcuts per 1,000 keys</dt><dd>${s.shortcut_rate.toFixed(1)}</dd>`;

  const r = d.records;
  const st = d.streaks;
  $("#recordsKv").innerHTML = `
    <dt>Busiest day</dt><dd>${r.best_day ? `${dayLabel(r.best_day.day, 0, true)} · ${fmtFull(r.best_day.keystrokes + r.best_day.clicks)}` : "—"}</dd>
    <dt>Busiest hour</dt><dd>${r.best_hour ? `${r.best_hour.bucket.slice(11)}:00 · ${fmtFull(r.best_hour.keystrokes + r.best_hour.clicks)}` : "—"}</dd>
    <dt>Fastest typing</dt><dd>${r.peak_wpm ? r.peak_wpm.toFixed(0) + " WPM" : "—"}</dd>
    <dt>Current streak</dt><dd>${st.current} day${st.current === 1 ? "" : "s"}</dd>
    <dt>Longest streak</dt><dd>${st.longest} day${st.longest === 1 ? "" : "s"}</dd>
    <dt>Days tracked</dt><dd>${st.total_active_days}</dd>
    <dt>Tracking since</dt><dd>${d.first_run ? dayLabel(d.first_run.slice(0, 10), 0, true) : "—"}</dd>`;

  $("#milestones").innerHTML = d.milestones.length
    ? d.milestones.map((m) =>
        `<span class="chip"><b>${fmt(m.threshold)}</b> ${m.kind} · ${m.achieved_at.slice(0, 10)}</span>`).join("")
    : `<p class="empty">No milestones yet — the first lands at 10,000 keystrokes.</p>`;

  void c2; void c3;
}

function renderCharts(d) {
  renderTrend(d);
  renderHours(d);
  renderMatrix(d);
  renderKeyboard(d);
  renderLists(d);
}

/* ---------------------------------------------------------------- data */

async function load(range = state.range) {
  state.range = range;
  const wrap = $(".wrap");
  wrap.classList.add("refreshing");   // hold the previous render, no skeleton flash
  try {
    const res = await fetch(`/api/data?range=${encodeURIComponent(range)}`);
    const d = await res.json();
    state.data = d;
    state.settings = d.settings;
    renderTiles(d);
    renderInsights(d);
    renderCharts(d);
    $("#rangeNote").textContent =
      d.summary.days_tracked
        ? `${d.start} → ${d.end} · ${d.summary.days_tracked} day${d.summary.days_tracked === 1 ? "" : "s"} with activity`
        : `${d.start} → ${d.end} · no activity recorded yet`;
    syncSettingsUi();
  } catch (err) {
    toast("Could not load data — is the tracker still running?");
  } finally {
    wrap.classList.remove("refreshing");
  }
}

async function pollLive() {
  try {
    const res = await fetch("/api/live");
    const live = await res.json();
    const dot = $("#liveDot");
    dot.className = "dot " + (live.paused ? "paused" : "rec");
    $("#liveText").textContent = live.paused
      ? "Paused"
      : `${fmtFull(live.keystrokes)} keys · ${fmtFull(live.clicks)} clicks today · ${live.wpm.toFixed(0)} WPM`;
    $("#pauseBtn").textContent = live.paused ? "Resume" : "Pause";
    state.settings.paused = live.paused;
    for (const m of live.new_milestones || []) {
      toast(`Milestone: ${fmtFull(m.threshold)} ${m.kind}!`);
      load();
    }
  } catch {
    $("#liveText").textContent = "Tracker offline";
    $("#liveDot").className = "dot paused";
  }
}

/* ---------------------------------------------------------------- settings */

function syncSettingsUi() {
  const s = state.settings || {};
  const map = {
    "#setPaused": "paused", "#setAutostart": "autostart",
    "#setKeyDetail": "track_key_detail", "#setApps": "track_apps",
    "#setShortcuts": "track_shortcuts", "#setOpenOnStart": "open_dashboard_on_start",
    "#setMilestoneNotify": "milestone_notifications",
  };
  for (const [sel, key] of Object.entries(map)) {
    const node = $(sel);
    if (node) node.checked = Boolean(s[key]);
  }
  const excluded = $("#setExcluded");
  if (excluded && document.activeElement !== excluded) {
    excluded.value = (s.excluded_apps || []).join(", ");
  }
}

async function saveSettings(patch) {
  const res = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  state.settings = await res.json();
  syncSettingsUi();
}

/* ---------------------------------------------------------------- wiring */

function init() {
  applyTheme(localStorage.getItem("kt-theme") || "system");

  $("#ranges").addEventListener("click", (evt) => {
    const btn = evt.target.closest("button[data-range]");
    if (!btn) return;
    for (const b of $("#ranges").querySelectorAll("button")) {
      b.setAttribute("aria-pressed", String(b === btn));
    }
    load(btn.dataset.range);
  });

  document.addEventListener("click", (evt) => {
    const exportBtn = evt.target.closest("[data-export]");
    if (exportBtn) {
      window.location.href = `/api/export?format=${exportBtn.dataset.export}&range=${state.range}`;
      return;
    }
    const toggle = evt.target.closest("[data-toggle]");
    if (toggle) {
      const name = toggle.dataset.toggle;
      const showTable = toggle.getAttribute("aria-pressed") !== "true";
      toggle.setAttribute("aria-pressed", String(showTable));
      toggle.textContent = showTable ? "Chart" : "Table";
      const chartId = { trend: "#trendChart", hour: "#hourChart", matrix: "#matrixChart", kbd: "#kbd" }[name];
      const tableId = { trend: "#trendTable", hour: "#hourTable", matrix: "#matrixTable", kbd: "#kbdTable" }[name];
      const chartNode = name === "kbd" ? $(chartId).parentElement : $(chartId);
      chartNode.classList.toggle("hidden", showTable);
      $(tableId).classList.toggle("hidden", !showTable);
      if (name === "trend") $("#trendLegend").classList.toggle("hidden", showTable);
      if (name === "matrix") $("#matrixScale").classList.toggle("hidden", showTable);
      if (name === "kbd") $("#kbdScale").classList.toggle("hidden", showTable);
    }
  });

  $("#themeBtn").addEventListener("click", cycleTheme);

  $("#pauseBtn").addEventListener("click", async () => {
    await saveSettings({ paused: !state.settings.paused });
    pollLive();
  });

  $("#settingsBtn").addEventListener("click", () => {
    syncSettingsUi();
    $("#settings").showModal();
  });
  $("#closeSettings").addEventListener("click", () => $("#settings").close());

  const checkboxes = {
    "#setPaused": "paused", "#setAutostart": "autostart",
    "#setKeyDetail": "track_key_detail", "#setApps": "track_apps",
    "#setShortcuts": "track_shortcuts", "#setOpenOnStart": "open_dashboard_on_start",
    "#setMilestoneNotify": "milestone_notifications",
  };
  for (const [sel, key] of Object.entries(checkboxes)) {
    $(sel).addEventListener("change", (evt) => saveSettings({ [key]: evt.target.checked }));
  }

  $("#setExcluded").addEventListener("change", (evt) => {
    saveSettings({ excluded_apps: evt.target.value.split(",").map((s) => s.trim()).filter(Boolean) });
    toast("Exclusion list updated");
  });

  $("#resetBtn").addEventListener("click", async () => {
    const answer = prompt('This permanently deletes every recorded statistic.\nType DELETE to confirm:');
    if (answer !== "DELETE") return;
    await fetch("/api/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: "DELETE" }),
    });
    toast("All data deleted");
    load();
  });

  // Re-render on OS theme change so chart colours follow the surface.
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (!document.documentElement.hasAttribute("data-theme") && state.data) renderCharts(state.data);
  });

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (state.data) renderCharts(state.data); }, 200);
  });

  load("30d");
  pollLive();
  setInterval(pollLive, 2500);
  setInterval(() => load(), 60000);   // keep charts fresh without hammering the DB
}

init();
