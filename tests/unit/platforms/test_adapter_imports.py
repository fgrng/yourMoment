"""Import-graph guard: the myMoment adapter knows neither ORM nor encryption."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_mymoment_adapter_imports_no_orm_or_encryption():
    probe = (
        "import sys; import src.platforms.mymoment.adapter; "
        "print(sorted(m for m in sys.modules "
        "if m.split('.')[0] == 'sqlalchemy' or m.startswith(('src.models', 'src.config.encryption'))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "[]"
