"""Android Drive Block — Android storage access.

CAPABILITY GAP (survey wave-2 close-out): the block is an honest stub.
A real implementation needs net-new ADB (or a device REST bridge)
integration — no donor exists in the surveyed repos. Until then every
operation refuses by name and returns no device data. Classified:
store_upgrade / net-new-capability.
"""

from typing import Any, Dict
from app.core.universal_base import UniversalBlock


class AndroidDriveBlock(UniversalBlock):
    """Android device storage operations"""
    
    name = "android_drive"
    version = "1.0"
    description = (
        "Android device storage access — HONEST STUB: not implemented, "
        "refuses by name; needs net-new ADB/bridge integration (no donor)"
    )
    layer = 4
    tags = ["integration", "storage", "mobile"]
    requires = []
    
    ui_schema = {
        "input": {
            "type": "file",
            "accept": ["*/*"],
            "placeholder": "Access Android device storage...",
            "multiline": False
        },
        "output": {
            "type": "list",
            "fields": [
                {"name": "files", "type": "array", "label": "Files"}
            ]
        },
        "quick_actions": [
            {"icon": "📱", "label": "Android Files", "prompt": "List Android device files"}
        ]
    }
    
    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Android storage access is not implemented — say so, honestly."""
        params = params or {}
        operation = params.get("operation", "list")

        return {
            "status": "error",
            "error": "not_implemented",
            "operation": operation,
            "detail": (
                "android_drive is a stub: no ADB or REST bridge is wired. "
                "It returns no device data. Do not build on this block until "
                "an integration exists."
            ),
        }
