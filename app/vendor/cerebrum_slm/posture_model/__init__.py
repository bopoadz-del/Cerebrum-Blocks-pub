"""Hook contract from <private-repo> ``docs/serve/FORK_INTEGRATION.md`` @ 4e167a7.

``sample_posture(user_text, fork_context=..., allowed_formula_ids=...)``
samples the pinned Tinker checkpoint. Retrieval stays on The Fork: this
module does not retrieve, and it refuses when ``fork_context`` is missing.
"""

from app.vendor.cerebrum_slm.posture_model.client import (
    CHECKPOINT_URI,
    ContextMissing,
    PostureSampleError,
    load_serve_config,
    sample_posture,
)

__all__ = [
    "CHECKPOINT_URI",
    "ContextMissing",
    "PostureSampleError",
    "load_serve_config",
    "sample_posture",
]
