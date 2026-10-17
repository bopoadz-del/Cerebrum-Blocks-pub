"""Kit copy of medical EHR connector — installed to app/blocks on publish.

At dev time, delegates to the platform block in ``app.blocks.medical_ehr_connector``.
"""

from app.blocks.medical_ehr_connector import MedicalEHRConnectorBlock

__all__ = ["MedicalEHRConnectorBlock"]
