#!/usr/bin/env python3
"""Paths, cohort constants and the shared colour palette.

Every script in src/ and the dashboard import from here, so the population
order, the display labels and the colours are identical in the CSVs, the
static PNG, the Dash app and the published HTML page.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
# config.py lives in <repo>/src, so the repository root is one level up.
ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"
DOCS_DIR = ROOT / "docs"

CSV_PATH = DATA_DIR / "cell-count.csv"

# The database is written to the repository root, next to load_data.py, so
# that `python load_data.py` from a fresh checkout puts the .db exactly where
# the brief asks for it.
DB_PATH = ROOT / "cell_counts.db"

FREQUENCY_CSV = OUTPUT_DIR / "cell_frequency_summary.csv"
STATISTICS_CSV = OUTPUT_DIR / "response_statistics.csv"
BASELINE_CSV = OUTPUT_DIR / "baseline_samples.csv"
BOXPLOT_PNG = OUTPUT_DIR / "response_boxplots.png"
BCELL_CSV = OUTPUT_DIR / "bcell_baseline_summary.csv"
STATIC_DASHBOARD = DOCS_DIR / "index.html"


def ensure_output_dir() -> None:
    """Create outputs/ if it is missing. Safe to call repeatedly."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# Cohort used for the response comparison (Part 3) and the baseline subset
# (Part 4). These are the defaults; the dashboard lets you change them.
# --------------------------------------------------------------------------
CONDITION = "melanoma"
TREATMENT = "miraclib"
SAMPLE_TYPE = "PBMC"
TIMEPOINTS = (0, 7, 14)
BASELINE = 0
ALPHA = 0.05

# --------------------------------------------------------------------------
# Cell populations. The dict order is the order used in every table and chart.
# --------------------------------------------------------------------------
POPULATIONS = {
    "b_cell": "B cell",
    "cd4_t_cell": "CD4 T cell",
    "cd8_t_cell": "CD8 T cell",
    "nk_cell": "NK cell",
    "monocyte": "Monocyte",
}

# One colour per population, held constant across every view so a population
# can be tracked from the composition bars to the boxplots without a re-read.
# The hues follow the excitation lasers on a cytometer: violet, blue, green,
# yellow-green, red.
POPULATION_COLOURS = {
    "b_cell": "#7A5AF8",       # 405 nm violet
    "cd4_t_cell": "#2E7CF6",   # 488 nm blue
    "cd8_t_cell": "#12A594",   # 532 nm green
    "nk_cell": "#E8912B",      # 561 nm yellow-green
    "monocyte": "#DB4F4F",     # 640 nm red
}

# Response groups get their own pair so they never collide with a population.
RESPONSE_COLOURS = {"yes": "#17795E", "no": "#C0574F"}
RESPONSE_LABELS = {"yes": "Responder", "no": "Non-responder", None: "Not recorded"}
SEX_LABELS = {"M": "Male", "F": "Female", None: "Not recorded"}


def population_label(population: str) -> str:
    return POPULATIONS.get(population, population)
