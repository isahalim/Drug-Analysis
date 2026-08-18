#!/usr/bin/env python3
"""Run the whole pipeline end to end.

    python src/run_pipeline.py     (or: make pipeline)

Steps run in order, in this interpreter, so there is no chance of one step
finding a package that another cannot see:

    0. preflight        confirm every third-party package imports
    1. load_data        build the SQLite database from the CSV
    2. analysis         relative frequency per sample (Part 2)
    3. stats_analysis   responders vs non-responders (Part 3)
    4. subset_analysis  baseline subset breakdowns (Part 4)
    5. bcell_query      average baseline B cell count (Part 4)
    6. export_static    build the shareable HTML dashboard

Each step is a module with a main(); importing and calling them rather than
shelling out to `python <script>` guarantees every step uses sys.executable,
which is the interpreter the venv already installed into.
"""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

# Allow `python src/run_pipeline.py` from anywhere in the repository.
# load_data.py sits at the root (the brief requires it there); everything else
# is in src/, so both directories go on the path.
_SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(_SRC))
sys.path.insert(0, str(_SRC.parent))

from config import OUTPUT_DIR, ROOT, ensure_output_dir  # noqa: E402

# (module, human-readable description)
STEPS = [
    ("load_data", "Build the database from cell-count.csv"),
    ("analysis", "Relative frequency of each population, per sample"),
    ("stats_analysis", "Responders vs non-responders"),
    ("subset_analysis", "Baseline subset breakdowns"),
    ("bcell_query", "Average baseline B cell count"),
    ("export_static", "Build the shareable HTML dashboard"),
]

# Package -> the import name, where they differ.
REQUIRED = ["numpy", "pandas", "scipy", "matplotlib", "plotly", "dash"]

RULE = "=" * 72


def preflight() -> None:
    """Import every third-party package up front and report the versions.

    Failing here, before any work has been done, turns a confusing
    ModuleNotFoundError halfway through the run into one clear instruction. It
    also prints which interpreter is being used, which is almost always the
    real cause when a package "is installed" but cannot be imported.
    """
    print(RULE)
    print("Step 0/6  Preflight")
    print(RULE)
    print(f"  interpreter  {sys.executable}")
    print(f"  python       {sys.version.split()[0]}")

    missing = []
    for name in REQUIRED:
        try:
            module = importlib.import_module(name)
        except ImportError:
            missing.append(name)
            print(f"  {name:<12} MISSING")
        else:
            version = getattr(module, "__version__", "unknown")
            print(f"  {name:<12} {version}")

    if missing:
        raise SystemExit(
            "\nMissing packages: "
            + ", ".join(missing)
            + "\n\nInstall them into *this* interpreter:\n"
            f"    {sys.executable} -m pip install -r requirements.txt\n\n"
            "Or let the Makefile handle it, which is the reliable route:\n"
            "    make setup\n"
        )

    if sys.version_info < (3, 10):
        raise SystemExit(
            f"\nPython 3.10 or newer is required; this is {sys.version.split()[0]}."
        )


def run_step(number: int, module_name: str, description: str) -> float:
    print(f"\n{RULE}")
    print(f"Step {number}/6  {description}   [{module_name}.py]")
    print(RULE)
    started = time.perf_counter()
    module = importlib.import_module(module_name)
    module.main()
    return time.perf_counter() - started


def main() -> None:
    ensure_output_dir()
    started = time.perf_counter()

    preflight()

    timings = []
    for number, (module_name, description) in enumerate(STEPS, start=1):
        elapsed = run_step(number, module_name, description)
        timings.append((module_name, elapsed))

    print(f"\n{RULE}")
    print("Pipeline complete")
    print(RULE)
    for module_name, elapsed in timings:
        print(f"  {module_name:<18} {elapsed:>6.2f}s")
    print(f"  {'total':<18} {time.perf_counter() - started:>6.2f}s")

    from config import DB_PATH  # noqa: PLC0415

    print(f"\nDatabase  {DB_PATH.name}  "
          f"({DB_PATH.stat().st_size / 1024:.1f} KB, repository root)")
    print(f"Outputs in {OUTPUT_DIR.relative_to(ROOT)}/")
    for path in sorted(OUTPUT_DIR.iterdir()):
        if path.is_file():
            size = path.stat().st_size
            print(f"  {path.name:<32} {size / 1024:>8.1f} KB")

    print("\nStart the interactive dashboard with:  make dashboard")


if __name__ == "__main__":
    main()
