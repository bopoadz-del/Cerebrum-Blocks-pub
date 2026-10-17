# Neutral Proof Platform

The Reasoning Kernel's domain-independence proof (mission Phase 7). A
deliberately neutral domain — equipment maintenance — running the FULL
kernel: deterministic formulas, rules, decision table, workflow state
machine, approval matrix, evidence, explanation and audit chain. No
finance, no construction, no retail, no insurance, no investment.

## The loop (all 15 mission steps)

1. `POST /login` — demo SSO stub; HMAC-signed principal tokens
2. `POST /inspections` — tenant-scoped inspection: risk = likelihood x
   consequence (1-5 scales, deterministic, precondition-guarded),
   condition matrix, critical/service rules, refusal rules
3. `POST /work_orders` — work order created in `draft`
4. `POST /work_orders/{id}/transition` — declared transitions only,
   role-checked, evidence-checked, guard-checked, approval-gated
5. `POST /work_orders/{id}/close-approval` — approval token issuance
   (role, self-approval, SoD enforced)
6. `GET /work_orders/{id}/report.xlsx` + `report.pdf`
7. `GET /work_orders/{id}/audit` — hash-chained audit, verified

Every domain decision is a kernel engine decision. The API layer only
carries requests. The LLM never authorizes, never computes, never moves
a workflow state.

## Run it

```
cd neutral_platform
pip install -r requirements.txt
NEUTRAL_DB_URL=sqlite:///./neutral_platform.db NEUTRAL_AUTH_SECRET="$(openssl rand -hex 32)" \
  uvicorn neutral_app.main:app --reload
```

`NEUTRAL_DB_URL` and `NEUTRAL_AUTH_SECRET` are required (no defaults). SQLite for the demo;
PostgreSQL via `NEUTRAL_DB_URL` with the password in `PGPASSWORD` (compose: set
`NEUTRAL_DB_PASSWORD` and `NEUTRAL_AUTH_SECRET` first):

```
docker compose up   # app + postgres:16
```

## Tests

```
python -m pytest neutral_platform/tests -q          # 17 tests, SQLite
NEUTRAL_DB_URL=postgresql+psycopg2://... \
  python -m pytest neutral_platform/tests/test_postgres.py   # PostgreSQL
```

CI (`.github/workflows/neutral-platform.yml`) runs the kernel suite, the
E2E suite on SQLite, the same E2E against a postgres:16 service, and a
Docker build + live smoke.

## Honest limitations

- Auth is an explicit demo stub — production needs real SSO. The rest of
  the platform never touches client-supplied identity fields.
- Kernel engines hold state in memory; the DB mirrors records and the
  audit chain. A production deployment hydrates engines from the DB.
- The pack is `domain_approved` because it is the kernel program's own
  neutral sample, oracle-verified in `tests/test_oracles.py`. Extracted
  donor packs remain `candidate` until the store gate promotes them.
