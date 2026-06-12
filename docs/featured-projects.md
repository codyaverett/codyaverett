# Decay-Driven Featured Projects

The Featured Projects section of `README.md` is automation whose only verb is
subtraction. Slots are earned by recent work and lost by silence — the system
never pads the list, and an empty slot is a designed state, not a bug.

## Rules

- **Candidate pool**: hand-written pitches live in [`featured.toml`](../featured.toml).
  Max 6 candidates, public repos only (private repos 404 for profile visitors).
- **Earning a slot**: a candidate qualifies only if `author` has commits on the
  repo's **default branch** within the last `window_days` (90). Activity is
  measured by author-filtered commits via the GitHub API — not `pushed_at` —
  so a Dependabot bump cannot keep a zombie project featured.
- **Ranking**: top `max_slots` (3) qualifying candidates render, ordered by
  commit count in the window; ties broken by most recent commit.
- **Culling**: a previously slotted project that no longer qualifies is removed
  and recorded as a struck-through tombstone under the slots
  (`~~name~~ culled YYYY-MM-DD`, zero adjectives). The last two culls render.
- **Days until cull**: each slot shows its remaining budget
  (`window_days - days since last author commit`) so the rule is legible.
- **Empty state**: with no qualifying candidates the section renders
  "Nothing earning a slot right now — heads-down elsewhere."

## Moving parts

| File | Role |
|---|---|
| `featured.toml` | Candidate pool + knobs (`max_slots`, `window_days`, `author`) |
| `scripts/featured.py` | Renderer; queries `gh api`, rewrites the marked README block |
| `scripts/featured-state.json` | Current slots + cull history (drives tombstones and promote/cull detection) |
| `.github/workflows/decay.yml` | Weekly cron (Mon 06:17 UTC) + manual dispatch; commits only on diff |
| `README.md` | Render target between `<!-- featured:start -->` / `<!-- featured:end -->` |

## Operating it

```sh
make featured        # dry run: print the rendered block
make featured-write  # apply to README.md + state file
gh workflow run decay.yml   # force a pass in CI
```

Commits from the workflow use messages like `chore(featured): promote: x; cull: y`
or `chore(featured): refresh slot metadata`, so `git log -- README.md` doubles
as the promotion/cull ledger.

To add a candidate: append a `[[project]]` block to `featured.toml` with
`name`, `repo` (`owner/name`), `pitch` (~80 chars, no marketing fluff), and
`stack`. The decay pass decides whether it ever renders.

## Known limitations / common issues

- `scripts/featured.py` needs an authenticated `gh` (CI uses `github.token`;
  it can read all candidates because they are public).
- Local runs may differ from CI by a commit or two if local clones are ahead
  of GitHub — the API is the source of truth.
- The minimal TOML fallback parser (for python < 3.11) only supports the
  subset `featured.toml` uses: top-level scalars and `[[project]]` string/int
  pairs. Keep the file in that shape.
- Curation of *which* candidates belong in the pool is still human/agent work —
  the `curate-featured-projects` skill and `make scan` feed that decision.
