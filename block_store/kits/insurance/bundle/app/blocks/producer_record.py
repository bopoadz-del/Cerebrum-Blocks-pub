"""Producer record Store block for insurance distribution."""

from datetime import date
from typing import Any, Dict, List, Optional, TypedDict

from app.core.universal_base import UniversalBlock


class ProducerLicense(TypedDict):
    """Producer license details."""

    jurisdiction: str
    number: str
    status: str
    expires: Optional[str]


class ProducerRecord(TypedDict):
    """Insurance producer record."""

    producer_id: str
    name: str
    licenses: List[ProducerLicense]
    agency_id: str
    status: str
    appointed_carriers: List[str]


class ProducerRecordResult(TypedDict, total=False):
    """Typed result envelope returned by process operations."""

    status: str
    operation: str
    producer: ProducerRecord
    producers: List[ProducerRecord]
    producer_id: str
    agency_id: str
    license_status: str
    licenses: List[Dict[str, Any]]
    count: int
    errors: List[str]
    error: str
    message: str


class ProducerRecordBlock(UniversalBlock):
    """In-memory producer Store block for F1 distribution workflows."""

    name = "producer_record"
    version = "1.0.0"
    description = "Insurance producer record Store block for licenses, agency assignment, status, and carrier appointments"
    layer = 3
    tags = ["domain", "insurance", "producer", "licensing", "store"]
    requires: List[str] = []

    default_config = {
        "active_producer_statuses": ["active", "appointed"],
        "active_license_statuses": ["active", "valid"],
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"operation": "upsert", "producer": {"producer_id": "prod-1", "name": "Jane Producer", "agency_id": "agency-1", "status": "active", "licenses": []}}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "producer", "type": "json", "label": "Producer"},
                {"name": "producers", "type": "json", "label": "Producers"},
                {"name": "license_status", "type": "text", "label": "License Status"},
            ],
        },
        "quick_actions": [
            {"icon": "G", "label": "Get Producer", "prompt": "Get a producer record"},
            {"icon": "L", "label": "License Status", "prompt": "Check producer license status"},
        ],
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        self._producers: Dict[str, ProducerRecord] = {}

    async def process(self, input_data: Any, params: Dict = None) -> ProducerRecordResult:
        """Route producer Store operations."""

        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        operation = (
            params.get("operation")
            or params.get("action")
            or data.get("operation")
            or data.get("action")
            or "get"
        )

        if operation == "upsert":
            return self._upsert(data)
        if operation == "get":
            return self._get(data, params)
        if operation == "list_by_agency":
            return self._list_by_agency(data, params)
        if operation == "license_status":
            return self._license_status(data, params)

        return {
            "status": "error",
            "operation": str(operation),
            "error": f"Unknown operation: {operation}",
        }

    def _upsert(self, data: Dict[str, Any]) -> ProducerRecordResult:
        raw_producer = data.get("producer") if isinstance(data.get("producer"), dict) else data
        producer = self._normalize_producer(raw_producer)
        errors = self._validate_producer(producer)
        if errors:
            return {
                "status": "error",
                "operation": "upsert",
                "producer": producer,
                "errors": errors,
            }

        self._producers[producer["producer_id"]] = producer
        return {
            "status": "success",
            "operation": "upsert",
            "producer": self._copy_producer(producer),
            "message": f"Producer '{producer['producer_id']}' upserted",
        }

    def _get(self, data: Dict[str, Any], params: Dict[str, Any]) -> ProducerRecordResult:
        producer_id = data.get("producer_id") or data.get("id") or params.get("producer_id") or params.get("id")
        if not producer_id:
            return self._error("get", "producer_id is required")

        producer = self._producers.get(str(producer_id))
        if not producer:
            return self._error("get", f"producer_id '{producer_id}' not found")

        return {
            "status": "success",
            "operation": "get",
            "producer": self._copy_producer(producer),
        }

    def _list_by_agency(self, data: Dict[str, Any], params: Dict[str, Any]) -> ProducerRecordResult:
        agency_id = data.get("agency_id") or params.get("agency_id")
        if not agency_id:
            return self._error("list_by_agency", "agency_id is required")

        include_inactive = bool(data.get("include_inactive", params.get("include_inactive", True)))
        active_statuses = set(self.config.get("active_producer_statuses", []))
        producers = [
            self._copy_producer(producer)
            for producer in self._producers.values()
            if producer["agency_id"] == str(agency_id)
            and (include_inactive or producer["status"] in active_statuses)
        ]
        producers.sort(key=lambda producer: producer["producer_id"])

        return {
            "status": "success",
            "operation": "list_by_agency",
            "agency_id": str(agency_id),
            "producers": producers,
            "count": len(producers),
        }

    def _license_status(self, data: Dict[str, Any], params: Dict[str, Any]) -> ProducerRecordResult:
        producer_id = data.get("producer_id") or data.get("id") or params.get("producer_id") or params.get("id")
        if not producer_id:
            return self._error("license_status", "producer_id is required")

        producer = self._producers.get(str(producer_id))
        if not producer:
            return self._error("license_status", f"producer_id '{producer_id}' not found")

        as_of_value = data.get("as_of") or params.get("as_of")
        as_of = self._parse_date(as_of_value) if as_of_value else date.today()
        if as_of is None:
            return self._error("license_status", f"as_of '{as_of_value}' is not a valid ISO date")

        active_license_statuses = set(self.config.get("active_license_statuses", []))
        license_results: List[Dict[str, Any]] = []
        active_count = 0
        expired_count = 0

        for license_record in producer["licenses"]:
            expires = self._parse_date(license_record.get("expires"))
            is_expired = bool(expires and expires < as_of)
            is_active = license_record["status"] in active_license_statuses and not is_expired
            if is_active:
                active_count += 1
            if is_expired:
                expired_count += 1

            license_results.append(
                {
                    **self._copy_license(license_record),
                    "is_active": is_active,
                    "is_expired": is_expired,
                }
            )

        producer_active = producer["status"] in set(self.config.get("active_producer_statuses", []))
        if not producer["licenses"]:
            aggregate = "missing"
        elif active_count > 0 and producer_active:
            aggregate = "active"
        elif expired_count == len(producer["licenses"]):
            aggregate = "expired"
        else:
            aggregate = "inactive"

        return {
            "status": "success",
            "operation": "license_status",
            "producer_id": producer["producer_id"],
            "license_status": aggregate,
            "licenses": license_results,
            "count": len(license_results),
        }

    def _normalize_producer(self, raw_producer: Dict[str, Any]) -> ProducerRecord:
        raw_licenses = raw_producer.get("licenses", [])
        if not isinstance(raw_licenses, list):
            raw_licenses = []

        raw_carriers = raw_producer.get("appointed_carriers", [])
        if not isinstance(raw_carriers, list):
            raw_carriers = [raw_carriers]

        return {
            "producer_id": str(raw_producer.get("producer_id", raw_producer.get("id", ""))).strip(),
            "name": str(raw_producer.get("name", "")).strip(),
            "licenses": [self._normalize_license(item) for item in raw_licenses if isinstance(item, dict)],
            "agency_id": str(raw_producer.get("agency_id", "")).strip(),
            "status": str(raw_producer.get("status", "active")).strip().lower(),
            "appointed_carriers": [str(carrier) for carrier in raw_carriers if str(carrier)],
        }

    def _normalize_license(self, raw_license: Dict[str, Any]) -> ProducerLicense:
        return {
            "jurisdiction": str(raw_license.get("jurisdiction", "")).strip().upper(),
            "number": str(raw_license.get("number", "")).strip(),
            "status": str(raw_license.get("status", "active")).strip().lower(),
            "expires": self._normalize_date_value(raw_license.get("expires")),
        }

    def _validate_producer(self, producer: ProducerRecord) -> List[str]:
        errors: List[str] = []
        if not producer.get("producer_id"):
            errors.append("producer_id is required")
        if not producer.get("name"):
            errors.append("name is required")
        if not producer.get("agency_id"):
            errors.append("agency_id is required")
        if not producer.get("status"):
            errors.append("status is required")

        for index, license_record in enumerate(producer.get("licenses", [])):
            prefix = f"licenses[{index}]"
            if not license_record.get("jurisdiction"):
                errors.append(f"{prefix}.jurisdiction is required")
            if not license_record.get("number"):
                errors.append(f"{prefix}.number is required")
            if not license_record.get("status"):
                errors.append(f"{prefix}.status is required")
            expires = license_record.get("expires")
            if expires and self._parse_date(expires) is None:
                errors.append(f"{prefix}.expires must be an ISO date")

        return errors

    def _copy_producer(self, producer: ProducerRecord) -> ProducerRecord:
        return {
            "producer_id": producer["producer_id"],
            "name": producer["name"],
            "licenses": [self._copy_license(license_record) for license_record in producer["licenses"]],
            "agency_id": producer["agency_id"],
            "status": producer["status"],
            "appointed_carriers": list(producer.get("appointed_carriers", [])),
        }

    def _copy_license(self, license_record: ProducerLicense) -> ProducerLicense:
        return {
            "jurisdiction": license_record["jurisdiction"],
            "number": license_record["number"],
            "status": license_record["status"],
            "expires": license_record.get("expires"),
        }

    def _normalize_date_value(self, value: Any) -> Optional[str]:
        if value in ("", None):
            return None
        return str(value)

    def _parse_date(self, value: Any) -> Optional[date]:
        if value in ("", None):
            return None
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return None

    def _error(self, operation: str, message: str) -> ProducerRecordResult:
        return {
            "status": "error",
            "operation": operation,
            "error": message,
            "errors": [message],
        }
