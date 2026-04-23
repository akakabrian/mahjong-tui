.PHONY: all venv run test test-only clean

all: venv

venv: .venv/bin/python
.venv/bin/python:
	python3 -m venv .venv
	.venv/bin/pip install -e .

run: venv
	.venv/bin/python mahjong.py

test: venv
	.venv/bin/python -m tests.qa

# Subset of QA scenarios by name. Usage: make test-only PAT=cursor
test-only: venv
	.venv/bin/python -m tests.qa $(PAT)

perf: venv
	.venv/bin/python -m tests.perf

tile-check: venv
	.venv/bin/python -m tests.tile_test

clean:
	rm -rf .venv *.egg-info mahjong_tui/__pycache__ tests/__pycache__
