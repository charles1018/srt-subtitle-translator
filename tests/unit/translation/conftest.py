"""Translation module test fixtures."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_cache_manager():
    """Provide a mock CacheManager."""
    with patch("srt_translator.translation.client.CacheManager") as mock:
        instance = MagicMock()
        instance.get_cached_translation.return_value = None
        instance.store_translation.return_value = None
        mock.return_value = instance
        yield instance


@pytest.fixture
def mock_prompt_manager():
    """Provide a mock PromptManager."""
    with patch("srt_translator.translation.client.PromptManager") as mock:
        instance = MagicMock()
        instance.get_optimized_message.return_value = [
            {"role": "system", "content": "You are a translator."},
            {"role": "user", "content": "Translate: Hello"},
        ]
        mock.return_value = instance
        yield instance


@pytest.fixture
def mock_aiohttp_session():
    """Provide a mock aiohttp ClientSession."""
    session = AsyncMock()
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"response": "translated text"})
    response.raise_for_status = MagicMock()

    context_manager = AsyncMock()
    context_manager.__aenter__.return_value = response
    context_manager.__aexit__.return_value = None

    session.post.return_value = context_manager
    session.get.return_value = context_manager
    session.close = AsyncMock()

    return session


@pytest.fixture
def sample_messages():
    """Provide sample messages for translation."""
    return [
        {"role": "system", "content": "You are a translator."},
        {"role": "user", "content": "Translate this: Hello, world!"},
    ]
