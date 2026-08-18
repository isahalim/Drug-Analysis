#!/usr/bin/env python3
"""Part 4 query - average B cell count: melanoma males, responders, baseline.

    python src/bcell_query.py     (run after load_data.py)

Answers: considering melanoma males of all sample and treatment types, what is
the average number of B cells for responders at time = 0?

All treatments and all sample types are included, so PBMC and whole blood are
pooled, as are miraclib and phauximab. The composition of the pool is printed
alongside the answer so the pooling is visible rather than implied.

Uses the raw cell_count, not the relative frequency -- the question asks for a
number of cells.

Outputs
    stdout                                  the answer and the pool it came from
    outputs/bcell_baseline_summary.csv      the same figures, for sharing
"""

from __future__ import annotations

import pandas as pd

from config import BCELL_CSV, ensure_output_dir
from queries import connect

CONDITION = "melanoma"
SEX = "M"
RESPONSE = "yes"
POPULATION = "b_cell"
TIMEPOINT = 0

AVERAGE_QUERY = """
SELECT
    COUNT(*)                        AS samples,
    COUNT(DISTINCT sub.subject_id)  AS subjects,
    AVG(cc.cell_count)              AS mean_b_cells,
    MIN(cc.cell_count)              AS min_b_cells,
    MAX(cc.cell_count)              AS max_b_cells
FROM cell_counts cc
JOIN sample sm   ON sm.sample_id  = cc.sample_id
JOIN subject sub ON sub.subject_id = sm.subject_id
WHERE cc.population = ?
  AND sub.condition = ?
  AND sub.sex = ?
  AND sub.response = ?
  AND sm.time_from_treatment_start = ?
"""

COMPOSITION_QUERY = """
SELECT sm.sample_type, sub.treatment, COUNT(*) AS samples,
       AVG(cc.cell_count) AS mean_b_cells
FROM cell_counts cc
JOIN sample sm   ON sm.sample_id  = cc.sample_id
JOIN subject sub ON sub.subject_id = sm.subject_id
WHERE cc.population = ?
  AND sub.condition = ?
  AND sub.sex = ?
  AND sub.response = ?
  AND sm.time_from_treatment_start = ?
GROUP BY sm.sample_type, sub.treatment
ORDER BY sm.sample_type, sub.treatment
"""

PARAMS = (POPULATION, CONDITION, SEX, RESPONSE, TIMEPOINT)


def summary(connection) -> tuple[dict, pd.DataFrame]:
    samples, subjects, mean, minimum, maximum = connection.execute(
        AVERAGE_QUERY, PARAMS
    ).fetchone()
    composition = pd.read_sql_query(COMPOSITION_QUERY, connection, params=PARAMS)
    overall = {
        "samples": samples,
        "subjects": subjects,
        "mean_b_cells": mean,
        "min_b_cells": minimum,
        "max_b_cells": maximum,
    }
    return overall, composition


def main() -> None:
    with connect() as connection:
        overall, composition = summary(connection)

    if not overall["samples"]:
        raise SystemExit("No samples matched the filters.")

    print(
        f"Melanoma / male / responder / day {TIMEPOINT} / all treatments / "
        f"all sample types"
    )
    print(f"  samples   {overall['samples']:>5,}")
    print(f"  subjects  {overall['subjects']:>5,}")
    for _, row in composition.iterrows():
        print(
            f"    {row['sample_type']:<5} {row['treatment']:<10} "
            f"{int(row['samples']):>5,}"
        )
    print(
        f"  B cell count range  {overall['min_b_cells']:,} to "
        f"{overall['max_b_cells']:,}"
    )

    print(f"\nAverage number of B cells: {overall['mean_b_cells']:.2f}")

    ensure_output_dir()
    pd.DataFrame([overall]).to_csv(BCELL_CSV, index=False)
    print(f"\nWrote {BCELL_CSV.name}")


if __name__ == "__main__":
    main()
