"""Worker test configuration.

Clears the Settings lru_cache before each test so that environment variable
overrides (e.g. LLM_PROVIDER=mock) are always picked up freshly.
"""

import pytest

from apps.api.app.core.config import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    """Ensure Settings is re-read from .env for every test."""
    get_settings.cache_clear()
