# Dependency adjudications

Dated notes for advisories that remain after the Linux resolve. Each
remaining finding has a registry row, a dated note, and a test twin in
`tests/test_dep_audit.py`. CI runs `scripts/dep_audit.py`, which audits
`requirements.txt` (the store pin set). A local-env scan on GitHub
Actions also reports the runner's `setuptools`; that is not a store pin
and is not adjudicated with `--ignore-vuln`.

A scanner summary is not evidence. Read the package's declared
`Requires-Dist` (and, for a pin we keep, `pip-audit`'s `fix_versions`)
before writing a note.

## Rules

1. **Upgrade when the graph allows it.** Do not adjudicate a finding whose
   fix satisfies every installed package's declared constraint.
2. **No bare suppressions.** `pip-audit --ignore-vuln` is forbidden in
   workflows. The only ignore path is this registry, and only while its
   evidence still holds.
3. **A fix appearing later is a red check.** If `fix_versions` becomes
   non-empty and the installed pin is still below it, the note is stale.
   Upgrade or rewrite the note. Do not widen the ignore.

## What this pass did (2026-09-11, Linux)

- **cryptography 48.0.1 → 50.0.1.** Three PYSEC rows (3552 / 3553 / 3554).
  MLflow 3.16.0 declares `cryptography<51,>=43.0.0`. Highest published
  fix is `50.0.0`; latest is `50.0.1`. Upgraded, not adjudicated.
- **pypdf 6.14.2 → 6.18.1.** Six PYSEC rows. Highest published fix is
  `6.16.1`; latest is `6.18.1`. Upgraded, not adjudicated.
- **mlflow 3.14.0 → 3.16.0.** PYSEC-2026-3687 and GHSA-gqvg-gmmx-x4hm
  fix at `3.15.0`. PYSEC-2026-3865 (empty `fix_versions` on 3.14.0)
  is gone on 3.16.0. Upgraded, not adjudicated.
- **python-dotenv 1.0.1 → 1.2.2.** PYSEC-2026-2270 (not in the original
  five; it appeared on the live Linux resolve). Fix is `1.2.2`.
  Upgraded, not adjudicated.
- **deep-translator 1.11.4.** PYSEC-2022-252, no fix, latest equals pin.
  See [2026-09-11-deep-translator.md](2026-09-11-deep-translator.md).
- **click 8.1.8.** PYSEC-2026-2132 fix is `8.3.3`. `gTTS 2.5.4` declares
  `click<8.2,>=7.1`. Constrained, not ceilinged. See
  [2026-09-11-click.md](2026-09-11-click.md).

## Click (do not invent a ceiling)

`gTTS 2.5.4` declares `click<8.2,>=7.1`. That is a real Requires-Dist,
not a scanner story. The prior Factory miss was inventing a `click<8.2`
ceiling when `gTTS` was not even a factory pin — the real published fix
was `click 8.3.3`. Adjudicate against declared constraints: if a newer
`gTTS` (or dropping it) lets the graph take `>=8.3.3`, upgrade. If
`gTTS 2.5.4` stays and still caps `<8.2`, the note must name that
Requires-Dist, not a ceiling we wrote ourselves.

## Adding a note

1. Run `python3 scripts/dep_audit.py` on Linux.
2. For each remaining id: read `importlib.metadata.requires` / PyPI
   `requires_dist` for every package that constrains it.
3. Add a registry row with `date`, `note`, `decision`, `evidence`.
4. Write the dated note. Name the declared constraint, not the scanner
   blurb.
5. Extend `tests/test_dep_audit.py` so deleting the note or the evidence
   check fails.
