# Profile Ops

This profile's automation is run like production infrastructure: one
render pipeline, a watchdog that checks what visitors actually see, a
public status line with the measured SLO, and a queryable commit ledger.
Green CI is not the bar — correct, fresh, visible content is.

## Pipelines

| Workflow | Schedule | Job |
|---|---|---|
| `metrics.yml` | daily 00:00 UTC | Render the 5 displayed dashboard SVGs, land them as ONE verified commit |
| `watchdog.yml` | daily 13:00 UTC | Content-assert the cards, self-heal, quarantine |
| `decay.yml` | weekly Mon 06:17 UTC | Featured Projects decay pass (see [featured-projects.md](../featured-projects.md)) |

All third-party actions are SHA-pinned. All scheduled workflows have
`concurrency` groups. Automation commits are created via the GraphQL
`createCommitOnBranch` API (`scripts/verified-commit.sh`), which means:

- **Verified badge** — GitHub signs the commit itself; zero key management.
- **One commit per run** — this pipeline used to be 8 independent jobs
  each committing its own SVG, racing each other up to 8 bot commits a run.
- **Structured trailers** — every automation commit carries `Workflow`,
  `Run` (link to the exact Actions run), `Files`, and `Inputs-SHA256` (hash
  of the workflow definition that produced it). `make ledger` queries it.

## Watchdog

`scripts/watchdog.py`, daily, offset 13h from the render. Asserts:

- every card displayed in README.md was re-committed within 72h
  (staleness measured from the **last commit touching the file**, not mtime);
- `issue_pr_lang.svg` contains at least one nonzero count — this card
  shipped an all-zeros section for months under green CI before the
  2026-06-12 audit caught it ([audit note](2026-06-12-audit-note.md));
- cards are non-trivially sized; the latest metrics run is recent and green.

Failure ladder (state in `scripts/watchdog-state.json`):

1. **First consecutive failure** — re-dispatch `metrics.yml` (self-heal)
   and open an issue with the evidence.
2. **Second consecutive failure** — quarantine: the README card is swapped
   for a plain-text stale notice linking the issue. The README refuses to
   display frozen lies.
3. **Recovery** — card restored, issue auto-closed.

## Operating it

```sh
make watchdog         # run assertions locally, no side effects
make ledger           # automation commits with trailers
make metrics-trigger  # force a render pass
gh workflow run watchdog.yml
```

## Known limitations

- `verified-commit.sh` uses `expectedHeadOid` = checkout HEAD; if the branch
  moves mid-run the commit fails loudly rather than force-landing. Re-run.
- Watchdog staleness assumes renders change daily (they historically do —
  the SVGs embed run-varying content). If a card legitimately stops
  changing, raise `CARD_MAX_AGE_HOURS` rather than letting it red-bar.
- The 72h threshold tolerates up to 2 missed crons before alarming.
- `basic_output_example.yml` is a manual-only scratch workflow, not part of
  the pipeline count (no schedule).
