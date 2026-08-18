# =============================================================================
# Cell count analysis
#
#   make setup       install dependencies
#   make pipeline    build the database and produce every table and plot
#   make dashboard   serve the interactive dashboard
#
# Everything runs inside a virtual environment created by `make setup`, and
# every target invokes that environment's interpreter by absolute path. That
# is deliberate: the usual way this breaks is `pip install pandas` landing in
# one interpreter while the script runs under another, which surfaces later as
# ModuleNotFoundError. Here the interpreter that gets the packages is the same
# one that runs the code, so the two cannot disagree.
#
# `pipeline` and `dashboard` both depend on the setup stamp, so either works
# from a clean checkout without running `make setup` first.
# =============================================================================

PYTHON ?= python3
VENV   := .venv
STAMP  := $(VENV)/.installed
PORT   ?= 8050

ifeq ($(OS),Windows_NT)
    VENV_PY := $(VENV)/Scripts/python.exe
else
    VENV_PY := $(VENV)/bin/python
endif

.DEFAULT_GOAL := help
.PHONY: help setup pipeline dashboard verify clean distclean

# -----------------------------------------------------------------------------

help:
	@echo ""
	@echo "  make setup       Install dependencies into $(VENV)"
	@echo "  make pipeline    Load the data, run every analysis, write outputs/"
	@echo "  make dashboard   Serve the dashboard on http://localhost:$(PORT)"
	@echo ""
	@echo "  make verify      Check the environment without running anything"
	@echo "  make clean       Remove generated outputs"
	@echo "  make distclean   Remove outputs and the virtual environment"
	@echo ""

# --- setup -------------------------------------------------------------------

setup: $(STAMP)

$(STAMP): requirements.txt
	@echo "==> Checking $(PYTHON)"
	@$(PYTHON) -c "import sys; \
		sys.exit(0) if sys.version_info >= (3, 10) else \
		(print('Python 3.10 or newer is required; found ' + sys.version.split()[0]), sys.exit(1))"
	@echo "==> Creating the virtual environment in $(VENV)"
	@$(PYTHON) -m venv $(VENV) || { \
		echo ""; \
		echo "    Could not create a virtual environment."; \
		echo "    On Debian or Ubuntu:  sudo apt-get install -y python3-venv"; \
		echo "    Then run 'make setup' again."; \
		echo ""; \
		exit 1; }
	@echo "==> Installing dependencies"
	@$(VENV_PY) -m pip install --quiet --upgrade pip setuptools wheel
	@$(VENV_PY) -m pip install --quiet -r requirements.txt
	@echo "==> Confirming every package imports"
	@$(VENV_PY) -c "import numpy, pandas, scipy, matplotlib, plotly, dash; \
		print('    numpy', numpy.__version__); \
		print('    pandas', pandas.__version__); \
		print('    scipy', scipy.__version__); \
		print('    matplotlib', matplotlib.__version__); \
		print('    plotly', plotly.__version__); \
		print('    dash', dash.__version__)"
	@touch $@
	@echo ""
	@echo "    Ready. Next:  make pipeline"
	@echo ""

# --- pipeline ----------------------------------------------------------------

pipeline: $(STAMP)
	@$(VENV_PY) src/run_pipeline.py

# --- dashboard ---------------------------------------------------------------

dashboard: $(STAMP)
	@test -f cell_counts.db || { \
		echo "The database has not been built yet. Running the pipeline first."; \
		$(VENV_PY) src/run_pipeline.py; }
	@PORT=$(PORT) $(VENV_PY) dashboard/app.py

# --- housekeeping ------------------------------------------------------------

verify: $(STAMP)
	@$(VENV_PY) -c "import sys; sys.path.insert(0, 'src'); \
		import run_pipeline; run_pipeline.preflight()"

clean:
	@rm -f cell_counts.db
	@rm -f outputs/*.csv outputs/*.png
	@rm -rf src/__pycache__ dashboard/__pycache__
	@echo "Removed generated outputs."

distclean: clean
	@rm -rf $(VENV) docs/index.html
	@echo "Removed the virtual environment."
