"""The only place litellm is imported.

Two defaults of litellm are unacceptable for a service that must start offline and must
not send anything anywhere on its own:
  * it fetches a model price table from GitHub at import time (observed: an outbound
    connection through the local proxy), and
  * it can emit telemetry/callbacks if configured.
The environment switch must be set BEFORE the first import, so every other module imports
litellm through here.
"""
from __future__ import annotations

import os

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm  # noqa: E402

litellm.suppress_debug_info = True
litellm.telemetry = False
litellm.success_callback = []
litellm.failure_callback = []
litellm.drop_params = False  # unsupported parameters must fail loudly, not be silently dropped

__all__ = ["litellm"]
