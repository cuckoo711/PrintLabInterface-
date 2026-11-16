from __future__ import annotations

import pytest

from printlab_interface.config import Settings


@pytest.fixture()
def settings(tmp_path):
    """Isolated settings: temp data dir, PrintLab absent, unreachable URL."""
    return Settings(
        data_dir=tmp_path / "data",
        printlab_root=None,
        printlab_url="http://127.0.0.1:9",  # nothing listens on the discard port
        http_timeout_s=0.5,
        extra_hosts=frozenset({"testserver"}),
    )
