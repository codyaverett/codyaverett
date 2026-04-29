.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

PROJECTS_ROOT ?= /Users/caavere/Projects
TOP ?= 10
SCAN := scripts/scan-projects.sh
REPORT := scripts/projects-report.md

.PHONY: help scan scan-json report show-report featured clean-report metrics-trigger metrics-status preview lint check

help: ## Show this help (default target)
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n\nTargets:\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 } \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)
	@echo
	@echo "Variables: PROJECTS_ROOT=$(PROJECTS_ROOT)  TOP=$(TOP)"

##@ Project discovery

scan: ## Scan ~/Projects and write a ranked report (TOP=N to limit, default 10)
	@bash $(SCAN) --top $(TOP) >/dev/null
	@echo "wrote $(REPORT)"

scan-json: ## Scan and emit NDJSON to stdout (machine-readable, no report file)
	@bash $(SCAN) --json --top $(TOP)

report: scan show-report ## Regenerate report and print it

show-report: ## Print the current report to stdout
	@test -f $(REPORT) || { echo "no report yet — run: make scan" >&2; exit 1; }
	@cat $(REPORT)

featured: ## Reminder: invoke the curate-featured-projects skill in Claude Code
	@echo "Run the 'curate-featured-projects' skill in Claude Code, or:"
	@echo "  1) make scan"
	@echo "  2) review $(REPORT)"
	@echo "  3) edit the Featured Projects section of README.md"

clean-report: ## Remove the generated projects report
	@rm -f $(REPORT)
	@echo "removed $(REPORT)"

##@ Metrics SVGs (lowlighter/metrics workflow)

metrics-trigger: ## Manually trigger the metrics workflow on GitHub (requires gh CLI + auth)
	@command -v gh >/dev/null || { echo "gh CLI not installed" >&2; exit 1; }
	@gh workflow run metrics.yml
	@echo "triggered. tail with: make metrics-status"

metrics-status: ## Show recent runs of the metrics workflow
	@command -v gh >/dev/null || { echo "gh CLI not installed" >&2; exit 1; }
	@gh run list --workflow=metrics.yml --limit 5

##@ README

preview: ## Preview README.md in browser via grip (pip install grip)
	@command -v grip >/dev/null || { echo "grip not installed: pip install grip" >&2; exit 1; }
	@grip -b README.md

lint: ## Lint shell scripts with shellcheck (if installed)
	@command -v shellcheck >/dev/null || { echo "shellcheck not installed (skipping)"; exit 0; }
	@shellcheck $(SCAN) && echo "shellcheck: ok"

check: lint ## Sanity check: scripts executable, report dir exists
	@test -x $(SCAN) || { echo "$(SCAN) is not executable" >&2; exit 1; }
	@echo "ok"
