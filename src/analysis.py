#!/usr/bin/env python3
"""Part 2 - relative frequency of each cell population in each sample.

    python src/analysis.py     (run after load_data.py)

For every sample the total count is the sum across all five populations, and
each population's relative frequency is its count as a percentage of that
total.

One row per population per sample:

    sample, total_count, population, count, percentage

Written to outputs/cell_frequency_summary.csv.
"""

from __future__ import annotations

import csv
import sqlite3

from config import DB_PATH, FREQUENCY_CSV, ensure_output_dir

PREVIEW_ROWS = 20

QUERY = """
SELECT sample_id, population, cell_count
FROM cell_counts
ORDER BY sample_id, population
"""

COLUMNS = ["sample", "total_count", "population", "count", "percentage"]


def allocate_percentages(counts: list[int], total: int) -> list[float]:
    """Round percentages to 2 dp so that they still sum to exactly 100.

    Rounding each share independently can leave a sample summing to 99.99 or
    100.01. This distributes the leftover hundredths to the populations with
    the largest truncated remainder (the largest-remainder method), so every
    sample's percentages add up to 100.00 exactly.
    """
    if total <= 0:
        return [0.0] * len(counts)

    UNITS = 10_000  # hundredths of a percent in a whole
    exact = [count * UNITS / total for count in counts]
    floors = [int(value) for value in exact]
    leftover = UNITS - sum(floors)

    order = sorted(range(len(counts)), key=lambda i: exact[i] - floors[i], reverse=True)
    for i in order[:leftover]:
        floors[i] += 1

    return [units / 100 for units in floors]


def fetch_summary(connection: sqlite3.Connection) -> list[tuple]:
    """Return (sample, total_count, population, count, percentage) rows.

    The query is ordered by sample so the rows for one sample arrive together
    and can be totalled in a single streaming pass -- no need to hold the whole
    table in memory or make a second query per sample.
    """
    rows: list[tuple] = []
    current: list[tuple[str, int]] = []
    current_sample: str | None = None

    def flush() -> None:
        if current_sample is None:
            return
        counts = [count for _, count in current]
        total = sum(counts)
        percentages = allocate_percentages(counts, total)
        for (population, count), percentage in zip(current, percentages):
            rows.append((current_sample, total, population, count, percentage))

    for sample_id, population, cell_count in connection.execute(QUERY):
        if sample_id != current_sample:
            flush()
            current_sample, current = sample_id, []
        current.append((population, cell_count))
    flush()

    return rows


def print_table(rows: list[tuple], limit: int = PREVIEW_ROWS) -> None:
    shown = rows[:limit]
    widths = [len(name) for name in COLUMNS]
    formatted = []
    for row in shown:
        cells = [
            str(row[0]),
            f"{row[1]:,}",
            str(row[2]),
            f"{row[3]:,}",
            f"{row[4]:.2f}",
        ]
        widths = [max(w, len(c)) for w, c in zip(widths, cells)]
        formatted.append(cells)

    header = "  ".join(name.ljust(w) for name, w in zip(COLUMNS, widths))
    print(header)
    print("  ".join("-" * w for w in widths))
    for cells in formatted:
        # Left-align the text columns, right-align the numbers.
        print(
            "  ".join(
                cell.ljust(w) if i in (0, 2) else cell.rjust(w)
                for i, (cell, w) in enumerate(zip(cells, widths))
            )
        )

    if len(rows) > limit:
        print(f"... {len(rows) - limit:,} more rows")


def write_csv(rows: list[tuple]) -> None:
    ensure_output_dir()
    with FREQUENCY_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        writer.writerows(rows)


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(
            f"Could not find {DB_PATH.name}. Run 'python load_data.py' first."
        )

    connection = sqlite3.connect(DB_PATH)
    try:
        rows = fetch_summary(connection)
    finally:
        connection.close()

    if not rows:
        raise SystemExit("cell_counts is empty. Re-run 'python load_data.py'.")

    print("Relative frequency of each cell population, by sample\n")
    print_table(rows)

    write_csv(rows)
    samples = len({row[0] for row in rows})
    print(f"\n{len(rows):,} rows across {samples:,} samples -> {FREQUENCY_CSV.name}")


if __name__ == "__main__":
    main()
