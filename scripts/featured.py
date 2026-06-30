#!/usr/bin/env python3
"""Decay-driven Featured Projects renderer.

Reads the candidate pool from featured.toml, measures author-filtered commit
activity on each repo's default branch via the GitHub API (`gh api`), and
renders the top candidates into the marked Featured Projects block of
README.md. Activity is measured by *author* commits, not pushed_at, so a
Dependabot bump cannot keep a zombie project featured.

Rules:
  - A candidate earns a slot only if the author committed to the default
    branch within the last `window_days` (default 90).
  - At most `max_slots` (default 3) render, ranked by commits in the window,
    ties broken by most recent commit.
  - A slotted project that goes quiet is culled: removed from the slots and
    recorded as a struck-through tombstone (last two culls render).
  - Fewer qualifying candidates than slots is a designed state, not an error.

Usage:
  scripts/featured.py            # dry run: print the rendered block
  scripts/featured.py --write    # update README.md + featured-state.json,
                                 # print a one-line change summary to stdout
  scripts/featured.py --today 2026-06-12   # override today (for testing)

Requires `gh` authenticated (GH_TOKEN in CI). Exit codes: 0 ok, 1 config or
API error.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "featured.toml"
STATE_PATH = ROOT / "scripts" / "featured-state.json"
README_PATH = ROOT / "README.md"
START_MARK = "<!-- featured:start -->"
END_MARK = "<!-- featured:end -->"
MAX_TOMBSTONES = 2


def load_config(path):
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib

        return tomllib.loads(text)
    except ModuleNotFoundError:
        return parse_minimal_toml(text)


def parse_minimal_toml(text):
    """Fallback for python < 3.11: parses only the subset featured.toml uses
    (top-level scalars and [[project]] tables with string/int values)."""
    config = {"project": []}
    current = config
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "[[project]]":
            current = {}
            config["project"].append(current)
            continue
        match = re.match(r'^(\w+)\s*=\s*(?:"(.*)"|(\d+))$', line)
        if not match:
            raise ValueError(f"unparseable featured.toml line: {raw!r}")
        key, string_val, int_val = match.groups()
        current[key] = string_val if string_val is not None else int(int_val)
    return config


def gh_api(args):
    result = subprocess.run(
        ["gh", "api"] + args, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh api {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def repo_activity(repo, author, since):
    """Returns (commits_in_window, last_author_commit_date or None)."""
    shas = gh_api(
        [
            "--paginate",
            f"repos/{repo}/commits?author={author}&since={since.isoformat()}T00:00:00Z&per_page=100",
            "--jq",
            ".[].sha",
        ]
    ).split()
    last_raw = gh_api(
        [
            f"repos/{repo}/commits?author={author}&per_page=1",
            "--jq",
            ".[0].commit.committer.date // empty",
        ]
    ).strip()
    last = datetime.fromisoformat(last_raw.replace("Z", "+00:00")).date() if last_raw else None
    return len(shas), last


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"slots": [], "culls": []}


def render(slotted, open_slots, tombstones, window_days):
    lines = []
    if slotted:
        for entry in slotted:
            project, activity = entry["project"], entry
            lines.append(f"### [{project['name']}](https://github.com/{project['repo']})")
            lines.append(
                f'<img align="right" alt="last commit" '
                f'src="https://img.shields.io/github/last-commit/'
                f'{project["repo"]}?style=flat-square&label=updated">'
            )
            lines.append(f"{project['pitch']} _Stack: {project['stack']}_")
            lines.append("")
        if open_slots:
            plural = "s" if open_slots > 1 else ""
            lines.append(f"_{open_slots} slot{plural} open._")
            lines.append("")
    else:
        lines.append("_Nothing featured right now — heads-down elsewhere._")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="update README and state")
    parser.add_argument("--today", help="override today as YYYY-MM-DD (testing)")
    args = parser.parse_args()

    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    config = load_config(CONFIG_PATH)
    window_days = config.get("window_days", 90)
    max_slots = config.get("max_slots", 3)
    author = config["author"]
    since = today - timedelta(days=window_days)

    candidates = []
    for project in config["project"]:
        count, last = repo_activity(project["repo"], author, since)
        days_since = (today - last).days if last else None
        active = last is not None and days_since <= window_days
        candidates.append(
            {
                "project": project,
                "count": count,
                "last": last.isoformat() if last else None,
                "days_left": (window_days - days_since) if active else 0,
                "active": active,
            }
        )

    qualifying = [c for c in candidates if c["active"]]
    # rank by commits in window, ties broken by most recent commit
    qualifying.sort(key=lambda c: c["last"], reverse=True)
    qualifying.sort(key=lambda c: c["count"], reverse=True)
    slotted = qualifying[:max_slots]
    slot_names = [c["project"]["name"] for c in slotted]

    state = load_state()
    previous = state.get("slots", [])
    active_names = {c["project"]["name"] for c in qualifying}
    culled = [name for name in previous if name not in slot_names and name not in active_names]
    promoted = [name for name in slot_names if name not in previous]

    culls = state.get("culls", [])
    culls = [{"name": n, "date": today.isoformat()} for n in culled] + culls
    tombstones = culls[:MAX_TOMBSTONES]

    block = render(slotted, max_slots - len(slotted), tombstones, window_days)

    if not args.write:
        print(block)
        return

    readme = README_PATH.read_text(encoding="utf-8")
    if START_MARK not in readme or END_MARK not in readme:
        sys.exit(f"README.md is missing {START_MARK} / {END_MARK} markers")
    pre, rest = readme.split(START_MARK, 1)
    _, post = rest.split(END_MARK, 1)
    README_PATH.write_text(
        f"{pre}{START_MARK}\n{block}\n{END_MARK}{post}", encoding="utf-8"
    )
    STATE_PATH.write_text(
        json.dumps({"slots": slot_names, "culls": culls[:10]}, indent=2) + "\n",
        encoding="utf-8",
    )

    actions = []
    if promoted:
        actions.append("promote: " + ", ".join(promoted))
    if culled:
        actions.append("cull: " + ", ".join(culled))
    print("; ".join(actions) if actions else "refresh slot metadata")


if __name__ == "__main__":
    main()
