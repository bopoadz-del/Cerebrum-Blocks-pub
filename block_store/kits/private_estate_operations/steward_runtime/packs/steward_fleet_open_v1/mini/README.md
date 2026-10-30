# SYNTHETIC TEST FIXTURE — vehicles.jsonl

Every row in `vehicles.jsonl` is synthetic test data authored for CI (ST-7). It
describes no real vehicle, person, company, estate or vehicle. All identifiers
carry a `synthetic` / `SYNTH` prefix. Rows carry only the fields the pack
loader in `steward_runtime/packs/__init__.py` reads, and are checked against
that loader by `tests/test_st7_steward_fixtures.py`.
