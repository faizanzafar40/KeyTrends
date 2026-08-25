/* Small SVG chart toolkit for the KeyTrends dashboard.
   Hand-rolled rather than pulled from a CDN so the dashboard keeps working
   with no network at all. Colours are read from CSS custom properties, so a
   theme change just needs a re-render. */

const SVGNS = "http://www.w3.org/2000/svg";

function el(name, attrs = {}) {
  const node = document.createElementNS(SVGNS, name);
  for (const [k, v] of Object.entries(attrs)) {
    if (v !== null && v !== undefined) node.setAttribute(k, String(v));
  }
  return node;
}

function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function fmt(n) {
  const v = Number(n) || 0;
  if (Math.abs(v) >= 1_000_000) return (v / 1_000_000).toFixed(v >= 10_000_000 ? 0 : 1) + "M";
  if (Math.abs(v) >= 10_000) return Math.round(v / 1000) + "k";
  return Math.round(v).toLocaleString();
}

export function fmtFull(n) {
  return (Math.round(Number(n) || 0)).toLocaleString();
}

/* Nice round axis maximum, so ticks land on readable numbers. */
function niceMax(value) {
  if (value <= 0) return 1;
  const exp = Math.floor(Math.log10(value));
  const base = Math.pow(10, exp);
  const scaled = value / base;
  const step = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 2.5 ? 2.5 : scaled <= 5 ? 5 : 10;
  return step * base;
}

/* ---------------------------------------------------------------- tooltip */

let tipNode = null;

function tip() {
  if (!tipNode) {
    tipNode = document.createElement("div");
    tipNode.className = "tooltip hidden";
    document.body.appendChild(tipNode);
  }
  return tipNode;
}

export function showTip(evt, title, rows) {
  const node = tip();
  node.innerHTML =
    `<div class="t-title">${title}</div>` +
    rows.map((r) =>
      `<div class="t-row">` +
      (r.color ? `<span class="swatch" style="background:${r.color}"></span>` : "") +
      `<span>${r.label}</span><b>${r.value}</b></div>`
    ).join("");
  node.classList.remove("hidden");
  positionTip(evt);
}

export function positionTip(evt) {
  const node = tip();
  const pad = 14;
  const rect = node.getBoundingClientRect();
  let x = evt.clientX + pad;
  let y = evt.clientY + pad;
  if (x + rect.width > window.innerWidth - 8) x = evt.clientX - rect.width - pad;
  if (y + rect.height > window.innerHeight - 8) y = evt.clientY - rect.height - pad;
  node.style.left = Math.max(8, x) + "px";
  node.style.top = Math.max(8, y) + "px";
}

export function hideTip() {
  if (tipNode) tipNode.classList.add("hidden");
}

/* ---------------------------------------------------------------- line chart */

/* series: [{ name, values:[], color }] -- 2px lines, selective endpoint labels,
   crosshair tooltip across the full plot height. */
export function lineChart(host, { labels, series, formatX }) {
  host.innerHTML = "";
  const W = 760, H = 250;
  const pad = { l: 52, r: 18, t: 14, b: 30 };
  const plotW = W - pad.l - pad.r;
  const plotH = H - pad.t - pad.b;

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  const gridColor = token("--grid");
  const axisColor = token("--axis");
  const muted = token("--text-muted");

  const peak = Math.max(1, ...series.flatMap((s) => s.values));
  const yMax = niceMax(peak * 1.05);
  const n = labels.length;
  const x = (i) => pad.l + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (v) => pad.t + plotH - (v / yMax) * plotH;

  // Horizontal gridlines + y ticks (solid hairlines, one shade off the surface).
  for (let i = 0; i <= 4; i++) {
    const value = (yMax / 4) * i;
    const yy = y(value);
    svg.appendChild(el("line", {
      x1: pad.l, x2: W - pad.r, y1: yy, y2: yy,
      stroke: i === 0 ? axisColor : gridColor, "stroke-width": 1,
    }));
    const label = el("text", {
      x: pad.l - 8, y: yy + 4, "text-anchor": "end",
      fill: muted, "font-size": 11, "font-variant-numeric": "tabular-nums",
    });
    label.textContent = fmt(value);
    svg.appendChild(label);
  }

  // X tick labels, thinned to avoid collisions. The final label is always drawn,
  // so drop any regular tick that would sit on top of it.
  const every = Math.max(1, Math.ceil(n / 8));
  labels.forEach((lab, i) => {
    if (i !== n - 1 && (i % every || n - 1 - i < every * 0.7)) return;
    const t = el("text", {
      x: x(i), y: H - 8, "text-anchor": i === n - 1 ? "end" : "middle",
      fill: muted, "font-size": 11,
    });
    t.textContent = formatX ? formatX(lab, i) : lab;
    svg.appendChild(t);
  });

  series.forEach((s, si) => {
    const pts = s.values.map((v, i) => [x(i), y(v)]);
    if (si === 0 && n > 1) {
      const area = `M${pts[0][0]},${pad.t + plotH} ` +
        pts.map((p) => `L${p[0]},${p[1]}`).join(" ") +
        ` L${pts[pts.length - 1][0]},${pad.t + plotH} Z`;
      svg.appendChild(el("path", { d: area, fill: s.color, opacity: 0.10 }));
    }
    svg.appendChild(el("path", {
      d: pts.map((p, i) => `${i ? "L" : "M"}${p[0]},${p[1]}`).join(" "),
      fill: "none", stroke: s.color, "stroke-width": 2,
      "stroke-linejoin": "round", "stroke-linecap": "round",
    }));
    // Direct-label the endpoint only -- never a number on every point.
    const last = s.values[s.values.length - 1];
    if (n > 1 && last > 0) {
      svg.appendChild(el("circle", {
        cx: x(n - 1), cy: y(last), r: 4,
        fill: s.color, stroke: token("--surface-1"), "stroke-width": 2,
      }));
    }
  });

  // Crosshair + hit layer.
  const crosshair = el("line", {
    y1: pad.t, y2: pad.t + plotH, stroke: axisColor, "stroke-width": 1, opacity: 0,
  });
  svg.appendChild(crosshair);
  const markers = series.map((s) => {
    const c = el("circle", {
      r: 5, fill: s.color, stroke: token("--surface-1"), "stroke-width": 2, opacity: 0,
    });
    svg.appendChild(c);
    return c;
  });

  const hit = el("rect", {
    x: pad.l, y: pad.t, width: plotW, height: plotH, fill: "transparent",
  });
  svg.appendChild(hit);

  const nearest = (evt) => {
    const box = svg.getBoundingClientRect();
    const px = ((evt.clientX - box.left) / box.width) * W;
    const ratio = (px - pad.l) / plotW;
    return Math.max(0, Math.min(n - 1, Math.round(ratio * (n - 1))));
  };

  const move = (evt) => {
    const i = nearest(evt);
    crosshair.setAttribute("x1", x(i));
    crosshair.setAttribute("x2", x(i));
    crosshair.setAttribute("opacity", 0.6);
    series.forEach((s, si) => {
      markers[si].setAttribute("cx", x(i));
      markers[si].setAttribute("cy", y(s.values[i]));
      markers[si].setAttribute("opacity", 1);
    });
    showTip(evt, formatX ? formatX(labels[i], i, true) : labels[i],
      series.map((s) => ({ color: s.color, label: s.name, value: fmtFull(s.values[i]) })));
  };

  hit.addEventListener("pointermove", move);
  hit.addEventListener("pointerdown", move);
  hit.addEventListener("pointerleave", () => {
    crosshair.setAttribute("opacity", 0);
    markers.forEach((m) => m.setAttribute("opacity", 0));
    hideTip();
  });

  host.appendChild(svg);
}

/* ---------------------------------------------------------------- bar chart */

/* Vertical bars, one series, one colour. 4px rounded top anchored to the
   baseline, 2px surface gap between neighbours. */
export function barChart(host, { labels, values, color, formatLabel, tipTitle }) {
  host.innerHTML = "";
  const W = 760, H = 220;
  const pad = { l: 52, r: 14, t: 12, b: 28 };
  const plotW = W - pad.l - pad.r;
  const plotH = H - pad.t - pad.b;

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  const gridColor = token("--grid");
  const axisColor = token("--axis");
  const muted = token("--text-muted");
  const yMax = niceMax(Math.max(1, ...values) * 1.05);

  for (let i = 0; i <= 4; i++) {
    const value = (yMax / 4) * i;
    const yy = pad.t + plotH - (value / yMax) * plotH;
    svg.appendChild(el("line", {
      x1: pad.l, x2: W - pad.r, y1: yy, y2: yy,
      stroke: i === 0 ? axisColor : gridColor, "stroke-width": 1,
    }));
    const t = el("text", {
      x: pad.l - 8, y: yy + 4, "text-anchor": "end", fill: muted,
      "font-size": 11, "font-variant-numeric": "tabular-nums",
    });
    t.textContent = fmt(value);
    svg.appendChild(t);
  }

  const slot = plotW / values.length;
  const barW = Math.max(3, slot - 2); // 2px surface gap between bars

  values.forEach((v, i) => {
    const h = (v / yMax) * plotH;
    const bx = pad.l + i * slot + (slot - barW) / 2;
    const by = pad.t + plotH - h;
    // Hit target spans the full column height so short bars stay easy to hover.
    const hit = el("rect", {
      x: bx - 1, y: pad.t, width: barW + 2, height: plotH, fill: "transparent",
    });
    const bar = el("rect", {
      x: bx, y: h > 0 ? by : pad.t + plotH - 1, width: barW,
      height: h > 0 ? h : 1, rx: Math.min(4, barW / 2), fill: color,
    });
    if (h <= 0) bar.setAttribute("opacity", 0.28);

    const enter = (evt) => {
      bar.setAttribute("opacity", h > 0 ? 0.78 : 0.28);
      showTip(evt, tipTitle ? tipTitle(labels[i], i) : String(labels[i]),
        [{ color, label: "Keystrokes", value: fmtFull(v) }]);
    };
    hit.addEventListener("pointerenter", enter);
    hit.addEventListener("pointermove", positionTip);
    hit.addEventListener("pointerleave", () => {
      bar.setAttribute("opacity", h > 0 ? 1 : 0.28);
      hideTip();
    });

    svg.appendChild(bar);
    svg.appendChild(hit);

    if (formatLabel) {
      const text = formatLabel(labels[i], i);
      if (text !== null) {
        const t = el("text", {
          x: bx + barW / 2, y: H - 8, "text-anchor": "middle", fill: muted, "font-size": 11,
        });
        t.textContent = text;
        svg.appendChild(t);
      }
    }
  });

  host.appendChild(svg);
}

/* ---------------------------------------------------------------- heat grid */

const RAMP = ["--seq-1", "--seq-2", "--seq-3", "--seq-4", "--seq-5", "--seq-6", "--seq-7"];

/* Square-root scaling spreads activity data across the ramp; raw linear
   scaling leaves almost every cell in the palest step. */
export function rampColor(value, max) {
  if (!value || max <= 0) return token("--seq-0");
  const t = Math.sqrt(value / max);
  const idx = Math.min(RAMP.length - 1, Math.max(0, Math.ceil(t * RAMP.length) - 1));
  return token(RAMP[idx]);
}

export function rampSteps() {
  return [token("--seq-0"), ...RAMP.map(token)];
}

export function heatGrid(host, { matrix, rowLabels, colLabels, tipFor }) {
  host.innerHTML = "";
  const rows = matrix.length;
  const cols = matrix[0].length;
  const cell = 26, gap = 2, labelW = 42, labelH = 18;
  const W = labelW + cols * (cell + gap);
  const H = labelH + rows * (cell + gap);

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  const muted = token("--text-muted");
  const max = Math.max(0, ...matrix.flat());

  colLabels.forEach((lab, c) => {
    if (lab === null) return;
    const t = el("text", {
      x: labelW + c * (cell + gap) + cell / 2, y: 12,
      "text-anchor": "middle", fill: muted, "font-size": 10,
    });
    t.textContent = lab;
    svg.appendChild(t);
  });

  rowLabels.forEach((lab, r) => {
    const t = el("text", {
      x: labelW - 8, y: labelH + r * (cell + gap) + cell / 2 + 4,
      "text-anchor": "end", fill: muted, "font-size": 11,
    });
    t.textContent = lab;
    svg.appendChild(t);
  });

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const v = matrix[r][c];
      const rect = el("rect", {
        x: labelW + c * (cell + gap), y: labelH + r * (cell + gap),
        width: cell, height: cell, rx: 4, fill: rampColor(v, max),
      });
      rect.addEventListener("pointerenter", (evt) => {
        rect.setAttribute("stroke", token("--text-primary"));
        rect.setAttribute("stroke-width", 1.5);
        const info = tipFor(r, c, v);
        showTip(evt, info.title, info.rows);
      });
      rect.addEventListener("pointermove", positionTip);
      rect.addEventListener("pointerleave", () => {
        rect.removeAttribute("stroke");
        hideTip();
      });
      svg.appendChild(rect);
    }
  }

  host.appendChild(svg);
}
