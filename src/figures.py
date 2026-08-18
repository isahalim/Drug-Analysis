#!/usr/bin/env python3
"""Plotly figure builders.

Kept separate from the Dash callbacks so the same functions can be called by
the static exporter. A figure's appearance is therefore defined once.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import (
    ALPHA,
    POPULATION_COLOURS,
    POPULATIONS,
    RESPONSE_COLOURS,
    RESPONSE_LABELS,
)

INK = "#0E1726"
MUTED = "#62708A"
RULE = "#DDE3EC"
SURFACE = "#FFFFFF"

FONT = "IBM Plex Sans, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
MONO = "IBM Plex Mono, ui-monospace, SFMono-Regular, Menlo, monospace"

BASE_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family=FONT, size=12, color=INK),
    margin=dict(l=8, r=8, t=32, b=8),
    hoverlabel=dict(font=dict(family=MONO, size=12), bgcolor=SURFACE, bordercolor=RULE),
)

AXIS = dict(
    showgrid=True,
    gridcolor=RULE,
    gridwidth=1,
    zeroline=False,
    linecolor=RULE,
    ticks="outside",
    tickcolor=RULE,
    ticklen=4,
    tickfont=dict(family=MONO, size=11, color=MUTED),
)


def empty_figure(message: str) -> go.Figure:
    """A figure that says why it is empty, rather than an unexplained blank."""
    figure = go.Figure()
    figure.add_annotation(
        text=message,
        showarrow=False,
        font=dict(family=FONT, size=13, color=MUTED),
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
    )
    figure.update_layout(**BASE_LAYOUT, height=220)
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    return figure


# --------------------------------------------------------------------------
# Composition
# --------------------------------------------------------------------------


def composition_figure(frame: pd.DataFrame) -> go.Figure:
    """Mean composition of a sample, stacked, one bar per day per group.

    Stacked to 100% because that is what a relative frequency is: the bars are
    the average sample, not a sum of counts.
    """
    if frame.empty:
        return empty_figure("No samples match these filters.")

    grouped = (
        frame.groupby(["timepoint", "response", "population"], dropna=False)["percentage"]
        .mean()
        .reset_index()
    )

    rows = []
    for timepoint in sorted(grouped["timepoint"].dropna().unique()):
        for response in ("yes", "no"):
            slice_ = grouped[
                (grouped["timepoint"] == timepoint) & (grouped["response"] == response)
            ]
            if slice_.empty:
                continue
            rows.append((timepoint, response, slice_))

    if not rows:
        return empty_figure("No responder / non-responder samples match these filters.")

    labels = [
        f"Day {int(t)} &nbsp;·&nbsp; {RESPONSE_LABELS[r]}" for t, r, _ in rows
    ]

    figure = go.Figure()
    for population, label in POPULATIONS.items():
        values = []
        for _, _, slice_ in rows:
            match = slice_[slice_["population"] == population]["percentage"]
            values.append(float(match.iloc[0]) if len(match) else 0.0)
        figure.add_bar(
            y=labels,
            x=values,
            name=label,
            orientation="h",
            marker=dict(color=POPULATION_COLOURS[population], line=dict(width=0)),
            hovertemplate="%{y}<br>" + label + ": %{x:.2f}%<extra></extra>",
            text=[f"{v:.1f}" for v in values],
            textposition="inside",
            insidetextanchor="middle",
            textfont=dict(family=MONO, size=10, color="#FFFFFF"),
        )

    figure.update_layout(
        **BASE_LAYOUT,
        barmode="stack",
        height=90 + 42 * len(rows),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            x=0,
            font=dict(family=MONO, size=11),
            bgcolor="rgba(0,0,0,0)",
        ),
        bargap=0.32,
    )
    figure.update_xaxes(**AXIS, range=[0, 100], ticksuffix="%", title=None)
    figure.update_yaxes(
        showgrid=False,
        linecolor=RULE,
        autorange="reversed",
        tickfont=dict(family=MONO, size=11, color=INK),
    )
    return figure


# --------------------------------------------------------------------------
# Responder vs non-responder boxplots
# --------------------------------------------------------------------------


def boxplot_figure(frame: pd.DataFrame, results: pd.DataFrame) -> go.Figure:
    """One panel per population; days along the x-axis, two boxes per day.

    Laying the days along the x-axis inside each panel (rather than giving each
    day its own row) puts the whole time course of one population in a single
    panel, which is what makes a trend across days readable at a glance.
    """
    if frame.empty:
        return empty_figure("No samples match these filters.")

    frame = frame[frame["response"].isin(["yes", "no"])]
    if frame.empty:
        return empty_figure(
            "No response is recorded for this cohort, so there is nothing to "
            "compare. Healthy subjects were never treated."
        )

    populations = [p for p in POPULATIONS if p in set(frame["population"])]
    if not populations:
        return empty_figure("No cell populations match these filters.")

    timepoints = sorted(int(t) for t in frame["timepoint"].dropna().unique())
    if not timepoints:
        return empty_figure("No timepoints match these filters.")

    lookup = {}
    if not results.empty:
        lookup = {
            (int(row.timepoint), row.population): row.p_value
            for row in results.itertuples()
        }

    figure = make_subplots(
        rows=1,
        cols=len(populations),
        shared_yaxes=False,
        horizontal_spacing=0.035,
        subplot_titles=[POPULATIONS[p] for p in populations],
    )

    for column, population in enumerate(populations, start=1):
        panel = frame[frame["population"] == population]
        for response in ("yes", "no"):
            group = panel[panel["response"] == response]
            if group.empty:
                continue
            figure.add_box(
                x=["Day " + str(int(t)) for t in group["timepoint"]],
                y=group["percentage"],
                name=RESPONSE_LABELS[response],
                legendgroup=response,
                showlegend=(column == 1),
                marker=dict(
                    color=RESPONSE_COLOURS[response],
                    outliercolor=RESPONSE_COLOURS[response],
                    size=3,
                    opacity=0.45,
                ),
                fillcolor=RESPONSE_COLOURS[response],
                opacity=0.62,
                line=dict(width=1.2, color=RESPONSE_COLOURS[response]),
                boxmean=True,
                width=0.34,
                hovertemplate=(
                    f"{RESPONSE_LABELS[response]}<br>%{{x}}"
                    "<br>median %{median:.2f}%<extra></extra>"
                ),
                row=1,
                col=column,
            )

        # A p-value caption under each day, so significance is read in place
        # rather than looked up in a table elsewhere on the page.
        marks = []
        for timepoint in timepoints:
            p_value = lookup.get((timepoint, population))
            if p_value is None or np.isnan(p_value):
                marks.append("n/a")
            elif p_value < ALPHA:
                marks.append(f"p={p_value:.3f} *")
            else:
                marks.append(f"p={p_value:.3f}")
        figure.add_annotation(
            text="&nbsp;&nbsp;".join(marks),
            xref=f"x{column} domain" if column > 1 else "x domain",
            yref="paper",
            x=0.5,
            y=-0.16,
            showarrow=False,
            font=dict(
                family=MONO,
                size=9.5,
                color=INK if any("*" in m for m in marks) else MUTED,
            ),
        )

    figure.update_layout(
        **BASE_LAYOUT,
        boxmode="group",
        height=380,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.10,
            x=0,
            font=dict(family=MONO, size=11),
            bgcolor="rgba(0,0,0,0)",
        ),
    )
    # The first n annotations are the subplot titles make_subplots added; the
    # p-value captions were appended after them and keep their own styling.
    for annotation in figure.layout.annotations[: len(populations)]:
        annotation.font = dict(family=FONT, size=12, color=INK)

    figure.update_xaxes(**{**AXIS, "showgrid": False})
    figure.update_yaxes(**AXIS, ticksuffix="%")
    figure.update_yaxes(title_text="Relative frequency", title_font=dict(size=11, color=MUTED), row=1, col=1)
    figure.update_layout(margin=dict(l=8, r=8, t=52, b=52))
    return figure


# --------------------------------------------------------------------------
# Divergence over time
# --------------------------------------------------------------------------


def divergence_figure(results: pd.DataFrame) -> go.Figure:
    """Responder minus non-responder median, in percentage points, over days.

    A single significant p-value out of fifteen comparisons is weak evidence. A
    gap that grows steadily from day 0 through day 14 is a different kind of
    claim, and this is the view that shows it.
    """
    if results.empty:
        return empty_figure("No comparison available for this cohort.")

    figure = go.Figure()
    figure.add_hline(y=0, line=dict(color=RULE, width=1.5))

    for population, label in POPULATIONS.items():
        series = results[results["population"] == population].sort_values("timepoint")
        if series.empty:
            continue
        significant = series["significant"].to_numpy()
        figure.add_scatter(
            x=[f"Day {int(t)}" for t in series["timepoint"]],
            y=series["median_difference"],
            name=label,
            mode="lines+markers",
            line=dict(color=POPULATION_COLOURS[population], width=2.2),
            marker=dict(
                color=POPULATION_COLOURS[population],
                size=[11 if s else 7 for s in significant],
                symbol=["star" if s else "circle" for s in significant],
                line=dict(width=0),
            ),
            customdata=series["p_value"],
            hovertemplate=(
                label + "<br>%{x}<br>%{y:+.2f} points<br>p = %{customdata:.4f}"
                "<extra></extra>"
            ),
        )

    figure.update_layout(
        **BASE_LAYOUT,
        height=300,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.04,
            x=0,
            font=dict(family=MONO, size=11),
            bgcolor="rgba(0,0,0,0)",
        ),
    )
    figure.update_xaxes(**{**AXIS, "showgrid": False})
    figure.update_yaxes(
        **AXIS,
        ticksuffix=" pp",
        title_text="Responder − non-responder",
        title_font=dict(size=11, color=MUTED),
    )
    return figure


# --------------------------------------------------------------------------
# Baseline breakdowns
# --------------------------------------------------------------------------


def breakdown_figure(
    categories: list[str], values: list[int], colours: list[str], unit: str
) -> go.Figure:
    """Small horizontal bar chart for one baseline breakdown."""
    if not categories:
        return empty_figure("Nothing in this subset.")

    total = sum(values) or 1
    figure = go.Figure()
    figure.add_bar(
        y=categories,
        x=values,
        orientation="h",
        marker=dict(color=colours, line=dict(width=0)),
        text=[f"{v:,}  ({100 * v / total:.1f}%)" for v in values],
        textposition="outside",
        textfont=dict(family=MONO, size=11, color=MUTED),
        cliponaxis=False,
        hovertemplate="%{y}: %{x:,} " + unit + "<extra></extra>",
    )
    figure.update_layout(
        **BASE_LAYOUT,
        height=52 + 40 * len(categories),
        showlegend=False,
        bargap=0.42,
    )
    figure.update_xaxes(visible=False, range=[0, max(values) * 1.42])
    figure.update_yaxes(
        showgrid=False,
        linecolor="rgba(0,0,0,0)",
        autorange="reversed",
        tickfont=dict(family=MONO, size=11, color=INK),
    )
    figure.update_layout(margin=dict(l=4, r=4, t=8, b=4))
    return figure
