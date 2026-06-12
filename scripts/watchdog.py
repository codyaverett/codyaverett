#!/usr/bin/env python3
"""Profile watchdog: asserts the dashboard cards in README.md are alive,
self-heals, and quarantines cards that stay broken.

Green CI is not the same as a working profile — the renderer can succeed
while a card silently renders zeros or goes stale. So this checks what
visitors actually see:

  - every displayed card must have been re-committed recently (staleness is
    measured from the last commit touching the file, not mtime; renders have
    historically changed every daily run)
  - issue_pr_lang.svg must contain at least one nonzero count (this card
    once showed an all-zeros section for months under green CI)
  - every displayed card must be non-trivially sized
  - the metrics pipeline's latest run must be recent and green

Failure handling, per target, tracked in scripts/watchdog-state.json:
  1st consecutive failure  -> re-dispatch metrics.yml (self-heal) and open
                              a GitHub issue with the evidence
  2nd consecutive failure  -> quarantine: the README card is swapped for a
                              plain-text stale notice linking the issue.
                              A README that refuses to display frozen lies.
  recovery                 -> restore the card, close the issue.

Usage:
  scripts/watchdog.py            # dry run: report check results, no side effects
  scripts/watchdog.py --write    # apply state/README changes, heal, file issues
  scripts/watchdog.py --today 2026-06-12   # override today (testing)

Requires `gh` authenticated. Exit code 0 even when checks fail (the failure
is recorded and acted on; the workflow itself succeeded).
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README_PATH = ROOT / "README.md"
STATE_PATH = ROOT / "scripts" / "watchdog-state.json"
REPO = "codyaverett/codyaverett"
PIPELINE = "metrics.yml"
PIPELINE_MAX_AGE_HOURS = 30  # daily cron + generous queue slack
MAX_INCIDENTS = 20

IMG_LINE = '  <img align="center" width="49%" src="./{card}" />'
QUARANTINE_LINE = (
    "  <em>{card} — data stale since {date}; auto-repair attempted, "
    "see <a href=\"https://github.com/{repo}/issues/{issue}\">issue #{issue}</a>"
    "</em> <!-- quarantine:{card} -->"
)


def svg_text(path):
    raw = path.read_text(encoding="utf-8", errors="replace")
    return [t.strip() for t in re.findall(r">([^<>]{1,80})<", raw) if t.strip()]


def gh(args, parse_json=True):
    result = subprocess.run(["gh"] + args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"gh {args[0]} failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if parse_json else result.stdout.strip()


CARD_MAX_AGE_HOURS = 72  # renders change every daily run; 3 days = stuck


def card_age_hours(card, now):
    out = subprocess.run(
        ["git", "-C", str(ROOT), "log", "-1", "--format=%cI", "--", card],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    if not out:
        return None
    return (now - datetime.fromisoformat(out)).total_seconds() / 3600


def check_card(card, now):
    """Returns None if healthy, else a failure detail string."""
    path = ROOT / card
    if not path.exists():
        return "file missing"
    if path.stat().st_size < 1024:
        return f"suspiciously small ({path.stat().st_size} bytes)"
    age = card_age_hours(card, now)
    if age is not None and age > CARD_MAX_AGE_HOURS:
        return f"stale: last commit touching it is {age:.0f}h old (max {CARD_MAX_AGE_HOURS}h)"
    if card == "issue_pr_lang.svg":
        numbers = [int(t) for t in svg_text(path) if t.isdigit()]
        if not any(n > 0 for n in numbers):
            return "all counts are zero"
    return None


def check_pipeline(now):
    runs = gh(
        ["run", "list", "--repo", REPO, "--workflow", PIPELINE, "--limit", "1",
         "--json", "conclusion,updatedAt,databaseId"]
    )
    if not runs:
        return "no runs found"
    run = runs[0]
    age_hours = (now - datetime.fromisoformat(run["updatedAt"].replace("Z", "+00:00"))).total_seconds() / 3600
    if run["conclusion"] not in ("success", None):
        return f"last run concluded {run['conclusion']} (run {run['databaseId']})"
    if age_hours > PIPELINE_MAX_AGE_HOURS:
        return f"last run is {age_hours:.0f}h old (max {PIPELINE_MAX_AGE_HOURS}h)"
    return None


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"consecutive": {}, "quarantined": {}, "incidents": []}


def displayed_cards(readme):
    return re.findall(r'src="\./([\w-]+\.svg)"', readme)


def heal(write):
    if write:
        gh(["workflow", "run", PIPELINE, "--repo", REPO], parse_json=False)
    return "re-dispatched metrics.yml"


def open_issue(target, detail, today, write):
    if not write:
        return 0
    out = gh(
        ["issue", "create", "--repo", REPO,
         "--title", f"watchdog: {target} failing content assertions",
         "--body",
         f"Detected {today.isoformat()} by the watchdog workflow.\n\n"
         f"**Target:** `{target}`\n**Detail:** {detail}\n\n"
         f"Self-heal (metrics re-dispatch) was attempted. If this fails again "
         f"on the next pass, the card will be quarantined in the README.\n"],
        parse_json=False,
    )
    match = re.search(r"/issues/(\d+)", out)
    return int(match.group(1)) if match else 0


def close_issue(number, target, write):
    if write and number:
        gh(["issue", "close", str(number), "--repo", REPO,
            "--comment", f"watchdog: {target} recovered."], parse_json=False)


def quarantine(readme, card, date, issue):
    return readme.replace(
        IMG_LINE.format(card=card),
        QUARANTINE_LINE.format(card=card, date=date, repo=REPO, issue=issue),
    )


def restore(readme, card):
    return re.sub(
        r'^  <em>.*<!-- quarantine:' + re.escape(card) + r' -->$',
        IMG_LINE.format(card=card),
        readme,
        flags=re.MULTILINE,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="apply changes and side effects")
    parser.add_argument("--today", help="override today as YYYY-MM-DD (testing)")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    today = datetime.fromisoformat(args.today).date() if args.today else now.date()

    readme = README_PATH.read_text(encoding="utf-8")
    state = load_state()
    targets = {card: check_card(card, now) for card in displayed_cards(readme)}
    # quarantined cards are not in the README as <img>, keep checking them
    for card in list(state["quarantined"]):
        targets.setdefault(card, check_card(card, now))
    targets[PIPELINE] = check_pipeline(now)

    summary = []
    for target, detail in targets.items():
        if detail is None:
            state["consecutive"].pop(target, None)
            quarantined = state["quarantined"].pop(target, None)
            if quarantined:
                readme = restore(readme, target)
                close_issue(quarantined.get("issue", 0), target, args.write)
                summary.append(f"recovered: {target}")
            continue

        count = state["consecutive"].get(target, 0) + 1
        state["consecutive"][target] = count
        print(f"FAIL {target}: {detail} (consecutive: {count})", file=sys.stderr)

        if count == 1:
            action = heal(args.write)
            issue = open_issue(target, detail, today, args.write)
            state["incidents"].insert(0, {
                "date": today.isoformat(), "target": target,
                "detail": detail, "issue": issue,
            })
            state["incidents"] = state["incidents"][:MAX_INCIDENTS]
            summary.append(f"heal: {target} ({action}, issue #{issue})")
        elif target != PIPELINE and target not in state["quarantined"]:
            issue = next(
                (i.get("issue", 0) for i in state["incidents"] if i["target"] == target), 0
            )
            state["quarantined"][target] = {"since": today.isoformat(), "issue": issue}
            readme = quarantine(readme, target, today.isoformat(), issue)
            summary.append(f"quarantine: {target}")
        else:
            summary.append(f"still failing: {target}")

    if args.write:
        README_PATH.write_text(readme, encoding="utf-8")
        STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    print("; ".join(summary) if summary else "all checks green")


if __name__ == "__main__":
    main()
