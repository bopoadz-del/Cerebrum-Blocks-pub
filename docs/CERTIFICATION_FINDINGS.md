# What certification found

Certifying the Store's blocks against the three bars surfaced defects that no
existing test caught, because the control-delete asks a question the tests were
not asking: *if this block silently returned a plausible success, would anything
notice?*

No block source was edited while producing this list. Every item below was
observed, not inferred. File and line references are to this branch.

---

## 1. Blocks that report success with invented data

These are the serious ones. A caller checking `status` cannot tell them from a
real result.

**`app/blocks/bim_extractor.py:78-99`** — given a missing `file_path`, or a path
that does not exist, returns `status: "success"` with hard-coded quantities:
45 `IfcWall`, `total_volume_m3: 125.5`, `concrete_volume_m3: 446.5`,
`steel_weight_kg: 53580`. The_Fork's equivalent returns `status: "error"`.

**`app/blocks/capture.py`** (`_capture`) — with no resolvable image, returns
`status: "success"` and fabricated content: `ocr_text` = "Demo: Site inspection
photo showing concrete pour in progress.", `structured.activity` = "Concrete
Pour", `location` = "Level 3, Grid B-C/4-5", `confidence` = 0.85. Pinned by
`tests/blocks/test_capture_real_payload.py::test_capture_without_an_image_returns_a_fabricated_demo_record`.

**`app/blocks/boq_processor.py`** (`_to_float`) — swallows `ValueError` and
returns `0.0`, so a BOQ line reading `"Provisional Sum"` or `"Lot"` becomes zero
with no signal and the bill total under-counts. The_Fork raises, so a caller can
distinguish a true zero from an unparseable cell, and carries a `_to_float_safe`
wrapper for the cases that genuinely want a default.

## 2. A safety guard that is inert over the block's own advertised input

**`app/blocks/clash_resolver.py:79` and `:102`** — both fall guards read
`getattr(element, "is_gravity", False)`, which is always `False` for a dict.
`block.json` advertises JSON input (`ui_schema.input.type == "json"`).

Reproduced:

| input shape | `_free_axes` | `preserves_fall(el, (0,0,500))` |
|---|---|---|
| dict (the advertised surface) | `[0, 1, 2]` | `True` — a 500 mm lift of a drain, approved |
| attribute-carrying object | `[0, 1]` | `False` — correctly rejected |

The module docstring calls a vertical move on a gravity element "the one failure
this block must never allow", and the comment at `resolve()` calls
`preserves_fall` "the second lock". Over JSON both locks are open. It looks safe
today only because the smallest-magnitude candidate happens to be lateral.

## 3. Integrity and credential handling

**`app/blocks/webhook.py:89` vs `:110`** — the HMAC is computed over
`str(payload)`, the Python dict repr (`{'invoice': 7}`), while aiohttp transmits
`json=payload` (`{"invoice": 7}`). The signed bytes are not the transmitted
bytes, so **no receiver can ever verify `X-Webhook-Signature`**.

**`app/blocks/webhook.py:99`** — `X-Webhook-Timestamp` is
`int(asyncio.get_event_loop().time())`, a monotonic clock reading against an
arbitrary epoch, not a wall-clock time. Replay windows on the receiver are
meaningless.

**`app/blocks/onedrive.py`** — a 401 on the refresh grant raises `RuntimeError`,
which the `list` branch converts to `{"status": "success", "mode":
"unconfigured"}` — identical in shape to "no credentials were configured". A
revoked credential is indistinguishable from an unconfigured one.

**`app/core/learning_store.py:72`** — `FileLearningStore.save()` is a
non-atomic `write_text` with no lock and no `os.replace`. Reproduced: 120
concurrent writers plus one reader gave torn or invalid JSON on **41 of 58
reads**. `LearningEngineBlock._load_state` catches the parse error and returns
`{"formulas": {}, "history": []}`, so a read during any write silently yields an
empty learning state.

## 4. Code that cannot run

**`app/blocks/ocr.py`** (`_detect_markup`) — its first statement is an
unconditional `from app.core.redline import detect_redlines, summarize_markup`,
**outside** the function's `try`. `app/core/redline.py` does not exist in this
repo. So every image and every PDF raises `ModuleNotFoundError` before a pixel
is read; `UniversalBlock.execute` catches it and returns a generic error
envelope, which is why nothing noticed. `app/blocks/ocr_v2.py:192` carries the
same dead import. `app/core/image_quality.py` is also absent
(`ocr.py:199`, `ocr.py:348`).

**`app/blocks/project_reasoner.py`** — imports `search_project_documents` from
`app.core.doc_index` inside a bare `try/except`. That module has never existed
here. The block's entire document-grounded fallback is unreachable: excerpts are
always `[]`, the planner-failure RAG answer never fires, `sources` is always
empty.

**`app/blocks/bim.py`** — `_extract_dwg_real` is dispatched at line 78 and never
defined, so `extract_dwg_metadata` is an unconditional `AttributeError`. The
block also never emits a top-level `status` on any path.

## 5. Silent truncation and undisclosed fallback

**`app/blocks/translate.py`** — cuts text to `text[:5000]` before translating
while `char_count` reports the full length. A 6,000-character document returns
`char_count: 6000` with 1,000 characters never translated and no flag. Unknown
languages are also not refused: `_normalize_lang("Esperanto")` returns
`"esperanto"` and hands that to the provider as a language code.

**`app/blocks/historical_benchmark.py`** — `_location_factor()` returns a bare
float instead of `(factor, matched)`, so an unlisted country is silently priced
at the US baseline with no `location_matched: False` and no `source_note`. Rates
also carry no `basis` field, so `cost_estimate` cannot warn when it sums
material-only and all-in rates together.

**`app/blocks/web.py`** — `_clean_text()` decomposes `<nav>`/`<footer>` in place
*before* `_extract_links()` runs, so `fetch` and `extract_links` return different
link sets from the same document.

**`app/blocks/sandbox.py:150`** — `self.policies` is seeded only in
`_legacy_initialize()`, so a bare `SandboxBlock()` dies on `KeyError: 'default'`.
`app/blocks/sandbox.py:381-383` and `:472-474` pass `timeout=policy.max_cpu_time`
straight to `proc.communicate()`, charging subprocess spawn against the CPU
budget — The_Fork hit this in CI and fixed it with a spawn grace.

## 6. Where `block.json` contradicts the code

- `block_registry/document_engine_block/block.json` — **missing entirely** (bar 2 fails).
- `block_registry/learning_engine/block.json` — advertises an input
  `storage_path` defaulting to `/tmp/cerebrum_learning_engine.json`, which the
  block deliberately removed and which
  `tests/blocks/test_learning_engine_durability.py::test_default_lands_on_memory_not_tmp`
  asserts is absent.
- `block_registry/learning_engine/block.json` — carries an acceptance criterion
  `missing_credential` ("fails loud when a required credential is absent") that
  this block requires no credential to satisfy and cannot perform.
- `block_registry/spec_analyzer/block.json` — `"acceptance": []`, while the block
  performs three real refusals that nothing committed it to.
- `app/blocks/bcf_export.py` — the `export` action is unreachable over the
  advertised JSON input: `export_bcf` does attribute access (`f.kind`), so a JSON
  payload returns `'dict' object has no attribute 'kind'`. It refuses rather than
  writing a bogus archive, so this is a contract defect, not a safety one. Only
  `validate` is callable from JSON.
- `app/blocks/search.py` — the chaining shape `{"result": {"text": ...}}` that
  `tests/blocks/test_chaining.py` passes has no top-level `query`/`text`/`input`,
  so `process` refuses with "Query is required". The existing test never noticed
  because it asserts only envelope keys.

## 7. Dependencies missing from requirements

- **`trimesh`** — required by `app/blocks/clash_resolver.py` and
  `app/blocks/geometry_engine.py`. Added on this branch to `requirements.txt`
  and `requirements.lock` (pinned `4.12.2`; CI's `lockfile-consistency` job is
  fail-closed on a requirements change with no lock delta). Declared but not yet
  executed here — the trimesh-gated files first run in CI.
- **`ultralytics`** — imported by `app/blocks/safety_world_detector.py:37` and
  lazily by `app/blocks/image.py`. Declared in no requirements file. In any
  environment built from `requirements.txt` the detector can never construct, so
  `safety_world_detector` is a permanent refusal — and it is certified today
  **entirely on its refusal paths**. The_Fork pins `ultralytics==8.4.66` in
  `requirements-cv.txt`.
- **`onnxruntime`** — a runtime dependency with no import statement anywhere to
  grep for: the baked detector weights are `.onnx`, and ultralytics needs
  onnxruntime to execute an ONNX graph. Neither it nor a weights artifact ships
  here.

## 8. Modules The_Fork has that this Store does not

These blocked harvested tests that were otherwise ready to run:

| module | lines | what it unblocks |
|---|---|---|
| `app/core/drive_auth.py` + `app/routers/drive.py` | 135 + 742 | The real Google Drive OAuth path and `POST /v1/projects/{id}/drive/import`. The_Fork's 326 lines of tests for it run fully offline — no credentials. |
| `app/core/doc_index.py` + `app/core/projects.py` | — | ~1,860 lines of real-artifact ingestion coverage, plus `project_reasoner`'s grounded fallback (see §4). |
| `app/core/deployment_profile.py` | — | The zero-egress on-prem gate. `grep DEPLOYMENT_PROFILE` returns nothing here, so no block refuses to egress on an air-gapped deploy. |
| `app/core/redline.py`, `app/core/image_quality.py` | — | Makes `ocr` runnable at all (see §4). |
| `scripts/synthetic_fixtures.py` | — | The only end-to-end `SpecAnalyzerBlock.process` test in either repo. |

The_Fork also has ten blocks this Store does not: `aconex`, `cpm_engine`,
`fasttrack_analyzer`, `manpower_planner`, `mcp_consumer`, `project_dashboard`,
`schedule_excel_writer`, `schedule_generator`, `scope_extractor`,
`validation_pipeline`.
