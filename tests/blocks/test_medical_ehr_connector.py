"""Tests for medical EHR FHIR connector (mocked httpx)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.blocks.medical_ehr_connector import MedicalEHRConnectorBlock


PATIENT_BUNDLE = {
    "resourceType": "Bundle",
    "entry": [
        {
            "resource": {
                "resourceType": "Patient",
                "id": "pat-1",
                "name": [{"family": "Doe", "given": ["Jane"]}],
                "birthDate": "1990-01-01",
                "gender": "female",
            }
        }
    ],
}


@pytest.fixture
def ehr_block():
    block = MedicalEHRConnectorBlock(config={
        "fhir_base_url": "https://fhir.test/r4",
        "fhir_access_token": "test-token",
    })
    return block


@pytest.mark.asyncio
async def test_auth_with_token(ehr_block):
    auth = await ehr_block.authenticate()
    assert auth["authenticated"] is True
    assert auth["method"] == "bearer_token"


@pytest.mark.asyncio
async def test_auth_fails_without_config():
    block = MedicalEHRConnectorBlock(config={"fhir_base_url": "", "fhir_access_token": ""})
    auth = await block.authenticate()
    assert auth["authenticated"] is False


@pytest.mark.asyncio
async def test_fetch_patient_bundle(ehr_block):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = PATIENT_BUNDLE

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await ehr_block.process(
            {"resource": "Patient", "patient_id": "pat-1"},
            {"action": "fetch", "resource": "Patient"},
        )

    assert result["status"] == "success"
    event = result["event"]
    assert event["event_type"] == "fhir.patient.fetched"
    assert event["normalized_data"]["count"] == 1


@pytest.mark.asyncio
async def test_execute_envelope(ehr_block):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "resourceType": "Patient",
        "id": "solo",
        "name": [{"text": "Solo Patient"}],
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        envelope = await ehr_block.execute(
            {"resource": "Patient", "resource_id": "solo"},
            {"action": "fetch", "resource": "Patient"},
        )

    assert envelope["block"] == "medical_ehr_connector"
    assert envelope["status"] == "success"
