#!/usr/bin/env python3
"""Build docs/index.html - a self-contained, shareable copy of the dashboard.

    python src/export_static.py     (run after load_data.py)

The Dash app needs a running Python server, which makes it awkward to link to
from a README. This writes a single HTML file that GitHub Pages can serve for
free and that never goes to sleep.

It stays genuinely interactive by pre-computing every cohort the selector can
reach -- condition x treatment x sample type, with the box statistics and the
Mann-Whitney p-values already worked out -- and embedding the result as JSON.
The page then redraws from that lookup in the browser. The arithmetic is still
done here, in Python, by the same functions the Dash app calls, so the two
pages cannot disagree.
"""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd

from config import (
    ALPHA,
    DOCS_DIR,
    POPULATION_COLOURS,
    POPULATIONS,
    RESPONSE_COLOURS,
    RESPONSE_LABELS,
    SEX_LABELS,
    STATIC_DASHBOARD,
)
from queries import box_statistics, connect, filter_options, load_cohort, test_populations


def build_payload() -> dict:
    with connect() as connection:
        options = filter_options(connection)
        everything = load_cohort(connection)

    cohorts: dict[str, dict] = {}

    combinations = [
        (condition, treatment, sample_type)
        for condition in options["condition"]
        for treatment in options["treatment"]
        for sample_type in options["sample_type"]
    ]

    for condition, treatment, sample_type in combinations:
        frame = everything[
            (everything["condition"] == condition)
            & (everything["treatment"] == treatment)
            & (everything["sample_type"] == sample_type)
        ]
        if frame.empty:
            continue

        key = f"{condition}|{treatment}|{sample_type}"
        cohorts[key] = summarise(frame)

    return {
        "generated": date.today().isoformat(),
        "alpha": ALPHA,
        "populations": POPULATIONS,
        "population_colours": POPULATION_COLOURS,
        "response_colours": RESPONSE_COLOURS,
        "response_labels": {k: v for k, v in RESPONSE_LABELS.items() if k},
        "options": {
            "condition": options["condition"],
            "treatment": options["treatment"],
            "sample_type": options["sample_type"],
        },
        "cohorts": cohorts,
        "totals": {
            "samples": int(everything["sample_id"].nunique()),
            "subjects": int(everything["subject_id"].nunique()),
            "projects": int(everything["project_id"].nunique()),
        },
    }


def summarise(frame: pd.DataFrame) -> dict:
    """Everything the static page needs for one cohort."""
    timepoints = sorted(int(t) for t in frame["timepoint"].dropna().unique())
    results = test_populations(frame)

    samples = frame[["sample_id", "subject_id", "response", "sex", "project_id", "timepoint"]].drop_duplicates()
    subjects = samples[["subject_id", "response", "sex"]].drop_duplicates()

    # Box statistics per population, day and response group.
    boxes: dict = {}
    composition: dict = {}
    for population in POPULATIONS:
        boxes[population] = {}
        composition[population] = {}
        for timepoint in timepoints:
            slice_ = frame[
                (frame["population"] == population) & (frame["timepoint"] == timepoint)
            ]
            boxes[population][str(timepoint)] = {
                response: box_statistics(
                    slice_.loc[slice_["response"] == response, "percentage"].to_numpy()
                )
                for response in ("yes", "no")
            }
            composition[population][str(timepoint)] = {
                response: float(
                    np.mean(
                        slice_.loc[slice_["response"] == response, "percentage"].to_numpy()
                    )
                )
                if (slice_["response"] == response).any()
                else 0.0
                for response in ("yes", "no")
            }

    statistics = []
    if not results.empty:
        for row in results.itertuples():
            statistics.append(
                {
                    "timepoint": int(row.timepoint),
                    "population": row.population,
                    "n_responders": int(row.n_responders),
                    "n_non_responders": int(row.n_non_responders),
                    "median_responders": none_if_nan(row.median_responders),
                    "median_non_responders": none_if_nan(row.median_non_responders),
                    "median_difference": none_if_nan(row.median_difference),
                    "p_value": none_if_nan(row.p_value),
                    "significant": bool(row.significant),
                }
            )

    baseline = samples[samples["timepoint"] == 0]
    baseline_subjects = baseline[["subject_id", "response", "sex"]].drop_duplicates()

    return {
        "timepoints": timepoints,
        "counts": {
            "samples": int(samples["sample_id"].nunique()),
            "subjects": int(subjects["subject_id"].nunique()),
            "responders": int((subjects["response"] == "yes").sum()),
            "non_responders": int((subjects["response"] == "no").sum()),
        },
        "composition": composition,
        "boxes": boxes,
        "statistics": statistics,
        "baseline": {
            "by_project": count_map(baseline, "project_id", "sample_id"),
            "by_response": label_map(
                count_map(baseline_subjects, "response", "subject_id"), RESPONSE_LABELS
            ),
            "by_sex": label_map(
                count_map(baseline_subjects, "sex", "subject_id"), SEX_LABELS
            ),
        },
    }


def none_if_nan(value) -> float | None:
    value = float(value)
    return None if np.isnan(value) else round(value, 6)


def count_map(frame: pd.DataFrame, key: str, unique_on: str) -> dict:
    if frame.empty:
        return {}
    grouped = frame.groupby(key, dropna=False)[unique_on].nunique().sort_index()
    return {str(index): int(value) for index, value in grouped.items()}


def label_map(counts: dict, labels: dict) -> dict:
    return {labels.get(key, key): value for key, value in counts.items()}


# --------------------------------------------------------------------------
# The page
# --------------------------------------------------------------------------

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cell population explorer</title>
<meta name="description" content="Relative frequencies of five immune cell populations across three clinical trial projects, compared between treatment responders and non-responders.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
__CSS__
</style>
</head>
<body>
<div class="shell">
  <aside class="rail">
    <div class="brand">
      <div class="eyebrow">Immune profiling</div>
      <h1>Cell population<br>explorer</h1>
      <p class="lede">Relative frequencies of five populations across three trial projects.</p>
    </div>

    <div class="controls">
      <div class="eyebrow">Gate on</div>
      <div class="field"><label for="condition">Condition</label><select id="condition"></select></div>
      <div class="field"><label for="treatment">Treatment</label><select id="treatment"></select></div>
      <div class="field"><label for="sample_type">Sample type</label><select id="sample_type"></select></div>
    </div>

    <div class="cascade-block">
      <div class="eyebrow">Samples surviving each gate</div>
      <div id="cascade"></div>
    </div>

    <p class="rail-foot">
      A published snapshot. The full version, with project, sex and day
      filters and a live per-sample table, runs locally with
      <code>make dashboard</code>.
    </p>
  </aside>

  <main class="main">
    <header class="masthead">
      <p class="cohort-sentence" id="sentence"></p>
      <div class="tiles" id="tiles"></div>
    </header>

    <section class="card">
      <div class="card-head">
        <h2>Average sample composition</h2>
        <p class="note">Mean relative frequency of each population, stacked to 100%. Each bar is the average sample in that group.</p>
      </div>
      <div id="composition"></div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>Responders against non-responders</h2>
        <p class="note">Mann-Whitney U, two-sided, run separately for every population on every day. A star marks p &lt; __ALPHA__.</p>
      </div>
      <div class="verdict" id="verdict"></div>
      <div id="boxplots"></div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>How the gap moves over treatment</h2>
        <p class="note">Responder median minus non-responder median, in percentage points. A gap that grows across days is worth more than one low p-value.</p>
      </div>
      <div id="divergence"></div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>Every comparison in this cohort</h2>
        <p class="note">Medians, differences and p-values for each population on each day.</p>
      </div>
      <div id="stats"></div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>Baseline subset, day 0</h2>
        <p class="note">Projects are counted in samples; response and sex describe a patient, so those are counted in subjects.</p>
      </div>
      <div class="breakdowns">
        <div class="breakdown"><h3>Samples per project</h3><div id="by-project"></div></div>
        <div class="breakdown"><h3>Subjects by response</h3><div id="by-response"></div></div>
        <div class="breakdown"><h3>Subjects by sex</h3><div id="by-sex"></div></div>
      </div>
    </section>

    <footer class="page-footer">
      <span>Data: cell-count.csv</span><span>·</span>
      <span>Built __GENERATED__</span><span>·</span>
      <span>Significance threshold p &lt; __ALPHA__</span>
    </footer>
  </main>
</div>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
__JS__
</script>
</body>
</html>
"""

EXTRA_CSS = """
select {
  width: 100%;
  padding: 7px 10px;
  font-family: var(--body);
  font-size: 13px;
  color: var(--ink);
  background: var(--paper);
  border: 1px solid var(--rule);
  border-radius: 3px;
  appearance: none;
  background-image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath fill='%2362708a' d='M0 0h10L5 6z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
  cursor: pointer;
}
select:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
select:hover { border-color: var(--accent); }
.rail-foot { font-size: 11.5px; color: var(--faint); line-height: 1.5; margin: 18px 0 0; }
.rail-foot code { font-family: var(--mono); font-size: 11px; color: var(--muted); }
.stats-table { width: 100%; border-collapse: collapse; font-family: var(--mono); font-size: 12px; }
.stats-table th {
  font-size: 10px; letter-spacing: 0.09em; text-transform: uppercase; font-weight: 500;
  color: var(--muted); text-align: right; padding: 8px 12px; border-bottom: 1px solid #c9d2e0;
}
.stats-table td { text-align: right; padding: 8px 12px; border-bottom: 1px solid var(--rule-soft); font-variant-numeric: tabular-nums; }
.stats-table th:nth-child(2), .stats-table td:nth-child(2) { text-align: left; font-family: var(--body); }
.stats-table tr.hit td { background: var(--accent-wash); font-weight: 500; }
.table-scroll { overflow-x: auto; }
"""

JS = """
const DATA = JSON.parse(document.getElementById("payload").textContent);
const POPS = DATA.populations;
const POP_KEYS = Object.keys(POPS);
const PC = DATA.population_colours;
const RC = DATA.response_colours;
const ALPHA = DATA.alpha;

const INK = "#0e1726", MUTED = "#62708a", RULE = "#dde3ec";
const FONT = "IBM Plex Sans, sans-serif";
const MONO = "IBM Plex Mono, monospace";

const BASE = {
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  font: { family: FONT, size: 12, color: INK },
  margin: { l: 8, r: 8, t: 32, b: 8 },
  hoverlabel: { font: { family: MONO, size: 12 }, bgcolor: "#fff", bordercolor: RULE }
};
const AXIS = {
  showgrid: true, gridcolor: RULE, zeroline: false, linecolor: RULE,
  ticks: "outside", tickcolor: RULE, ticklen: 4,
  tickfont: { family: MONO, size: 11, color: MUTED }
};
const CONFIG = { displayModeBar: false, responsive: true };

function fill(id, values, selected) {
  const el = document.getElementById(id);
  el.innerHTML = "";
  values.forEach(v => {
    const option = document.createElement("option");
    option.value = v; option.textContent = v;
    if (v === selected) option.selected = true;
    el.appendChild(option);
  });
}

function currentKey() {
  return ["condition", "treatment", "sample_type"]
    .map(id => document.getElementById(id).value).join("|");
}

function commas(n) { return n.toLocaleString("en-US"); }

/* ---------------------------------------------------------------- cascade */
function drawCascade(key, cohort) {
  const [condition, treatment, sampleType] = key.split("|");
  const total = DATA.totals.samples;
  const stages = [
    { label: "All samples", value: commas(DATA.totals.subjects) + " subjects", n: total, open: true },
    { label: "Condition", value: condition, n: cohort ? cohort.gates.condition : 0 },
    { label: "Treatment", value: treatment, n: cohort ? cohort.gates.treatment : 0 },
    { label: "Sample type", value: sampleType, n: cohort ? cohort.counts.samples : 0 }
  ];
  document.getElementById("cascade").innerHTML = stages.map(s => `
    <div class="gate${s.open ? " gate-open" : ""}">
      <div class="gate-head">
        <span class="gate-label">${s.label}</span>
        <span class="gate-count">${commas(s.n)}</span>
      </div>
      <div class="gate-track"><div class="gate-fill" style="width:${(100 * s.n / total).toFixed(3)}%"></div></div>
      <span class="gate-value">${s.value}</span>
    </div>`).join("");
}

/* ------------------------------------------------------------------ tiles */
function drawTiles(cohort) {
  const tiles = [
    ["Subjects", cohort.counts.subjects, null],
    ["Samples", cohort.counts.samples, null],
    ["Responders", cohort.counts.responders, RC.yes],
    ["Non-responders", cohort.counts.non_responders, RC.no]
  ];
  document.getElementById("tiles").innerHTML = tiles.map(([label, value, colour]) => `
    <div class="tile"${colour ? ` style="--tile-accent:${colour}"` : ""}>
      <span class="tile-label"${colour ? ` style="color:${colour}"` : ""}>${label}</span>
      <span class="tile-value">${commas(value)}</span>
    </div>`).join("");
}

/* ------------------------------------------------------------ composition */
function drawComposition(cohort) {
  const rows = [];
  cohort.timepoints.forEach(t => ["yes", "no"].forEach(r => rows.push([t, r])));
  const labels = rows.map(([t, r]) => `Day ${t} &nbsp;·&nbsp; ${DATA.response_labels[r]}`);

  const traces = POP_KEYS.map(pop => {
    const x = rows.map(([t, r]) => cohort.composition[pop][t][r]);
    return {
      type: "bar", orientation: "h", y: labels, x,
      name: POPS[pop], marker: { color: PC[pop], line: { width: 0 } },
      text: x.map(v => v.toFixed(1)), textposition: "inside", insidetextanchor: "middle",
      textfont: { family: MONO, size: 10, color: "#fff" },
      hovertemplate: `%{y}<br>${POPS[pop]}: %{x:.2f}%<extra></extra>`
    };
  });

  Plotly.react("composition", traces, Object.assign({}, BASE, {
    barmode: "stack", bargap: 0.32, height: 90 + 42 * rows.length,
    legend: { orientation: "h", yanchor: "bottom", y: 1.02, x: 0, font: { family: MONO, size: 11 } },
    xaxis: Object.assign({}, AXIS, { range: [0, 100], ticksuffix: "%" }),
    yaxis: { showgrid: false, linecolor: RULE, autorange: "reversed", tickfont: { family: MONO, size: 11, color: INK } }
  }), CONFIG);
}

/* --------------------------------------------------------------- boxplots */
function drawBoxplots(cohort) {
  const n = POP_KEYS.length;
  const gap = 0.035;
  const width = (1 - gap * (n - 1)) / n;
  const traces = [], layout = Object.assign({}, BASE, {
    height: 380, boxmode: "group", showlegend: true,
    margin: { l: 8, r: 8, t: 52, b: 52 },
    legend: { orientation: "h", yanchor: "bottom", y: 1.10, x: 0, font: { family: MONO, size: 11 } },
    annotations: []
  });

  POP_KEYS.forEach((pop, i) => {
    const axis = i === 0 ? "" : String(i + 1);
    const start = i * (width + gap);
    layout["xaxis" + axis] = Object.assign({}, AXIS, {
      showgrid: false, domain: [start, start + width], anchor: "y" + axis
    });
    layout["yaxis" + axis] = Object.assign({}, AXIS, {
      ticksuffix: "%", domain: [0, 1], anchor: "x" + axis
    });

    ["yes", "no"].forEach(response => {
      const days = [], stats = [];
      cohort.timepoints.forEach(t => {
        const box = cohort.boxes[pop][t][response];
        if (!box || !box.n) return;
        days.push("Day " + t); stats.push(box);
      });
      if (!days.length) return;
      traces.push({
        type: "box", x: days,
        q1: stats.map(s => s.q1), median: stats.map(s => s.median), q3: stats.map(s => s.q3),
        lowerfence: stats.map(s => s.min), upperfence: stats.map(s => s.max),
        mean: stats.map(s => s.mean), boxmean: true,
        name: DATA.response_labels[response], legendgroup: response, showlegend: i === 0,
        marker: { color: RC[response] }, fillcolor: RC[response], opacity: 0.62,
        line: { width: 1.2, color: RC[response] }, width: 0.34,
        xaxis: "x" + axis, yaxis: "y" + axis,
        hovertemplate: `${DATA.response_labels[response]}<br>%{x}<br>median %{median:.2f}%<extra></extra>`
      });
    });

    layout.annotations.push({
      text: POPS[pop], xref: "x" + axis + " domain", yref: "paper",
      x: 0.5, y: 1.0, showarrow: false, font: { family: FONT, size: 12, color: INK }
    });

    const marks = cohort.timepoints.map(t => {
      const row = cohort.statistics.find(s => s.timepoint === t && s.population === pop);
      if (!row || row.p_value === null) return "n/a";
      return "p=" + row.p_value.toFixed(3) + (row.significant ? " *" : "");
    });
    layout.annotations.push({
      text: marks.join("&nbsp;&nbsp;"), xref: "x" + axis + " domain", yref: "paper",
      x: 0.5, y: -0.16, showarrow: false,
      font: { family: MONO, size: 9.5, color: marks.some(m => m.includes("*")) ? INK : MUTED }
    });
  });

  layout.yaxis.title = { text: "Relative frequency", font: { size: 11, color: MUTED } };
  Plotly.react("boxplots", traces, layout, CONFIG);
}

/* ------------------------------------------------------------- divergence */
function drawDivergence(cohort) {
  const traces = POP_KEYS.map(pop => {
    const rows = cohort.statistics.filter(s => s.population === pop)
      .sort((a, b) => a.timepoint - b.timepoint);
    return {
      type: "scatter", mode: "lines+markers", name: POPS[pop],
      x: rows.map(r => "Day " + r.timepoint),
      y: rows.map(r => r.median_difference),
      customdata: rows.map(r => r.p_value),
      line: { color: PC[pop], width: 2.2 },
      marker: {
        color: PC[pop], size: rows.map(r => r.significant ? 11 : 7),
        symbol: rows.map(r => r.significant ? "star" : "circle"), line: { width: 0 }
      },
      hovertemplate: `${POPS[pop]}<br>%{x}<br>%{y:+.2f} points<br>p = %{customdata:.4f}<extra></extra>`
    };
  });

  Plotly.react("divergence", traces, Object.assign({}, BASE, {
    height: 300,
    legend: { orientation: "h", yanchor: "bottom", y: 1.04, x: 0, font: { family: MONO, size: 11 } },
    shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: 0, y1: 0, line: { color: RULE, width: 1.5 } }],
    xaxis: Object.assign({}, AXIS, { showgrid: false }),
    yaxis: Object.assign({}, AXIS, {
      ticksuffix: " pp",
      title: { text: "Responder − non-responder", font: { size: 11, color: MUTED } }
    })
  }), CONFIG);
}

/* ---------------------------------------------------------------- verdict */
function drawVerdict(cohort) {
  const target = document.getElementById("verdict");
  const hits = cohort.statistics.filter(s => s.significant);
  if (!cohort.statistics.length) {
    target.innerHTML = `<p class="caveat">No response is recorded for this cohort, so there is nothing to compare.</p>`;
    return;
  }
  if (!hits.length) {
    const scored = cohort.statistics.filter(s => s.p_value !== null)
      .sort((a, b) => a.p_value - b.p_value);
    const best = scored[0];
    target.innerHTML = `<p class="caveat"><strong>No population differs significantly.</strong>` +
      (best ? ` Closest: ${POPS[best.population]} on day ${best.timepoint} (p = ${best.p_value.toFixed(4)}).` : "") + `</p>`;
    return;
  }
  const items = hits.sort((a, b) => a.timepoint - b.timepoint).map(row => `
    <li>
      <span class="verdict-day">Day ${row.timepoint}</span>
      <span class="verdict-claim" style="color:${PC[row.population]}">
        ${POPS[row.population]} is ${row.median_difference > 0 ? "higher" : "lower"} in responders
      </span>
      <span class="verdict-detail">
        ${row.median_responders.toFixed(2)}% vs ${row.median_non_responders.toFixed(2)}%
        (${row.median_difference > 0 ? "+" : ""}${row.median_difference.toFixed(2)} pp, p = ${row.p_value.toFixed(4)})
      </span>
    </li>`).join("");
  target.innerHTML = `<ul class="verdict-list">${items}</ul>
    <p class="caveat">${hits.length} of ${cohort.statistics.length} comparisons cleared p &lt; ${ALPHA}.
    With ${cohort.statistics.length} tests, roughly one would clear it by chance alone.</p>`;
}

/* ------------------------------------------------------------ stats table */
function drawStats(cohort) {
  if (!cohort.statistics.length) {
    document.getElementById("stats").innerHTML = `<p class="note">No comparison available for this cohort.</p>`;
    return;
  }
  const head = ["Day", "Population", "n (resp)", "n (non-resp)", "Median resp",
                "Median non-resp", "Difference", "p-value", "p < 0.05"];
  const body = cohort.statistics.map(r => `
    <tr class="${r.significant ? "hit" : ""}">
      <td>${r.timepoint}</td><td>${POPS[r.population]}</td>
      <td>${r.n_responders}</td><td>${r.n_non_responders}</td>
      <td>${r.median_responders === null ? "—" : r.median_responders.toFixed(2)}</td>
      <td>${r.median_non_responders === null ? "—" : r.median_non_responders.toFixed(2)}</td>
      <td>${r.median_difference === null ? "—" : (r.median_difference > 0 ? "+" : "") + r.median_difference.toFixed(2)}</td>
      <td>${r.p_value === null ? "—" : r.p_value.toFixed(4)}</td>
      <td>${r.significant ? "yes" : "—"}</td>
    </tr>`).join("");
  document.getElementById("stats").innerHTML =
    `<div class="table-scroll"><table class="stats-table">
       <thead><tr>${head.map(h => `<th>${h}</th>`).join("")}</tr></thead>
       <tbody>${body}</tbody></table></div>`;
}

/* --------------------------------------------------------- baseline bars */
function drawBreakdown(id, counts, colours, unit) {
  const categories = Object.keys(counts);
  if (!categories.length) {
    Plotly.react(id, [], Object.assign({}, BASE, { height: 120,
      annotations: [{ text: "Nothing in this subset.", showarrow: false, x: 0.5, y: 0.5,
        xref: "paper", yref: "paper", font: { family: FONT, size: 13, color: MUTED } }],
      xaxis: { visible: false }, yaxis: { visible: false } }), CONFIG);
    return;
  }
  const values = categories.map(c => counts[c]);
  const total = values.reduce((a, b) => a + b, 0) || 1;
  Plotly.react(id, [{
    type: "bar", orientation: "h", y: categories, x: values,
    marker: { color: categories.map((_, i) => colours[i % colours.length]), line: { width: 0 } },
    text: values.map(v => `${commas(v)}  (${(100 * v / total).toFixed(1)}%)`),
    textposition: "outside", textfont: { family: MONO, size: 11, color: MUTED },
    cliponaxis: false,
    hovertemplate: `%{y}: %{x:,} ${unit}<extra></extra>`
  }], Object.assign({}, BASE, {
    height: 52 + 40 * categories.length, showlegend: false, bargap: 0.42,
    margin: { l: 4, r: 4, t: 8, b: 4 },
    xaxis: { visible: false, range: [0, Math.max.apply(null, values) * 1.42] },
    yaxis: { showgrid: false, linecolor: "rgba(0,0,0,0)", autorange: "reversed",
             tickfont: { family: MONO, size: 11, color: INK } }
  }), CONFIG);
}

/* ------------------------------------------------------------------ render */
function render() {
  const key = currentKey();
  const cohort = DATA.cohorts[key];
  const [condition, treatment, sampleType] = key.split("|");

  document.getElementById("sentence").textContent =
    `Showing ${condition} · ${treatment} · ${sampleType}.`;

  drawCascade(key, cohort);

  if (!cohort) {
    document.getElementById("tiles").innerHTML = "";
    document.getElementById("verdict").innerHTML =
      `<p class="caveat">No samples were collected for this combination. Try another gate.</p>`;
    ["composition", "boxplots", "divergence", "by-project", "by-response", "by-sex"]
      .forEach(id => Plotly.purge(id));
    document.getElementById("stats").innerHTML = "";
    return;
  }

  drawTiles(cohort);
  drawComposition(cohort);
  drawVerdict(cohort);
  drawBoxplots(cohort);
  drawDivergence(cohort);
  drawStats(cohort);
  drawBreakdown("by-project", cohort.baseline.by_project, Object.values(PC), "samples");
  drawBreakdown("by-response", cohort.baseline.by_response, [RC.yes, RC.no], "subjects");
  drawBreakdown("by-sex", cohort.baseline.by_sex, ["#2E7CF6", "#7A5AF8"], "subjects");
}

/* --------------------------------------------------------------- cascading

   Not every combination was collected -- healthy subjects were never treated,
   for one. Rather than let someone pick a gate that returns nothing and have
   to explain the blank, the later selects only ever offer values that exist
   for the earlier ones.
   ------------------------------------------------------------------------ */

const KEYS = Object.keys(DATA.cohorts).map(k => k.split("|"));

function optionsFor(level, prefix) {
  const values = KEYS
    .filter(parts => prefix.every((p, i) => parts[i] === p))
    .map(parts => parts[level]);
  return [...new Set(values)];
}

function syncSelects(changed) {
  const condition = document.getElementById("condition");
  const treatment = document.getElementById("treatment");
  const sampleType = document.getElementById("sample_type");

  if (changed === "condition" || changed === null) {
    const allowed = optionsFor(1, [condition.value]);
    const keep = allowed.includes(treatment.value) ? treatment.value : allowed[0];
    fill("treatment", allowed, keep);
  }

  const allowed = optionsFor(2, [condition.value, treatment.value]);
  const keep = allowed.includes(sampleType.value) ? sampleType.value : allowed[0];
  fill("sample_type", allowed, keep);
}

fill("condition", optionsFor(0, []), "melanoma");
fill("treatment", DATA.options.treatment, "miraclib");
fill("sample_type", DATA.options.sample_type, "PBMC");
syncSelects(null);

["condition", "treatment", "sample_type"].forEach(id =>
  document.getElementById(id).addEventListener("change", () => {
    syncSelects(id);
    render();
  }));

render();
"""


def add_gate_counts(payload: dict) -> None:
    """Counts for the intermediate cascade stages (condition, then + treatment)."""
    with connect() as connection:
        condition_counts = dict(
            connection.execute(
                """
                SELECT sub.condition, COUNT(*)
                FROM sample sm JOIN subject sub ON sub.subject_id = sm.subject_id
                GROUP BY sub.condition
                """
            ).fetchall()
        )
        pair_counts = {
            (condition, treatment): count
            for condition, treatment, count in connection.execute(
                """
                SELECT sub.condition, sub.treatment, COUNT(*)
                FROM sample sm JOIN subject sub ON sub.subject_id = sm.subject_id
                GROUP BY sub.condition, sub.treatment
                """
            ).fetchall()
        }

    for key, cohort in payload["cohorts"].items():
        condition, treatment, _ = key.split("|")
        cohort["gates"] = {
            "condition": condition_counts.get(condition, 0),
            "treatment": pair_counts.get((condition, treatment), 0),
        }


def main() -> None:
    payload = build_payload()
    add_gate_counts(payload)

    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    css = (
        (DOCS_DIR.parent / "dashboard" / "assets" / "style.css").read_text(
            encoding="utf-8"
        )
        + EXTRA_CSS
    )

    html = (
        TEMPLATE.replace("__CSS__", css)
        .replace("__JS__", JS)
        .replace("__PAYLOAD__", json.dumps(payload, separators=(",", ":")))
        .replace("__ALPHA__", str(ALPHA))
        .replace("__GENERATED__", payload["generated"])
    )

    STATIC_DASHBOARD.write_text(html, encoding="utf-8")
    size = STATIC_DASHBOARD.stat().st_size / 1024
    print(f"Built {STATIC_DASHBOARD.relative_to(DOCS_DIR.parent)}  ({size:.0f} KB)")
    print(f"  {len(payload['cohorts'])} cohorts pre-computed")
    print("  Open it directly in a browser, or publish docs/ with GitHub Pages.")


if __name__ == "__main__":
    main()
