#!/usr/bin/env python3
"""Render the ops status line in README.md.

Everyone automates their profile; this publishes the SLO of the automation:
how many pipelines, how long since a human touched anything, the measured
success rate, and the last incident the watchdog caught. None of it can be
faked with a badge — the numbers come from the repo and the Actions API.

Usage:
  scripts/ops_status.py            # dry run: print the line
  scripts/ops_status.py --write    # update README.md between ops markers

Requires `gh` authenticated and a git checkout with history (not shallow).
"""

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README_PATH = ROOT / "README.md"
STATE_PATH = ROOT / "scripts" / "watchdog-state.json"
WORKFLOWS = ROOT / ".github" / "workflows"
REPO = "codyaverett/codyaverett"
HUMAN_AUTHOR = "codyaverett@gmail.com"
START_MARK = "<!-- ops:start -->"
END_MARK = "<!-- ops:end -->"


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def pipeline_count():
    return sum(
        1 for f in WORKFLOWS.glob("*.yml")
        if re.search(r"^\s*schedule:", f.read_text(encoding="utf-8"), re.MULTILINE)
    )


def days_since_human_edit(now):
    last = run(["git", "-C", str(ROOT), "log", "-1", "--format=%cI",
                f"--author={HUMAN_AUTHOR}"])
    if not last:
        raise SystemExit(
            f"no commit by {HUMAN_AUTHOR} in history — shallow clone? "
            "use fetch-depth: 0"
        )
    return (now - datetime.fromisoformat(last)).days


def success_rate():
    runs = json.loads(run(["gh", "run", "list", "--repo", REPO,
                           "--workflow", "metrics.yml", "--limit", "30",
                           "--json", "conclusion"]))
    finished = [r for r in runs if r["conclusion"]]
    if not finished:
        return "no runs yet"
    pct = 100 * sum(r["conclusion"] == "success" for r in finished) / len(finished)
    return f"{pct:.0f}% success over last {len(finished)} runs"


def last_incident():
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        incidents = state.get("incidents", [])
        if incidents:
            inc = incidents[0]
            text = f"{inc['target']} ({inc['date']}, auto-detected"
            if inc.get("issue"):
                text += f", [issue #{inc['issue']}](https://github.com/{REPO}/issues/{inc['issue']})"
            return text + ")"
    return "none on record"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="update README.md")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    days = days_since_human_edit(now)
    line = (
        f"<sub>Profile maintained by {pipeline_count()} automated pipelines · "
        f"last human edit {days} day{'s' if days != 1 else ''} ago · "
        f"metrics: {success_rate()} · "
        f"$0.00 inference this month (no inference pipelines… yet) · "
        f"last incident: {last_incident()} · "
        f"ledger: <code>git log --format='%h %(trailers:key=Workflow,valueonly)'</code></sub>"
    )

    if not args.write:
        print(line)
        return

    readme = README_PATH.read_text(encoding="utf-8")
    if START_MARK not in readme or END_MARK not in readme:
        raise SystemExit(f"README.md is missing {START_MARK} / {END_MARK} markers")
    pre, rest = readme.split(START_MARK, 1)
    _, post = rest.split(END_MARK, 1)
    README_PATH.write_text(f"{pre}{START_MARK}\n{line}\n{END_MARK}{post}", encoding="utf-8")
    print("ops line updated")


if __name__ == "__main__":
    main()
