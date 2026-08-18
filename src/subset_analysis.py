#!/usr/bin/env python3
"""Part 4 - describe the baseline subset: melanoma, miraclib, PBMC, day 0.

    python src/subset_analysis.py     (run after load_data.py)

Isolates the samples taken before treatment started -- melanoma patients on
miraclib, PBMC only, time_from_treatment_start = 0 -- and breaks them down by
project, by response, and by sex.

Note the two units. Projects are counted in samples; response and sex are
properties of a patient, so those are counted in subjects. The script checks
whether the two coincide in this subset, since a subject with two baseline
samples would otherwise be silently double counted.

Outputs
    stdout                          the subset description and each breakdown
    outputs/baseline_samples.csv    one row per sample in the subset
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from config import (
    BASELINE,
    BASELINE_CSV,
    CONDITION,
    RESPONSE_LABELS,
    SAMPLE_TYPE,
    SEX_LABELS,
    TREATMENT,
    ensure_output_dir,
)
from queries import connect

# The subset itself: one row per baseline sample, with the subject attributes
# needed for the breakdowns below.
BASELINE_QUERY = """
SELECT
    sm.sample_id,
    sub.subject_id,
    sub.project_id,
    sub.condition,
    sub.treatment,
    sub.response,
    sub.sex,
    sub.age,
    sm.sample_type,
    sm.time_from_treatment_start
FROM sample sm
JOIN subject sub ON sub.subject_id = sm.subject_id
WHERE sub.condition = ?
  AND sub.treatment = ?
  AND sm.sample_type = ?
  AND sm.time_from_treatment_start = ?
ORDER BY sub.project_id, sub.subject_id, sm.sample_id
"""

# Samples per project.
PROJECT_QUERY = """
SELECT sub.project_id, COUNT(*) AS samples, COUNT(DISTINCT sub.subject_id) AS subjects
FROM sample sm
JOIN subject sub ON sub.subject_id = sm.subject_id
WHERE sub.condition = ?
  AND sub.treatment = ?
  AND sm.sample_type = ?
  AND sm.time_from_treatment_start = ?
GROUP BY sub.project_id
ORDER BY sub.project_id
"""

# Response and sex describe the patient, so these count distinct subjects.
SUBJECT_BREAKDOWN_QUERY = """
SELECT {column} AS category, COUNT(DISTINCT sub.subject_id) AS subjects
FROM sample sm
JOIN subject sub ON sub.subject_id = sm.subject_id
WHERE sub.condition = ?
  AND sub.treatment = ?
  AND sm.sample_type = ?
  AND sm.time_from_treatment_start = ?
GROUP BY {column}
ORDER BY subjects DESC
"""

PARAMS = (CONDITION, TREATMENT, SAMPLE_TYPE, BASELINE)


def query(connection: sqlite3.Connection, sql: str) -> pd.DataFrame:
    return pd.read_sql_query(sql, connection, params=PARAMS)


def breakdowns(connection: sqlite3.Connection) -> dict[str, pd.DataFrame]:
    """All four frames the CLI and the dashboard both need."""
    return {
        "samples": query(connection, BASELINE_QUERY),
        "by_project": query(connection, PROJECT_QUERY),
        "by_response": query(
            connection, SUBJECT_BREAKDOWN_QUERY.format(column="sub.response")
        ),
        "by_sex": query(connection, SUBJECT_BREAKDOWN_QUERY.format(column="sub.sex")),
    }


def print_breakdown(frame: pd.DataFrame, unit: str, labels: dict | None = None) -> None:
    total = int(frame[unit].sum())
    for _, row in frame.iterrows():
        category = row.iloc[0]
        if labels is not None:
            category = labels.get(category, category)
        count = int(row[unit])
        share = 100 * count / total if total else 0
        print(f"    {str(category):<16} {count:>5,}  ({share:.1f}%)")
    print(f"    {'total':<16} {total:>5,}")


def main() -> None:
    with connect() as connection:
        frames = breakdowns(connection)

    samples = frames["samples"]
    if samples.empty:
        raise SystemExit("No samples matched the baseline filters.")

    n_samples = len(samples)
    n_subjects = samples["subject_id"].nunique()

    print(f"Baseline subset: {CONDITION} / {TREATMENT} / {SAMPLE_TYPE} / day {BASELINE}")
    print(f"  samples   {n_samples:>5,}")
    print(f"  subjects  {n_subjects:>5,}", end="")
    print(
        "  (one baseline sample each)"
        if n_samples == n_subjects
        else f"  (note: {n_samples - n_subjects} subjects have more than one)"
    )

    print("\n  Samples per project")
    print_breakdown(frames["by_project"][["project_id", "samples"]], "samples")

    print("\n  Subjects by response")
    print_breakdown(frames["by_response"], "subjects", RESPONSE_LABELS)

    print("\n  Subjects by sex")
    print_breakdown(frames["by_sex"], "subjects", SEX_LABELS)

    ensure_output_dir()
    samples.to_csv(BASELINE_CSV, index=False)
    print(f"\nWrote {BASELINE_CSV.name}")


if __name__ == "__main__":
    main()
