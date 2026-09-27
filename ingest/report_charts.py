"""Client-side charts for the HTML report (Observable Plot, rendered in the browser).

The report embeds its data as JSON and this module renders it into SVG, so every
chart has hover tooltips and follows the page's light/dark tokens. The tables in
the report carry the same numbers, so nothing depends on hovering or on the CDN.

Kept as a plain string (not an f-string) so the JavaScript braces need no escaping.
"""

PLOT_MODULE = "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6/+esm"

SCRIPT = """
import * as Plot from "__PLOT_MODULE__";

const data = JSON.parse(document.getElementById("report-data").textContent);
const DAY = 86400000;

function tokens() {
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(name).trim();
  return {
    surface: v("--surface"), ink: v("--text-primary"), secondary: v("--text-secondary"),
    muted: v("--text-muted"), grid: v("--grid"), baseline: v("--baseline"),
    s1: v("--series-1"), s2: v("--series-2"), rampLo: v("--ramp-lo"), rampHi: v("--ramp-hi"),
  };
}

const eur = (x) => (x == null || Number.isNaN(x) ? "–" : `€${x.toFixed(2)}`);
const two = (n) => String(n).padStart(2, "0");

function frame(t, width, height, extra = {}) {
  return {
    width, height, marginLeft: 48, marginRight: 16, marginTop: 16, marginBottom: 32,
    style: { background: "transparent", color: t.secondary, fontSize: "12px",
             fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif" },
    ...extra,
  };
}

const charts = {
  week(el, t, width) {
    const rows = data.week.rows;
    return Plot.plot(frame(t, width, 260, {
      x: { label: null, domain: [0, 167], ticks: data.week.ticks,
           tickFormat: (i) => data.week.day_names[Math.round(i / 24)] },
      y: { label: null, grid: true, nice: true },
      marks: [
        Plot.ruleY([0], { stroke: t.baseline }),
        Plot.lineY(rows, { x: "i", y: "previous", stroke: t.muted, strokeWidth: 2 }),
        Plot.lineY(rows, { x: "i", y: "current", stroke: t.s1, strokeWidth: 2 }),
        Plot.ruleX(rows, Plot.pointerX({ x: "i", stroke: t.muted, strokeOpacity: 0.6 })),
        Plot.dot(rows, Plot.pointerX({ x: "i", y: "current", r: 4, fill: t.s1,
                                       stroke: t.surface, strokeWidth: 2 })),
        Plot.tip(rows, Plot.pointerX({
          x: "i", y: "current",
          title: (d) => `${d.label}\\nthis week  ${eur(d.current)}\\nlast week  ${eur(d.previous)}`,
        })),
      ],
    }));
  },

  fingerprint(el, t, width) {
    const start = Date.parse(data.fingerprint.start + "T00:00:00Z");
    const cells = data.fingerprint.rows.map(([day, hour, price]) => ({
      x1: new Date(start + day * DAY), x2: new Date(start + (day + 1) * DAY),
      hour, price,
    }));
    const positive = cells.filter((d) => d.price >= 0);
    const negative = cells.filter((d) => d.price < 0);
    return Plot.plot(frame(t, width, 330, {
      x: { type: "utc", label: null },
      y: { domain: [0, 24], reverse: true, label: null,
           ticks: [0, 6, 12, 18], tickFormat: (h) => `${two(h)}:00` },
      color: { type: "linear", domain: [0, data.fingerprint.p98], range: [t.rampLo, t.rampHi],
               interpolate: "lab", clamp: true },
      marks: [
        Plot.rect(positive, { x1: "x1", x2: "x2", y1: "hour", y2: (d) => d.hour + 1,
                              fill: "price", shapeRendering: "crispEdges" }),
        Plot.rect(negative, { x1: "x1", x2: "x2", y1: "hour", y2: (d) => d.hour + 1,
                              fill: t.s1, shapeRendering: "crispEdges" }),
        Plot.tip(cells, Plot.pointer({
          x: (d) => new Date((+d.x1 + +d.x2) / 2), y: (d) => d.hour + 0.5,
          title: (d) => `${d.x1.toISOString().slice(0, 10)} ${two(d.hour)}:00\\n${eur(d.price)}`
            + (d.price < 0 ? "  (below zero)" : ""),
        })),
      ],
    }));
  },

  profile(el, t, width) {
    const rows = data.profile;
    const wide = rows.filter((d) => d.kind === "weekday").map((d) => ({
      hour: d.hour, weekday: d.price,
      weekend: rows.find((r) => r.kind === "weekend" && r.hour === d.hour)?.price,
    }));
    // End labels: the higher line's label sits above its end, the lower one's below,
    // so the two never overprint when the lines finish close together.
    const ends = ["weekday", "weekend"].map((kind) => rows.filter((d) => d.kind === kind).at(-1));
    const [upper, lower] = ends[0].price >= ends[1].price ? ends : [ends[1], ends[0]];
    const endLabel = (d, dy) =>
      Plot.text([d], { x: "hour", y: "price", text: "kind", dx: 8, dy, textAnchor: "start",
                       fill: t.secondary });
    return Plot.plot(frame(t, width, 260, {
      marginRight: 72,
      x: { label: null, domain: [0, 23], insetLeft: 16,
           ticks: width < 560 ? [0, 6, 12, 18] : [0, 3, 6, 9, 12, 15, 18, 21],
           tickFormat: (h) => `${two(h)}:00` },
      y: { label: null, grid: true, nice: true },
      marks: [
        Plot.ruleY([0], { stroke: t.baseline }),
        Plot.lineY(rows, { x: "hour", y: "price", z: "kind",
                           stroke: (d) => (d.kind === "weekday" ? t.s1 : t.s2), strokeWidth: 2 }),
        endLabel(upper, -9),
        endLabel(lower, 9),
        Plot.ruleX(wide, Plot.pointerX({ x: "hour", stroke: t.muted, strokeOpacity: 0.6 })),
        Plot.tip(wide, Plot.pointerX({
          x: "hour", y: "weekday",
          title: (d) =>
            `${two(d.hour)}:00\\nweekday  ${eur(d.weekday)}\\nweekend  ${eur(d.weekend)}`,
        })),
      ],
    }));
  },

  negative(el, t, width) {
    const rows = data.monthly;
    const band = (width - 64) / Math.max(rows.length, 1);
    const inset = Math.max(1, (band - 24) / 2);
    const peak = rows.reduce((a, b) => (b.negative_hours > a.negative_hours ? b : a), rows[0]);
    // Label every k-th month so "Aug 2025"-wide labels never overprint.
    const step = Math.max(1, Math.ceil((rows.length * 64) / Math.max(width - 64, 1)));
    const ticks = rows.filter((_, i) => i % step === 0).map((d) => d.month);
    return Plot.plot(frame(t, width, 240, {
      x: { label: null, domain: rows.map((d) => d.month), ticks, insetLeft: 24,
           tickFormat: (m) => data.month_labels[m] },
      y: { label: null, grid: true, nice: true },
      marks: [
        Plot.barY(rows, { x: "month", y: "negative_hours", fill: t.s1,
                          insetLeft: inset, insetRight: inset, rx: 4 }),
        Plot.ruleY([0], { stroke: t.baseline }),
        Plot.text([peak], { x: "month", y: "negative_hours", text: (d) => `${d.negative_hours} h`,
                            dy: -8, fill: t.ink }),
        Plot.tip(rows, Plot.pointerX({
          x: "month", y: "negative_hours",
          title: (d) => `${data.month_labels[d.month]}\\n${d.negative_hours} hours below €0\\n`
            + `avg price ${eur(d.avg_price)}`,
        })),
      ],
    }));
  },

  wind(el, t, width) {
    const rows = data.wind.rows;
    return Plot.plot(frame(t, width, 300, {
      x: { label: null, grid: true, nice: true, insetLeft: 16, tickFormat: (w) => `${w} m/s` },
      y: { label: null, grid: true, nice: true },
      marks: [
        Plot.ruleY([0], { stroke: t.baseline }),
        Plot.dot(rows, { x: "wind", y: "price", r: 3, fill: t.s1, fillOpacity: 0.45,
                         stroke: t.surface, strokeWidth: 1 }),
        Plot.linearRegressionY(rows, { x: "wind", y: "price", stroke: t.ink, strokeWidth: 2,
                                       fill: t.muted, fillOpacity: 0.12 }),
        Plot.tip(rows, Plot.pointer({
          x: "wind", y: "price",
          title: (d) => `${d.date}\\n${eur(d.price)} at ${d.wind.toFixed(1)} m/s`,
        })),
      ],
    }));
  },

  topics(el, t, width) {
    const rows = data.topics;
    return Plot.plot(frame(t, width, 36 + rows.length * 30, {
      marginLeft: 170, marginRight: 40,
      x: { label: null, grid: true },
      y: { label: null, domain: rows.map((d) => d.topic) },
      marks: [
        Plot.barX(rows, { x: "headlines", y: "topic", fill: t.s1, insetTop: 5, insetBottom: 5,
                          rx: 4 }),
        Plot.ruleX([0], { stroke: t.baseline }),
        Plot.text(rows, { x: "headlines", y: "topic", text: "headlines", dx: 6,
                          textAnchor: "start", fill: t.ink }),
      ],
    }));
  },
};

function render() {
  const t = tokens();
  for (const [name, draw] of Object.entries(charts)) {
    const el = document.getElementById(`chart-${name}`);
    if (!el || (name === "topics" && !data.topics.length)) continue;
    el.replaceChildren(draw(el, t, Math.max(el.clientWidth, 280)));
  }
}

render();
let pending;
addEventListener("resize", () => { clearTimeout(pending); pending = setTimeout(render, 150); });
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
""".replace("__PLOT_MODULE__", PLOT_MODULE)
