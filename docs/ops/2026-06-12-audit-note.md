# Audit note — 2026-06-12

A multi-agent review of this repo produced two findings worth recording,
one real and one instructive false positive.

## Real: issue_pr_lang.svg shipped an all-zeros section for months

The card's `plugin_followup` rendered two sections. The `repositories`
section (issues/PRs **on** owned repos) showed `0 open / 0 closed / 0
drafts / 0 skipped` — months of a visibly broken-looking card under green
CI, because the underlying repos see little inbound traffic. The `user`
section directly below it had real numbers (43 open / 99 closed issues,
31 merged PRs).

**Fix:** `plugin_followup_sections: user` — keep the section with signal,
drop the one structurally doomed to zeros.

**Lesson → watchdog:** a renderer can succeed while producing content a
visitor reads as broken. The watchdog now asserts nonzero counts on this
card specifically.

## False positive: the "two-week outage" that wasn't

The audit (running against a local clone) reported all SVGs stale since
May 29 despite a daily cron — a two-week silent outage. The remote had
fresh bot commits the whole time; the local clone was simply two weeks
behind. The staleness measurement was correct, the corpus was wrong.

**Lesson → watchdog:** staleness is measured from the last commit touching
the file on the branch being checked out fresh in CI, never from local
file mtimes or a possibly-stale working copy.

## Also fixed in the same pass

- 8 independent metrics jobs (one per SVG, racing, up to 8 bot commits per
  run) consolidated into one job landing a single verified commit.
- Action refs SHA-pinned (`lowlighter/metrics@latest`, two forks on
  mutable branch refs).
- `config_timezone` moved from a repo secret to plain config — a timezone
  is not a secret.
- Stale "(each hour)" comment on a daily cron corrected.
- Renders trimmed from 8 SVGs to the 5 the README displays (also drops one
  of the unpinned forks entirely).
