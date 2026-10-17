# Connector Workflows

Reactive video analytics, medical EHR connector patterns, and the platform
reactive workflow engine for Cerebrum Blocks.

## Reactive workflow engine (auto-chaining)

The platform **ReactiveWorkflowEngine** (`app/core/reactive_workflow.py`) matches
connector events to registered triggers and executes block step chains without
manual `video_anomaly_trigger` wiring.

### Default built-in trigger

| Event type       | Min severity | Steps                          |
|------------------|--------------|--------------------------------|
| `video.anomaly`  | `medium`     | `notification` (action: send)  |

When `video_metadata_ingest` stores metadata with anomalies and `auto_trigger`
is true (default), the engine dispatches `video.anomaly` and sends a notification.

Environment overrides:

- `VIDEO_ANOMALY_NOTIFY_CHANNEL` — default notification channel (default: `webhook`)
- `VIDEO_ANOMALY_MIN_SEVERITY` — minimum anomaly severity (default: `medium`)

### Register custom triggers

```bash
# List triggers (built-in + custom)
curl http://localhost:8000/v1/workflows/triggers \
  -H "Authorization: Bearer $CEREBRUM_API_KEY"

# Register a custom trigger
curl -X POST http://localhost:8000/v1/workflows/triggers \
  -H "Authorization: Bearer $CEREBRUM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "video.anomaly",
    "min_severity": "high",
    "description": "Critical anomalies → video_anomaly_trigger",
    "steps": [
      {
        "block_id": "video_anomaly_trigger",
        "params": {"action": "evaluate", "channel": "webhook"},
        "input_mapping": {
          "metadata": "metadata",
          "channel": "notify_channel",
          "url": "notify_to"
        }
      }
    ]
  }'
```

### Manual chaining (still supported)

The `video_anomaly_trigger` block remains available for explicit `/execute` or
orchestrator chains:

```json
{
  "workflow_id": "video-anomaly-alert",
  "steps": [
    {
      "block": "video_metadata_ingest",
      "params": { "action": "ingest" },
      "input": {
        "camera_id": "lobby-1",
        "source_id": "jetson-edge-01",
        "zones": [
          { "zone_id": "lobby", "count": 42, "capacity": 50 }
        ],
        "anomalies": [
          {
            "anomaly_type": "overcrowding",
            "severity": "high",
            "zone_id": "lobby",
            "confidence": 0.92
          }
        ]
      }
    },
    {
      "block": "video_anomaly_trigger",
      "params": {
        "action": "evaluate",
        "channel": "webhook",
        "send_notification": "true"
      },
      "input": {
        "url": "https://hooks.example.com/video-alerts",
        "message": "Lobby overcrowding detected"
      }
    }
  ]
}
```

## REST shortcut (auto-chains via reactive engine)

```bash
curl -X POST http://localhost:8000/v1/video/ingest \
  -H "Authorization: Bearer $CEREBRUM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "camera_id": "lobby-1",
    "anomalies": [{"anomaly_type": "intrusion", "severity": "critical"}],
    "auto_trigger": true,
    "notify_channel": "webhook",
    "notify_to": "https://hooks.example.com/alerts"
  }'
```

Response includes `workflow` with step results when triggers fire.

Set `"auto_trigger": false` to ingest only (no reactive chain).

## Medical EHR (FHIR) fetch

```bash
curl -X POST http://localhost:8000/v1/connectors/medical/ehr \
  -H "Authorization: Bearer $CEREBRUM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"resource": "Patient", "resource_id": "example"}'
```

Environment:

- `FHIR_BASE_URL` — FHIR server base (e.g. `https://fhir.example.com/r4`)
- `FHIR_ACCESS_TOKEN` — Bearer token (preferred)
- `FHIR_CLIENT_ID` / `FHIR_CLIENT_SECRET` — optional client credentials

## Domain connector kits

| Kit          | Connectors                                      | Key env vars                          |
|--------------|-------------------------------------------------|---------------------------------------|
| law          | `pacer_connector`, `caselaw_connector`          | `PACER_*`, `CASELAW_*`                |
| finance      | `market_data_connector`, `sec_edgar_connector`  | `MARKET_DATA_*`, `SEC_USER_AGENT`     |
| maintenance  | `cmms_connector`, `iot_sensor_connector`        | `CMMS_*`, `IOT_*`                     |
| hotel        | `opera_connector`, `hotel_trigger`              | Opera PMS credentials (stub)          |
| medical      | `medical_ehr_connector`, `clinical_trigger`     | `FHIR_*`                              |

Install skeleton kits from the Block Store (`POST /store/containers/{kit_id}/install`).

## Storage

Set `DATABASE_URL` to a PostgreSQL/Timescale connection string for durable video event storage. Without it, an in-memory store is used (tests and local dev).
