#!/usr/bin/env python3
"""The query and statistics layer.

Everything that reads the database or runs a test lives here, and both the
command line scripts and the dashboard import it. That is deliberate: the
numbers printed by `make pipeline` and the numbers drawn in the dashboard come
from the same functions, so the two cannot drift apart.

Relative frequencies are computed in SQL with a window function rather than in
pandas, so the same expression would run unchanged against Postgres if the
database outgrew SQLite.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

import numpy as np
import pandas as pd
from scipy import stats

from config import ALPHA, DB_PATH, POPULATIONS

# --------------------------------------------------------------------------
# Connection handling
# --------------------------------------------------------------------------


@contextmanager
def connect(db_path=None):
    """Open a read-only-ish connection to the database.

    Raises a clear message rather than an sqlite3 error when the pipeline has
    not been run yet -- that is the most common way to arrive here.
    """
    path = db_path or DB_PATH
    if not path.exists():
        raise SystemExit(
            f"Could not find {path.name}. Run 'make pipeline' "
            f"(or 'python load_data.py') first."
        )
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
    finally:
        connection.close()


# --------------------------------------------------------------------------
# Filter vocabulary -- drives the dashboard's controls
# --------------------------------------------------------------------------

FILTER_COLUMNS = {
    "project": "sub.project_id",
    "condition": "sub.condition",
    "treatment": "sub.treatment",
    "sex": "sub.sex",
    "response": "sub.response",
    "sample_type": "sm.sample_type",
    "timepoint": "sm.time_from_treatment_start",
}


def filter_options(connection: sqlite3.Connection) -> dict[str, list]:
    """Distinct values for every filterable column, read from the data.

    Read rather than hard-coded so a new condition or treatment appears in the
    dashboard controls as soon as it is loaded.
    """
    options: dict[str, list] = {}
    for name, column in FILTER_COLUMNS.items():
        rows = connection.execute(
            f"""
            SELECT DISTINCT {column} AS value
            FROM sample sm
            JOIN subject sub ON sub.subject_id = sm.subject_id
            WHERE {column} IS NOT NULL
            ORDER BY value
            """
        ).fetchall()
        options[name] = [row[0] for row in rows]
    return options


def _where(filters: dict) -> tuple[str, list]:
    """Turn a {column: value-or-list} dict into a WHERE fragment and params.

    A value of None or an empty list means "do not filter on this column",
    which is what an untouched dashboard control sends.
    """
    clauses: list[str] = []
    params: list = []
    for name, value in (filters or {}).items():
        if value is None or value == [] or name not in FILTER_COLUMNS:
            continue
        column = FILTER_COLUMNS[name]
        if isinstance(value, (list, tuple, set)):
            values = list(value)
            placeholders = ", ".join("?" for _ in values)
            clauses.append(f"{column} IN ({placeholders})")
            params.extend(values)
        else:
            clauses.append(f"{column} = ?")
            params.append(value)
    return (" AND ".join(clauses) if clauses else "1=1"), params


# --------------------------------------------------------------------------
# Core data pull
# --------------------------------------------------------------------------

COHORT_SQL = """
SELECT
    sub.subject_id,
    sub.project_id,
    sub.condition,
    sub.treatment,
    sub.response,
    sub.sex,
    sub.age,
    sm.sample_id,
    sm.sample_type,
    sm.time_from_treatment_start AS timepoint,
    cc.population,
    cc.cell_count,
    100.0 * cc.cell_count / SUM(cc.cell_count) OVER (PARTITION BY sm.sample_id)
        AS percentage
FROM subject sub
JOIN sample sm      ON sm.subject_id = sub.subject_id
JOIN cell_counts cc ON cc.sample_id  = sm.sample_id
WHERE {where}
"""


def load_cohort(connection: sqlite3.Connection, **filters) -> pd.DataFrame:
    """Long frame: one row per sample per population, with relative frequency.

    Note the window function partitions by sample_id *before* the WHERE clause
    would remove populations, so a percentage is always out of that sample's
    full five-population total -- filtering to one population still reports its
    true share of the sample.
    """
    where, params = _where(filters)
    frame = pd.read_sql_query(COHORT_SQL.format(where=where), connection, params=params)
    if not frame.empty:
        frame["population_label"] = frame["population"].map(POPULATIONS)
    return frame


def gating_cascade(connection: sqlite3.Connection, ordered_filters: list[tuple]) -> list[dict]:
    """How many samples survive each filter, applied one after another.

    Mirrors a cytometry gating hierarchy: start from every sample, then apply
    each gate in turn and report what is left. This makes the cohort visible
    instead of implied, which matters because every statistic downstream is
    conditional on exactly this set of samples.
    """
    applied: dict = {}
    stages = []

    total = connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0]
    stages.append({"label": "All samples", "value": None, "samples": total, "subjects": None})

    subject_total = connection.execute("SELECT COUNT(*) FROM subject").fetchone()[0]
    stages[0]["subjects"] = subject_total

    for label, name, value in ordered_filters:
        applied[name] = value
        where, params = _where(applied)
        row = connection.execute(
            f"""
            SELECT COUNT(*), COUNT(DISTINCT sub.subject_id)
            FROM sample sm
            JOIN subject sub ON sub.subject_id = sm.subject_id
            WHERE {where}
            """,
            params,
        ).fetchone()
        display = value if not isinstance(value, (list, tuple)) else ", ".join(map(str, value))
        stages.append(
            {
                "label": label,
                "value": "any" if value in (None, [], ()) else str(display),
                "samples": row[0],
                "subjects": row[1],
            }
        )
    return stages


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------


def compare(responders: np.ndarray, non_responders: np.ndarray) -> dict:
    """Median of each group, the gap between them, and a p-value.

    The p-value comes from a Mann-Whitney U test, which compares the two groups
    without assuming the frequencies follow a bell curve -- they are bounded
    percentages, so that assumption is not safe. Groups smaller than three are
    reported without a p-value rather than with a meaningless one.
    """
    n_yes, n_no = len(responders), len(non_responders)
    result = {
        "n_responders": n_yes,
        "n_non_responders": n_no,
        "median_responders": float(np.median(responders)) if n_yes else float("nan"),
        "median_non_responders": float(np.median(non_responders)) if n_no else float("nan"),
        "p_value": float("nan"),
        "significant": False,
    }
    result["median_difference"] = result["median_responders"] - result["median_non_responders"]

    if n_yes >= 3 and n_no >= 3:
        _, p_value = stats.mannwhitneyu(
            responders, non_responders, alternative="two-sided"
        )
        result["p_value"] = float(p_value)
        result["significant"] = bool(p_value < ALPHA)

    return result


def test_populations(frame: pd.DataFrame, timepoints=None) -> pd.DataFrame:
    """One responder vs non-responder comparison per population per timepoint.

    Each timepoint is tested on its own. Responders are only ever compared with
    non-responders sampled on the same day, so nothing is averaged across time
    and the progression over treatment stays visible. Because each subject
    contributes one sample per day, the two groups within a day are independent
    and no subject is counted twice.
    """
    if frame.empty:
        return pd.DataFrame()

    days = timepoints if timepoints is not None else sorted(frame["timepoint"].dropna().unique())
    rows = []
    for timepoint in days:
        day = frame[frame["timepoint"] == timepoint]
        if day.empty:
            continue
        for population in POPULATIONS:
            group = day[day["population"] == population]
            if group.empty:
                continue
            responders = group.loc[group["response"] == "yes", "percentage"].to_numpy()
            non_responders = group.loc[group["response"] == "no", "percentage"].to_numpy()
            if len(responders) == 0 and len(non_responders) == 0:
                continue
            rows.append(
                {
                    "timepoint": int(timepoint),
                    "population": population,
                    **compare(responders, non_responders),
                }
            )

    results = pd.DataFrame(rows)
    if not results.empty:
        results["population_label"] = results["population"].map(POPULATIONS)
    return results


def box_statistics(values: np.ndarray) -> dict:
    """Five-number summary plus n, for pre-computed box plots."""
    if len(values) == 0:
        return {"n": 0}
    q1, median, q3 = (float(v) for v in np.percentile(values, [25, 50, 75]))
    return {
        "n": int(len(values)),
        "min": float(np.min(values)),
        "q1": q1,
        "median": median,
        "q3": q3,
        "max": float(np.max(values)),
        "mean": float(np.mean(values)),
    }
