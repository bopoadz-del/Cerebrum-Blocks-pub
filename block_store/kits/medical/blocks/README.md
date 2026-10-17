# Medical Domain Blocks

| Block ID | Module | Description |
|----------|--------|-------------|
| `medical_ehr_connector` | `blocks/medical_ehr_connector.py` | Async FHIR R4 connector — fetches Patient, Observation, MedicationRequest resources |

## Registration

- **Kit dev:** source lives under `block_store/kits/medical/blocks/`.
- **Runtime:** enable with `CEREBRUM_DOMAIN_KITS=medical` or install the kit from the Block Store.
- **Loader map:** `app/core/domain_kit_loader.py` → `app.blocks.medical_ehr_connector.MedicalEHRConnectorBlock`.

## Environment

| Variable | Purpose |
|----------|---------|
| `FHIR_BASE_URL` | FHIR server base URL (required) |
| `FHIR_ACCESS_TOKEN` | Optional Bearer token |

## Params (workflow builder)

- `patient_id` — subject filter
- `resource_type` — `Patient` \| `Observation` \| `MedicationRequest`
- `limit` — max bundle entries (default 20)

Install copies `blocks/medical_ehr_connector.py` → `app/blocks/medical_ehr_connector.py` per manifest `skeleton_artifacts`.
