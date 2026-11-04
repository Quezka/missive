import os
import tempfile
from datetime import datetime

import pytest

# Tests must never touch the real settings of the installed app (QSettings().clear() would wipe them).
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="missive-tests-")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

from missive.bootstrap import build_services
from missive.infrastructure.demo_source import DemoSource
from missive.infrastructure.sqlite_store import SqliteStore

NOW = datetime(2026, 10, 26, 12, 0)


@pytest.fixture
def service():
    return build_services(demo=True, store=SqliteStore(":memory:"), source=DemoSource(NOW))
