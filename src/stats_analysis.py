#!/usr/bin/env python3
"""Part 3 - compare cell population frequencies in responders vs non-responders.

    python src/stats_analysis.py     (run after load_data.py)

Cohort: melanoma subjects on miraclib, PBMC samples, reported separately at day
0, day 7 and day 14. Each subject contributes exactly one sample per day, so
within any one day every subject counts once and the two groups are independent.

Responders ("yes") are compared with non-responders ("no") one cell population
at a time. Each comparison gets a median for each group, the difference between
those medians in percentage points, and a p-value. A comparison is called
significant when p < 0.05.

Outputs
    stdout                              cohort description, table, conclusion
    outputs/response_boxplots.png       one row of plots per day, one per population
    outputs/response_statistics.csv     the same table, for sharing
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # render to file; no display needed

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import (
    ALPHA,
    BOXPLOT_PNG,
    CONDITION,
    POPULATIONS,
    RESPONSE_COLOURS,
    SAMPLE_TYPE,
    STATISTICS_CSV,
    TIMEPOINTS,
    TREATMENT,
    ensure_output_dir,
)
from queries import connect, load_cohort, test_populations


def plot_boxplots(frame: pd.DataFrame, results: pd.DataFrame) -> None:
    """Grid of boxplots: one row per day, one column per cell population.

    Each column shares a y-axis across the three days, so a population can be
    read straight down to see how the two groups move over treatment.
    """
    populations = [p for p in POPULATIONS if p in set(frame["population"])]
    timepoints = [t for t in TIMEPOINTS if t in set(frame["timepoint"])]
    lookup = results.set_index(["timepoint", "population"])["p_value"]

    figure, axes = plt.subplots(
        len(timepoints),
        len(populations),
        figsize=(3.1 * len(populations), 3.6 * len(timepoints)),
        sharey="col",
        squeeze=False,
    )

    for row, timepoint in enumerate(timepoints):
        last_row = row == len(timepoints) - 1
        for column, population in enumerate(populations):
            axis = axes[row][column]
            group = frame[
                (frame["timepoint"] == timepoint) & (frame["population"] == population)
            ]
            data = [
                group.loc[group["response"] == "yes", "percentage"].to_numpy(),
                group.loc[group["response"] == "no", "percentage"].to_numpy(),
            ]

            boxes = axis.boxplot(
                data,
                tick_labels=(
                    [
                        f"Responder\n(n={len(data[0])})",
                        f"Non-responder\n(n={len(data[1])})",
                    ]
                    if last_row
                    else ["", ""]
                ),
                widths=0.55,
                patch_artist=True,
                showmeans=True,
                meanprops={
                    "marker": "D",
                    "markerfacecolor": "white",
                    "markeredgecolor": "#333333",
                    "markersize": 5,
                },
                medianprops={"color": "#222222", "linewidth": 1.6},
                flierprops={"marker": ".", "markersize": 3, "alpha": 0.35},
            )
            for patch, response in zip(boxes["boxes"], ("yes", "no")):
                patch.set_facecolor(RESPONSE_COLOURS[response])
                patch.set_alpha(0.55)

            p_value = float(lookup.get((timepoint, population), float("nan")))
            significant = p_value < ALPHA
            verdict = "significant" if significant else "not significant"
            title = (
                f"{POPULATIONS[population]}\np = {p_value:.3f} ({verdict})"
                if row == 0
                else f"p = {p_value:.3f} ({verdict})"
            )
            axis.set_title(
                title,
                fontsize=10,
                color="#1A5632" if significant else "#444444",
            )

            if column == 0:
                axis.set_ylabel(f"Day {timepoint}\nRelative frequency (%)", fontsize=10)
            axis.grid(axis="y", alpha=0.25, linewidth=0.6)
            axis.set_axisbelow(True)

    figure.suptitle(
        f"{CONDITION.title()} patients on {TREATMENT}: cell population frequencies "
        f"over treatment\n{SAMPLE_TYPE} samples, responders vs non-responders, "
        f"each day compared separately",
        fontsize=13,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.97))
    ensure_output_dir()
    figure.savefig(BOXPLOT_PNG, dpi=200)
    plt.close(figure)


def describe_cohort(frame: pd.DataFrame) -> None:
    samples = frame[["sample_id", "subject_id", "response", "timepoint"]].drop_duplicates()
    subjects = samples[["subject_id", "response"]].drop_duplicates()

    print(f"Cohort: {CONDITION} / {TREATMENT} / {SAMPLE_TYPE}")
    print(
        f"  subjects  {len(subjects):>5,}  "
        f"({(subjects['response'] == 'yes').sum():,} responders, "
        f"{(subjects['response'] == 'no').sum():,} non-responders)"
    )
    print(
        f"  samples   {len(samples):>5,}  "
        f"(days {', '.join(str(t) for t in TIMEPOINTS)}; one per subject per day)"
    )


def print_results(results: pd.DataFrame) -> None:
    display = results.copy()
    display["population"] = display["population"].map(POPULATIONS)
    display["significant"] = np.where(display["significant"], "yes", "no")
    display["timepoint"] = "day " + display["timepoint"].astype(str)
    columns = {
        "timepoint": "day",
        "population": "population",
        "median_responders": "median (resp)",
        "median_non_responders": "median (non-resp)",
        "median_difference": "difference",
        "p_value": "p-value",
        "significant": "significant",
    }
    display = display[list(columns)].rename(columns=columns)

    print("\nRelative frequency (%), responders vs non-responders, by day")
    formatters = {
        "median (resp)": "{:.2f}".format,
        "median (non-resp)": "{:.2f}".format,
        "difference": "{:+.2f}".format,
        "p-value": "{:.4f}".format,
    }

    text = display.to_string(index=False, formatters=formatters).splitlines()
    header, body = text[0], text[1:]
    print(header)

    previous_day = None
    for line, day in zip(body, display["day"]):
        if previous_day is not None and day != previous_day:
            print()
        print(line)
        previous_day = day
    print()

    print(
        "  difference = responder median minus non-responder median, "
        "in percentage points"
    )
    print(f"  significant = p < {ALPHA}")


def print_conclusion(results: pd.DataFrame) -> None:
    print(f"\nConclusion (p < {ALPHA}):")

    hits = results[results["significant"]]
    if hits.empty:
        best = results.sort_values("p_value").iloc[0]
        print(
            "  No cell population differs significantly between responders and "
            "non-responders\n  at any timepoint."
        )
        print(
            f"  Closest is {POPULATIONS[best['population']]} on day "
            f"{best['timepoint']} (p = {best['p_value']:.4f})."
        )
        return

    for timepoint in TIMEPOINTS:
        day_hits = hits[hits["timepoint"] == timepoint]
        if day_hits.empty:
            print(f"  Day {timepoint}: nothing significant.")
            continue
        for _, row in day_hits.iterrows():
            direction = "higher" if row["median_difference"] > 0 else "lower"
            print(
                f"  Day {timepoint}: {POPULATIONS[row['population']]} is "
                f"{direction} in responders -- "
                f"{row['median_responders']:.2f}% vs "
                f"{row['median_non_responders']:.2f}% "
                f"({row['median_difference']:+.2f} points, p = {row['p_value']:.4f})."
            )

    print(
        f"\n  Note: {len(results)} comparisons were run separately "
        f"({len(POPULATIONS)} populations x {len(TIMEPOINTS)} days),\n"
        "  so one or two p < 0.05 results are expected by chance alone. Read the\n"
        "  consistent trends across days rather than any single p-value."
    )


def main() -> None:
    with connect() as connection:
        frame = load_cohort(
            connection,
            condition=CONDITION,
            treatment=TREATMENT,
            sample_type=SAMPLE_TYPE,
            timepoint=list(TIMEPOINTS),
            response=["yes", "no"],
        )

    if frame.empty:
        raise SystemExit("No samples matched the cohort filters.")

    describe_cohort(frame)

    results = test_populations(frame, TIMEPOINTS)
    print_results(results)
    print_conclusion(results)

    plot_boxplots(frame, results)
    ensure_output_dir()
    results.drop(columns=["population_label"]).to_csv(STATISTICS_CSV, index=False)
    print(f"\nWrote {BOXPLOT_PNG.name} and {STATISTICS_CSV.name}")


if __name__ == "__main__":
    main()
