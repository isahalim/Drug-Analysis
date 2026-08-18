# Immune cell population analysis

Analysis of immune cell counts from three clinical trial projects, built for
Bob Loblaw at Loblaw Bio. Five cell populations, 3,500 subjects, 10,500
samples, loaded into SQLite and served through an interactive dashboard.

**Dashboard:** https://isahalim.github.io/Drug-Analysis/

---

## Running it

Three targets, in order. Tested from a clean GitHub Codespace.

```bash
make setup       # install dependencies into .venv
make pipeline    # build the database, run every analysis, write outputs/
make dashboard   # serve the dashboard at http://localhost:8050
```

`make pipeline` and `make dashboard` both depend on setup, so either works on
its own from a fresh checkout.

In Codespaces, `make dashboard` binds to `0.0.0.0`; VS Code will offer to
forward port 8050. Open the forwarded URL. Use `make dashboard PORT=8060` if
8050 is taken.

### Part 1 on its own

The brief asks for `load_data.py` to be runnable directly from the repository
root, and it is:

```bash
python load_data.py       # writes cell_counts.db to the repository root
```

It uses only `csv` and `sqlite3` from the standard library, so it needs no
`pip install` at all and runs on any Python 3.10 or newer. No arguments, no
`python -m`.

### Why the dependency problem cannot come back

The usual failure here is `pip install pandas` landing in one interpreter while
the script runs under another, which shows up later as `ModuleNotFoundError:
No module named 'matplotlib'`. Three things prevent it:

1. `make setup` creates `.venv`, and every target invokes `.venv/bin/python`
   by absolute path. The interpreter that receives the packages is the one
   that runs the code.
2. `make pipeline` depends on the setup stamp, so a fresh checkout installs
   before it runs rather than failing partway through.
3. Step 0 of the pipeline imports all six packages up front and prints the
   interpreter path and every version. If something is missing, the error
   names the exact `pip` command for *that* interpreter instead of surfacing
   three steps later.

`requirements.txt` uses version floors rather than exact pins, so pip is free
to choose a build with a wheel for whichever Python is present. All four
scientific packages publish `cp314` wheels and Dash and Plotly are pure
Python, so a Python 3.14 environment resolves without a compiler. Verified
against numpy 2.5.2, pandas 3.0.5, scipy 1.18.0, matplotlib 3.11.1,
plotly 6.9.0 and dash 4.4.1.

### Other targets

```bash
make verify      # check the environment, run nothing
make clean       # remove the database and generated outputs
make distclean   # also remove .venv and the built dashboard page
```

---

## Database schema

`cell-count.csv` is a wide, fully denormalised table: every row repeats the
subject's condition, age, sex, treatment and response, and holds the five cell
counts in five separate columns. The schema splits it along the three real
entities and pivots the counts into rows.

```
project(project_id)
    │
    └──< subject(subject_id, project_id, condition, age, sex, treatment, response)
             │
             └──< sample(sample_id, subject_id, sample_type, time_from_treatment_start)
                      │
                      └──< cell_counts(sample_id, population, cell_count)
```

```sql
CREATE TABLE project (
    project_id TEXT PRIMARY KEY
);

CREATE TABLE subject (
    subject_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project(project_id),
    condition  TEXT,
    age        INTEGER CHECK (age IS NULL OR age >= 0),
    sex        TEXT    CHECK (sex IS NULL OR sex IN ('M', 'F')),
    treatment  TEXT,
    response   TEXT    CHECK (response IS NULL OR response IN ('yes', 'no'))
);

CREATE TABLE sample (
    sample_id                 TEXT PRIMARY KEY,
    subject_id                TEXT NOT NULL REFERENCES subject(subject_id),
    sample_type               TEXT,
    time_from_treatment_start INTEGER CHECK (... >= 0)
);

CREATE TABLE cell_counts (
    sample_id  TEXT NOT NULL REFERENCES sample(sample_id),
    population TEXT NOT NULL,
    cell_count INTEGER NOT NULL CHECK (cell_count >= 0),
    PRIMARY KEY (sample_id, population)
);
```

### Why this shape

**Three tables because there are three grains.** A project has many subjects, a
subject has many samples over time, a sample has many population counts. In the
CSV, subject 000's condition and response are repeated once per sample; here
they are stored once. If a subject's response is later corrected from `no` to
`yes`, that is one `UPDATE` rather than three, and there is no way for the
three copies to disagree.

**`cell_counts` is long, not wide.** This is the decision that matters most.
Keeping `b_cell`, `cd8_t_cell` and the rest as columns would mean a schema
migration and a rewrite of every query each time a panel adds a marker. As
rows, a sixth or a fortieth population is a data change and nothing else. It
also makes the Part 2 question a single `GROUP BY` instead of an
unpivot, and lets one index serve every population.

The cost is honest: per-sample totals need an aggregate rather than a sum of
five columns, and a wide report needs a pivot. Both are cheap, and the
`(sample_id, population)` primary key means a sample can never carry two counts
for the same population.

**Constraints encode what the analysis assumes.** `response IN ('yes','no')`,
non-negative counts and non-negative timepoints are all things the statistics
would silently mis-handle if violated. `NULL` is allowed where the data really
is absent — healthy subjects have no recorded response — so a missing value
stays distinguishable from a zero.

**Indexes follow the questions actually asked.** `idx_subject_cohort` on
`(condition, treatment, response)` covers the Part 3 and Part 4 cohort filters;
`idx_sample_type_time` covers "PBMC at day 0"; `idx_cell_counts_pop` on
`(population, sample_id)` covers "B cells only".

### Scaling to hundreds of projects and thousands of samples

The current data is small — 10,500 samples, 52,500 count rows, a 6 MB database
that queries in milliseconds. The design choices that matter are the ones that
hold as it grows by two or three orders of magnitude.

**What already scales.** The long `cell_counts` table grows linearly with
samples × populations. At 100 projects, 200,000 samples and a 40-marker panel
that is 8 million rows — still comfortable for SQLite, and the schema needs no
change to get there. Adding a project is an `INSERT`, not a migration.

**What I would change first: move to Postgres.** SQLite has a single writer.
The moment two pipelines load in parallel, or a dashboard serves several
analysts at once, that becomes the bottleneck long before row counts do.
Nothing in the schema is SQLite-specific — the relative frequency is computed
with a standard `SUM() OVER (PARTITION BY sample_id)` window function
specifically so the query moves across unchanged.

**Then: partition and pre-aggregate.** `cell_counts` partitioned by
`project_id` keeps single-project queries touching one partition. Relative
frequencies are recomputed on every read today; at scale they belong in a
materialised view refreshed on load, since the counts for a sample never change
once recorded. Sample-level totals are the obvious first materialisation.

**Then: normalise the vocabulary.** `condition`, `treatment`, `sample_type` and
`population` are free text. At three conditions that is fine; at hundreds of
projects it becomes `melanoma` / `Melanoma` / `MELANOMA` in the same column.
Lookup tables with foreign keys — plus a `population` table carrying lineage,
so CD4 and CD8 T cells can roll up to "T cell" — turn a typo from a silent
wrong answer into a rejected insert.

**Then: split the clinical timeline out of `subject`.** `treatment` and
`response` sit on the subject today, which quietly assumes one treatment and
one outcome per patient. A crossover trial or a second line of therapy breaks
that. The fix is a `treatment_course(subject_id, treatment, start_date,
end_date)` table with `response` attached to the course, and samples joined to
a course by date. I left it out because the data has exactly one treatment per
subject and inventing the extra join now would cost clarity for no gain — but
it is the first schema change a real second trial would force.

**For the analytics themselves.** Cohort filtering, per-population aggregates
and time-series comparisons are all column-oriented scans over a narrow table.
If the analytical load outgrows Postgres, `cell_counts` is already in the shape
a columnar store wants (DuckDB, or Parquet on object storage), and the same SQL
runs against DuckDB today. The relational database stays the system of record;
the columnar copy serves the dashboard.

---

## Code structure

```
.
├── load_data.py              Part 1 — schema + loader (root, stdlib only)
├── Makefile                  setup / pipeline / dashboard
├── requirements.txt
├── cell-count.csv → data/    input
├── src/
│   ├── config.py             paths, cohort constants, colour palette
│   ├── queries.py            every database read and every statistical test
│   ├── figures.py            every Plotly figure
│   ├── analysis.py           Part 2 — relative frequency table
│   ├── stats_analysis.py     Part 3 — responders vs non-responders + boxplots
│   ├── subset_analysis.py    Part 4.1–4.2 — baseline subset breakdowns
│   ├── bcell_query.py        Part 4 — average baseline B cell count
│   ├── export_static.py      builds docs/index.html
│   └── run_pipeline.py       orchestrator
├── dashboard/
│   ├── app.py                Dash application
│   └── assets/style.css
├── outputs/                  generated tables and the boxplot PNG
└── docs/index.html           published dashboard
```

### Why it is arranged this way

**One script per question.** Each of Parts 1 to 4 is a file that runs on its
own and prints a readable answer. Bob can run `python src/bcell_query.py` and
get one number without executing anything else. `run_pipeline.py` exists to
chain them for the grader, not because the steps need each other.

**`queries.py` is the single source of truth.** Every database read and every
statistical test lives there, and both the command line scripts and the
dashboard import it. The dashboard does not recompute anything in its own way,
so the numbers on screen and the numbers in `outputs/response_statistics.csv`
cannot drift apart. Same reasoning for `figures.py` and `config.py`: the
population order, labels and colours are defined once and used by the CSVs, the
PNG, the Dash app and the published page.

**The dashboard queries the database, not the CSVs.** It reads
`cell_counts.db` live on every filter change. That is the point of having
built a relational schema — the dashboard is a client of it rather than a
second, parallel implementation.

**SQL does the set work, Python does the statistics.** Filtering, joining and
the relative-frequency window function run in the database; pandas and scipy
handle only what SQL is bad at. That keeps the data moving into Python small
and means the heavy expressions are already portable to Postgres.

**Percentages are made to sum to exactly 100.** Rounding five shares
independently leaves samples at 99.99 or 100.01. `analysis.py` uses the
largest-remainder method so every sample's five percentages add to 100.00.

**Failure modes are explicit.** Missing database, missing CSV, missing columns,
duplicate sample ids and groups too small to test each produce a specific
message naming the fix, rather than a traceback or a silent `NaN`.

---

## Results

### Part 2 — relative frequencies

`outputs/cell_frequency_summary.csv`, 52,500 rows, one per population per
sample: `sample, total_count, population, count, percentage`.

### Part 3 — responders vs non-responders

Melanoma subjects on miraclib, PBMC samples only: 656 subjects (331 responders,
325 non-responders), 1,968 samples across days 0, 7 and 14.

Each day is tested separately with a **Mann-Whitney U test**, two-sided.
Relative frequencies are bounded percentages and visibly non-normal, so a
t-test's assumptions are not safe; Mann-Whitney compares the two groups without
them. Each subject contributes exactly one sample per day, so within a day the
two groups are independent and no subject is counted twice.

Two comparisons clear p < 0.05:

| Day | Population | Responders | Non-responders | Difference | p |
|----:|------------|-----------:|---------------:|-----------:|--:|
| 7 | CD4 T cell | 30.45% | 29.55% | +0.90 pp | 0.0297 |
| 14 | B cell | 9.11% | 9.84% | −0.73 pp | 0.0144 |

**The honest reading.** Fifteen comparisons were run (5 populations × 3 days),
so roughly one p < 0.05 is expected by chance alone. Two hits is weak evidence
on its own, and I would not hand Yah D'yada that table by itself.

What makes it more than noise is the shape over time. At baseline every
population is indistinguishable between the groups — the largest gap is 0.68
percentage points at p = 0.21. The CD4 T cell and B cell gaps then widen
monotonically from ~0 at day 0 through day 7 to day 14, in opposite directions.
A response-associated effect that emerges only after treatment starts and grows
with exposure is the pattern a real drug effect would produce; multiple-testing
noise would not order itself by day. The dashboard's *"How the gap moves over
treatment"* chart is built for exactly this reading.

Both are consistent with miraclib driving a T-cell-forward shift in responders.
The effect sizes are small — under one percentage point — so this is a
hypothesis worth a pre-registered confirmatory analysis, not a finished
biomarker. A day-28 timepoint would be the most informative next data.

Boxplots: `outputs/response_boxplots.png` (5 populations × 3 days), and the
interactive version in the dashboard.

### Part 4 — baseline subset

Melanoma, miraclib, PBMC, `time_from_treatment_start = 0`: **656 samples from
656 subjects** (one baseline sample each — checked, not assumed).

| Breakdown | | |
|---|---|---|
| Samples per project | prj1 384 (58.5%) | prj3 272 (41.5%) |
| Subjects by response | responder 331 (50.5%) | non-responder 325 (49.5%) |
| Subjects by sex | male 344 (52.4%) | female 312 (47.6%) |

Projects are counted in **samples**; response and sex describe a patient, so
those are counted in **subjects**.

### Part 4 — average B cell count

> Considering melanoma males of all sample and treatment types, what is the
> average number of B cells for responders at time = 0?

## **10206.15**

Pooled across 485 samples from 485 subjects — both treatments (miraclib and
phauximab) and both sample types (PBMC and whole blood), as the question
specifies. Raw cell counts, not relative frequencies. Range 3,449 to 23,812.

---

## The dashboard

Two versions are built from the same code:

**Interactive (`make dashboard`).** A Dash app that queries `cell_counts.db`
live. Filter by condition, treatment, sample type, project, sex and day; every
chart, the significance table and the per-sample table recompute against the
gate you set, p-values included.

Responder status is deliberately *not* a filter — it is the axis every
comparison is made across.

The left rail shows a **gating cascade**: how many samples survive each filter
in turn, 10,500 down to the cohort in view. Every statistic on the page is
conditional on exactly that set of samples, and this keeps the set visible
rather than implied.

**Published (`docs/index.html`).** A single self-contained file, ~110 KB, no
server needed. Every reachable cohort is pre-computed in Python — including the
Mann-Whitney p-values — and embedded as JSON, so the browser only redraws from
a lookup. The arithmetic is done by the same functions the Dash app calls, so
the two cannot disagree. It carries the condition, treatment and sample type
filters; project, sex, day and the per-sample table are local-only.

### Publishing the dashboard

`make pipeline` writes `docs/index.html`. Then:

1. Push to GitHub.
2. **Settings → Pages → Source: GitHub Actions.**
3. The included workflow (`.github/workflows/pages.yml`) builds and deploys on
   every push to `main`.
4. Put the resulting URL at the top of this README.

Or open `docs/index.html` in a browser directly — it needs no server.

---

## Outputs

| File | Contents |
|---|---|
| `cell_counts.db` | SQLite database (repository root) |
| `outputs/cell_frequency_summary.csv` | Part 2 — 52,500 rows |
| `outputs/response_statistics.csv` | Part 3 — 15 comparisons |
| `outputs/response_boxplots.png` | Part 3 — boxplot grid |
| `outputs/baseline_samples.csv` | Part 4 — the 656 baseline samples |
| `outputs/bcell_baseline_summary.csv` | Part 4 — the B cell average |
| `docs/index.html` | Published dashboard |
