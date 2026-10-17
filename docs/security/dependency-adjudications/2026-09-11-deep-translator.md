# deep-translator — PYSEC-2022-252

Date: 2026-09-11

## PYSEC-2022-252

- Package: deep-translator
- Installed pin: 1.11.4
- Latest published: 1.11.4
- pip-audit `fix_versions`: (empty)

### Decision: accept_until_fix

PYSEC-2022-252 records a PyPI account takeover: a phishing compromise
published a malicious deep-translator release that exfiltrated environment
variables and ran installer malware. There is **no patched version**. The
current 1.11.4 is the latest published release; pip-audit lists no
`fix_versions`.

This pin is the translate block's optional backend (`deep-translator` in
`requirements.txt`). We keep 1.11.4 — the version the advisory describes as
the compromised-project pin, not a newer unknown release — until the
maintainer publishes a fixed release. A non-empty `fix_versions` list makes
this note stale: upgrade, do not widen an ignore.

### Evidence

- PyPI latest == 1.11.4
- pip-audit `fix_versions` is empty
- No `--ignore-vuln` in CI
