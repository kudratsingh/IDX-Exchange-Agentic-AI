PYTHON ?= python3

.PHONY: install lint test evals

install:
	$(PYTHON) -m pip install -e ".[dev]" && $(PYTHON) -m pre_commit install

lint:
	$(PYTHON) -m ruff check . && $(PYTHON) -m ruff format --check .

test:
	$(PYTHON) -m pytest

evals:
	@if [ -f evals/run.py ]; then \
		$(PYTHON) -m evals.run --suite ci; \
	else \
		echo "No eval runner yet; it arrives in WO-005."; \
	fi
