#!/usr/bin/env python3
"""Interactive dashboard for the cell-count analysis.

    python dashboard/app.py     (or: make dashboard)

Every number on the page is read live from outputs/cell_counts.db through the
same functions the command line scripts use, so the dashboard cannot report
anything the pipeline would not.

The controls in the left rail define a cohort. The gating cascade underneath
them shows how many samples survive each filter in turn, so the cohort behind
every chart is always visible rather than implied.

Responder status is deliberately *not* a filter: it is the axis every
comparison is made across.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make src/ importable when this file is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd
from dash import Dash, Input, Output, dash_table, dcc, html

from config import (
    ALPHA,
    BASELINE,
    DB_PATH,
    POPULATION_COLOURS,
    POPULATIONS,
    RESPONSE_COLOURS,
    RESPONSE_LABELS,
    SEX_LABELS,
)
from figures import (
    boxplot_figure,
    breakdown_figure,
    composition_figure,
    divergence_figure,
    empty_figure,
)
from queries import connect, filter_options, gating_cascade, load_cohort, test_populations

MAX_TABLE_ROWS = 1_000

# --------------------------------------------------------------------------
# Data access
# --------------------------------------------------------------------------

with connect() as _connection:
    OPTIONS = filter_options(_connection)

_cohort_cache: dict[tuple, pd.DataFrame] = {}


def cohort(filters: dict) -> pd.DataFrame:
    """Load a cohort, remembering the last few so repeated toggles stay quick."""
    key = tuple(
        (name, tuple(value) if isinstance(value, list) else value)
        for name, value in sorted(filters.items())
    )
    if key not in _cohort_cache:
        if len(_cohort_cache) > 24:
            _cohort_cache.clear()
        with connect() as connection:
            _cohort_cache[key] = load_cohort(connection, **filters)
    return _cohort_cache[key]


# --------------------------------------------------------------------------
# Small layout helpers
# --------------------------------------------------------------------------


def eyebrow(text: str) -> html.Div:
    return html.Div(text, className="eyebrow")


def card(title: str, note: str, *children) -> html.Section:
    return html.Section(
        [
            html.Div(
                [html.H2(title), html.P(note, className="note")],
                className="card-head",
            ),
            *children,
        ],
        className="card",
    )


def dropdown(component_id: str, label: str, values: list, multi: bool = False):
    return html.Div(
        [
            html.Label(label, htmlFor=component_id),
            dcc.Dropdown(
                id=component_id,
                options=[{"label": str(v), "value": v} for v in values],
                value=[] if multi else None,
                multi=multi,
                clearable=True,
                placeholder="Any",
            ),
        ],
        className="field",
    )


TABLE_STYLE = dict(
    style_as_list_view=True,
    style_table={"overflowX": "auto"},
    style_cell={
        "fontFamily": "IBM Plex Mono, ui-monospace, monospace",
        "fontSize": "12px",
        "padding": "9px 12px",
        "border": "none",
        "borderBottom": "1px solid #EDF0F5",
        "backgroundColor": "transparent",
        "color": "#0E1726",
        "textAlign": "right",
    },
    style_header={
        "fontFamily": "IBM Plex Mono, ui-monospace, monospace",
        "fontSize": "10px",
        "letterSpacing": "0.09em",
        "textTransform": "uppercase",
        "color": "#62708A",
        "fontWeight": "500",
        "backgroundColor": "transparent",
        "borderBottom": "1px solid #C9D2E0",
        "textAlign": "right",
    },
)


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------

app = Dash(__name__, title="Cell population explorer", update_title=None)
server = app.server

app.index_string = """<!DOCTYPE html>
<html lang="en">
  <head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
    {%css%}
  </head>
  <body>
    {%app_entry%}
    <footer>{%config%}{%scripts%}{%renderer%}</footer>
  </body>
</html>"""

app.layout = html.Div(
    [
        # ---------------------------------------------------------------
        # Left rail: the gate
        # ---------------------------------------------------------------
        html.Aside(
            [
                html.Div(
                    [
                        eyebrow("Immune profiling"),
                        html.H1(["Cell population", html.Br(), "explorer"]),
                        html.P(
                            "Relative frequencies of five populations across "
                            "three trial projects.",
                            className="lede",
                        ),
                    ],
                    className="brand",
                ),
                html.Div(
                    [
                        eyebrow("Gate on"),
                        dropdown("condition", "Condition", OPTIONS["condition"]),
                        dropdown("treatment", "Treatment", OPTIONS["treatment"]),
                        dropdown("sample_type", "Sample type", OPTIONS["sample_type"]),
                        dropdown("project", "Project", OPTIONS["project"], multi=True),
                        dropdown("sex", "Sex", OPTIONS["sex"], multi=True),
                        dropdown("timepoint", "Day", OPTIONS["timepoint"], multi=True),
                        html.Button(
                            "Reset to the study cohort",
                            id="reset",
                            n_clicks=0,
                            className="reset",
                        ),
                    ],
                    className="controls",
                ),
                html.Div(
                    [eyebrow("Samples surviving each gate"), html.Div(id="cascade")],
                    className="cascade-block",
                ),
            ],
            className="rail",
        ),
        # ---------------------------------------------------------------
        # Main column
        # ---------------------------------------------------------------
        html.Main(
            [
                html.Header(
                    [
                        html.P(id="cohort-sentence", className="cohort-sentence"),
                        html.Div(id="tiles", className="tiles"),
                    ],
                    className="masthead",
                ),
                card(
                    "Average sample composition",
                    "Mean relative frequency of each population, stacked to 100%. "
                    "Each bar is the average sample in that group.",
                    dcc.Graph(id="composition", config={"displayModeBar": False}),
                ),
                card(
                    "Responders against non-responders",
                    f"Mann-Whitney U, two-sided, run separately for every population "
                    f"on every day. A star marks p < {ALPHA}.",
                    html.Div(id="verdict", className="verdict"),
                    dcc.Graph(id="boxplots", config={"displayModeBar": False}),
                ),
                card(
                    "How the gap moves over treatment",
                    "Responder median minus non-responder median, in percentage "
                    "points. A gap that grows across days is worth more than one "
                    "low p-value.",
                    dcc.Graph(id="divergence", config={"displayModeBar": False}),
                ),
                card(
                    "Every comparison in this cohort",
                    "The same figures as outputs/response_statistics.csv, "
                    "recomputed for the gate you have set.",
                    html.Div(id="stats-table"),
                ),
                card(
                    f"Baseline subset, day {BASELINE}",
                    "Projects are counted in samples; response and sex describe a "
                    "patient, so those are counted in subjects.",
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H3("Samples per project"),
                                    dcc.Graph(
                                        id="by-project",
                                        config={"displayModeBar": False},
                                    ),
                                ],
                                className="breakdown",
                            ),
                            html.Div(
                                [
                                    html.H3("Subjects by response"),
                                    dcc.Graph(
                                        id="by-response",
                                        config={"displayModeBar": False},
                                    ),
                                ],
                                className="breakdown",
                            ),
                            html.Div(
                                [
                                    html.H3("Subjects by sex"),
                                    dcc.Graph(
                                        id="by-sex", config={"displayModeBar": False}
                                    ),
                                ],
                                className="breakdown",
                            ),
                        ],
                        className="breakdowns",
                    ),
                ),
                card(
                    "Per-sample frequencies",
                    "One row per sample, percentages of that sample's total. "
                    "Sort or filter any column; the complete table is written to "
                    "outputs/cell_frequency_summary.csv.",
                    html.Div(id="sample-table"),
                ),
                html.Footer(
                    [
                        html.Span("Data: cell-count.csv"),
                        html.Span("·"),
                        html.Span(f"Database: {DB_PATH.name}"),
                        html.Span("·"),
                        html.Span(f"Significance threshold p < {ALPHA}"),
                    ],
                    className="page-footer",
                ),
            ],
            className="main",
        ),
    ],
    className="shell",
)


# --------------------------------------------------------------------------
# Callbacks
# --------------------------------------------------------------------------

CONTROL_IDS = ["condition", "treatment", "sample_type", "project", "sex", "timepoint"]


@app.callback(
    [Output(name, "value") for name in CONTROL_IDS],
    Input("reset", "n_clicks"),
    prevent_initial_call=True,
)
def reset_controls(_):
    """Back to the cohort the written analysis uses."""
    return "melanoma", "miraclib", "PBMC", [], [], []


@app.callback(
    Output("cascade", "children"),
    Output("cohort-sentence", "children"),
    Output("tiles", "children"),
    Output("composition", "figure"),
    Output("verdict", "children"),
    Output("boxplots", "figure"),
    Output("divergence", "figure"),
    Output("stats-table", "children"),
    Output("by-project", "figure"),
    Output("by-response", "figure"),
    Output("by-sex", "figure"),
    Output("sample-table", "children"),
    [Input(name, "value") for name in CONTROL_IDS],
)
def refresh(condition, treatment, sample_type, project, sex, timepoint):
    filters = {
        "condition": condition,
        "treatment": treatment,
        "sample_type": sample_type,
        "project": project,
        "sex": sex,
        "timepoint": timepoint,
    }

    frame = cohort(filters)

    with connect() as connection:
        stages = gating_cascade(
            connection,
            [
                ("Condition", "condition", condition),
                ("Treatment", "treatment", treatment),
                ("Sample type", "sample_type", sample_type),
                ("Project", "project", project),
                ("Sex", "sex", sex),
                ("Day", "timepoint", timepoint),
            ],
        )

    cascade = build_cascade(stages)
    sentence = build_sentence(filters)

    if frame.empty:
        explanation = explain_empty(filters)
        blank = empty_figure(explanation)
        return (
            cascade,
            sentence,
            build_tiles(frame),
            blank,
            html.P(explanation, className="caveat"),
            blank,
            blank,
            html.P(explanation, className="note"),
            blank,
            blank,
            blank,
            html.P(explanation, className="note"),
        )

    results = test_populations(frame)

    return (
        cascade,
        sentence,
        build_tiles(frame),
        composition_figure(frame),
        build_verdict(results),
        boxplot_figure(frame, results),
        divergence_figure(results),
        build_stats_table(results),
        *build_breakdowns(frame),
        build_sample_table(frame),
    )


# --------------------------------------------------------------------------
# Builders for the pieces the callback returns
# --------------------------------------------------------------------------


def explain_empty(filters: dict) -> str:
    """Say what was actually collected, instead of just reporting nothing.

    Several gates are empty because of how the trials were run rather than
    because of a typo -- healthy subjects were never treated, for instance --
    so the message names what does exist for the condition already chosen.
    """
    condition = filters.get("condition")
    if not condition:
        return "No samples match this gate. Try clearing a filter."

    with connect() as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT sub.treatment, sm.sample_type
            FROM sample sm
            JOIN subject sub ON sub.subject_id = sm.subject_id
            WHERE sub.condition = ?
            ORDER BY sub.treatment, sm.sample_type
            """,
            (condition,),
        ).fetchall()

    if not rows:
        return f"No samples were collected for {condition}."

    pairs = ", ".join(f"{treatment} / {kind}" for treatment, kind in rows)
    return (
        f"No samples were collected for this gate. For {condition} the study "
        f"has: {pairs}."
    )


def build_cascade(stages: list[dict]) -> list:
    """The signature panel: one row per gate, bar width = share of all samples."""
    total = max(stages[0]["samples"], 1)
    rows = []
    for index, stage in enumerate(stages):
        share = 100 * stage["samples"] / total
        rows.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(stage["label"], className="gate-label"),
                            html.Span(
                                f"{stage['samples']:,}", className="gate-count"
                            ),
                        ],
                        className="gate-head",
                    ),
                    html.Div(
                        html.Div(
                            className="gate-fill",
                            style={"width": f"{share:.3f}%"},
                        ),
                        className="gate-track",
                    ),
                    html.Span(
                        stage["value"] or "everything",
                        className="gate-value",
                    )
                    if index > 0
                    else html.Span(
                        f"{stage['subjects']:,} subjects", className="gate-value"
                    ),
                ],
                className="gate" + (" gate-open" if index == 0 else ""),
            )
        )
    return rows


def build_sentence(filters: dict) -> str:
    parts = []
    for name in ("condition", "treatment", "sample_type"):
        value = filters[name]
        if value:
            parts.append(str(value))
    described = " · ".join(parts) if parts else "every condition and treatment"

    extras = []
    if filters["project"]:
        extras.append("projects " + ", ".join(map(str, filters["project"])))
    if filters["sex"]:
        extras.append(", ".join(SEX_LABELS.get(s, s).lower() for s in filters["sex"]))
    if filters["timepoint"]:
        extras.append("day " + ", ".join(str(t) for t in filters["timepoint"]))

    tail = f" ({'; '.join(extras)})" if extras else ""
    return f"Showing {described}{tail}."


def build_tiles(frame: pd.DataFrame) -> list:
    if frame.empty:
        counts = {"subjects": 0, "samples": 0, "yes": 0, "no": 0}
    else:
        samples = frame[["sample_id", "subject_id", "response"]].drop_duplicates()
        subjects = samples[["subject_id", "response"]].drop_duplicates()
        counts = {
            "subjects": subjects["subject_id"].nunique(),
            "samples": samples["sample_id"].nunique(),
            "yes": int((subjects["response"] == "yes").sum()),
            "no": int((subjects["response"] == "no").sum()),
        }

    tiles = [
        ("Subjects", f"{counts['subjects']:,}", None),
        ("Samples", f"{counts['samples']:,}", None),
        ("Responders", f"{counts['yes']:,}", RESPONSE_COLOURS["yes"]),
        ("Non-responders", f"{counts['no']:,}", RESPONSE_COLOURS["no"]),
    ]
    return [
        html.Div(
            [
                html.Span(
                    label,
                    className="tile-label",
                    style={"color": colour} if colour else {},
                ),
                html.Span(value, className="tile-value"),
            ],
            className="tile",
            style={"--tile-accent": colour} if colour else {},
        )
        for label, value, colour in tiles
    ]


def build_verdict(results: pd.DataFrame) -> list:
    if results.empty:
        return [html.Span("No responder / non-responder split in this cohort.")]

    hits = results[results["significant"]].sort_values("timepoint")
    if hits.empty:
        best = results.dropna(subset=["p_value"]).sort_values("p_value")
        if best.empty:
            return [html.Span("Too few samples in one group to test.")]
        row = best.iloc[0]
        return [
            html.Span("No population differs significantly. ", className="flat"),
            html.Span(
                f"Closest: {POPULATIONS[row['population']]} on day "
                f"{int(row['timepoint'])} (p = {row['p_value']:.4f})."
            ),
        ]

    items = []
    for row in hits.itertuples():
        direction = "higher" if row.median_difference > 0 else "lower"
        items.append(
            html.Li(
                [
                    html.Span(
                        f"Day {int(row.timepoint)}",
                        className="verdict-day",
                    ),
                    html.Span(
                        f"{POPULATIONS[row.population]} is {direction} in responders",
                        className="verdict-claim",
                        style={"color": POPULATION_COLOURS[row.population]},
                    ),
                    html.Span(
                        f"{row.median_responders:.2f}% vs "
                        f"{row.median_non_responders:.2f}%  "
                        f"({row.median_difference:+.2f} pp, p = {row.p_value:.4f})",
                        className="verdict-detail",
                    ),
                ]
            )
        )

    tested = len(results)
    return [
        html.Ul(items, className="verdict-list"),
        html.P(
            f"{len(hits)} of {tested} comparisons cleared p < {ALPHA}. With "
            f"{tested} tests, roughly one would clear it by chance alone.",
            className="caveat",
        ),
    ]


def build_stats_table(results: pd.DataFrame):
    if results.empty:
        return html.P("No comparison available for this cohort.", className="note")

    display = results.copy()
    display["Day"] = display["timepoint"].astype(int)
    display["Population"] = display["population"].map(POPULATIONS)
    display["n (resp)"] = display["n_responders"]
    display["n (non-resp)"] = display["n_non_responders"]
    display["Median resp"] = display["median_responders"].round(2)
    display["Median non-resp"] = display["median_non_responders"].round(2)
    display["Difference"] = display["median_difference"].round(2)
    display["p-value"] = display["p_value"].round(4)
    display["p < 0.05"] = display["significant"].map({True: "yes", False: "—"})

    columns = [
        "Day",
        "Population",
        "n (resp)",
        "n (non-resp)",
        "Median resp",
        "Median non-resp",
        "Difference",
        "p-value",
        "p < 0.05",
    ]
    display = display[columns]

    return dash_table.DataTable(
        data=display.to_dict("records"),
        columns=[{"name": c, "id": c} for c in columns],
        sort_action="native",
        style_data_conditional=[
            {
                "if": {"filter_query": '{p < 0.05} = "yes"'},
                "backgroundColor": "#F3F0FF",
                "fontWeight": "500",
            },
            {
                "if": {"column_id": "Population"},
                "textAlign": "left",
                "fontFamily": "IBM Plex Sans, sans-serif",
            },
        ],
        style_header_conditional=[
            {"if": {"column_id": "Population"}, "textAlign": "left"}
        ],
        **TABLE_STYLE,
    )


def build_breakdowns(frame: pd.DataFrame):
    """The three day-0 breakdowns, computed from the gated cohort."""
    baseline = frame[frame["timepoint"] == BASELINE]
    if baseline.empty:
        blank = empty_figure(f"No day {BASELINE} samples in this cohort.")
        return blank, blank, blank

    samples = baseline[
        ["sample_id", "subject_id", "project_id", "response", "sex"]
    ].drop_duplicates()
    subjects = samples[["subject_id", "response", "sex"]].drop_duplicates()

    by_project = samples.groupby("project_id")["sample_id"].nunique().sort_index()
    project_colours = list(POPULATION_COLOURS.values())
    project_figure = breakdown_figure(
        list(by_project.index),
        [int(v) for v in by_project.to_numpy()],
        [project_colours[i % len(project_colours)] for i in range(len(by_project))],
        "samples",
    )

    by_response = subjects["response"].value_counts()
    response_order = [r for r in ("yes", "no") if r in by_response.index]
    response_figure = breakdown_figure(
        [RESPONSE_LABELS[r] for r in response_order],
        [int(by_response[r]) for r in response_order],
        [RESPONSE_COLOURS[r] for r in response_order],
        "subjects",
    )

    by_sex = subjects["sex"].value_counts()
    sex_order = [s for s in ("M", "F") if s in by_sex.index]
    sex_figure = breakdown_figure(
        [SEX_LABELS[s] for s in sex_order],
        [int(by_sex[s]) for s in sex_order],
        ["#2E7CF6", "#7A5AF8"][: len(sex_order)],
        "subjects",
    )

    return project_figure, response_figure, sex_figure


def build_sample_table(frame: pd.DataFrame):
    """One row per sample, populations across the columns."""
    wide = frame.pivot_table(
        index=["sample_id", "subject_id", "timepoint", "response"],
        columns="population",
        values="percentage",
    ).reset_index()

    totals = (
        frame.groupby("sample_id")["cell_count"].sum().rename("total_count")
    )
    wide = wide.merge(totals, left_on="sample_id", right_index=True)

    wide["response"] = wide["response"].map(
        lambda r: RESPONSE_LABELS.get(r, "Not recorded")
    )
    wide = wide.rename(
        columns={
            "sample_id": "Sample",
            "subject_id": "Subject",
            "timepoint": "Day",
            "response": "Response",
            "total_count": "Total cells",
            **{key: label for key, label in POPULATIONS.items()},
        }
    )

    columns = ["Sample", "Subject", "Day", "Response", "Total cells"] + [
        label for label in POPULATIONS.values() if label in wide.columns
    ]
    wide = wide[columns].sort_values(["Sample"])
    for label in POPULATIONS.values():
        if label in wide.columns:
            wide[label] = wide[label].round(2)

    total_rows = len(wide)
    shown = wide.head(MAX_TABLE_ROWS)

    note = (
        html.P(
            f"Showing the first {MAX_TABLE_ROWS:,} of {total_rows:,} samples. "
            "All of them are in outputs/cell_frequency_summary.csv.",
            className="note tight",
        )
        if total_rows > MAX_TABLE_ROWS
        else html.P(f"{total_rows:,} samples.", className="note tight")
    )

    table = dash_table.DataTable(
        data=shown.to_dict("records"),
        columns=[
            {
                "name": c,
                "id": c,
                "type": "numeric" if c not in ("Sample", "Subject", "Response") else "text",
            }
            for c in columns
        ],
        page_size=12,
        sort_action="native",
        filter_action="native",
        style_data_conditional=[
            {
                "if": {"column_id": c},
                "textAlign": "left",
                "fontFamily": "IBM Plex Sans, sans-serif",
            }
            for c in ("Sample", "Subject", "Response")
        ],
        style_header_conditional=[
            {"if": {"column_id": c}, "textAlign": "left"}
            for c in ("Sample", "Subject", "Response")
        ],
        **TABLE_STYLE,
    )
    return [note, table]


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main() -> None:
    # 0.0.0.0 so the forwarded port works in GitHub Codespaces and Docker.
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8050"))
    print("\n  Cell population explorer")
    print(f"  Reading {DB_PATH}")
    print(f"  Open http://localhost:{port}  (Ctrl-C to stop)\n")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
