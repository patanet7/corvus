"""Test inject() handles new backend keys (openai, ollama, kimi, openai_compat)."""

import os


def test_inject_openai_sets_env(monkeypatch):
    """OpenAI API key should be set as OPENAI_API_KEY env var."""
    from corvus.credential_store import CredentialStore

    store = CredentialStore.__new__(CredentialStore)
    store._path = None
    store._age_key_file = ""
    store._data = {"openai": {"api_key": "sk-test-openai-key"}}

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    store.inject()
    assert os.environ.get("OPENAI_API_KEY") == "sk-test-openai-key"


def test_inject_ollama_sets_env(monkeypatch):
    """Ollama base_url should be stored for model router to read."""
    from corvus.credential_store import CredentialStore

    store = CredentialStore.__new__(CredentialStore)
    store._path = None
    store._age_key_file = ""
    store._data = {"ollama": {"base_url": "http://localhost:11434"}}

    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    store.inject()
    assert os.environ.get("OLLAMA_BASE_URL") == "http://localhost:11434"


def test_inject_kimi_sets_env(monkeypatch):
    """Kimi API key should be set as KIMI_BOT_TOKEN env var."""
    from corvus.credential_store import CredentialStore

    store = CredentialStore.__new__(CredentialStore)
    store._path = None
    store._age_key_file = ""
    store._data = {"kimi": {"api_key": "kimi-test-key"}}

    monkeypatch.delenv("KIMI_BOT_TOKEN", raising=False)
    store.inject()
    assert os.environ.get("KIMI_BOT_TOKEN") == "kimi-test-key"


def test_inject_openai_compat_sets_env(monkeypatch):
    """OpenAI-compat base_url and api_key should set OPENAI_COMPAT_* env vars."""
    from corvus.credential_store import CredentialStore

    store = CredentialStore.__new__(CredentialStore)
    store._path = None
    store._age_key_file = ""
    store._data = {
        "openai_compat": {
            "base_url": "http://localhost:1234/v1",
            "api_key": "lm-studio-key",
        }
    }

    monkeypatch.delenv("OPENAI_COMPAT_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_COMPAT_API_KEY", raising=False)
    store.inject()
    assert os.environ.get("OPENAI_COMPAT_BASE_URL") == "http://localhost:1234/v1"
    assert os.environ.get("OPENAI_COMPAT_API_KEY") == "lm-studio-key"


def test_from_env_includes_new_backends(monkeypatch):
    """from_env() should pick up openai, ollama, kimi, openai_compat env vars."""
    from corvus.credential_store import CredentialStore

    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://gpu-host:11434")
    monkeypatch.setenv("KIMI_BOT_TOKEN", "kimi-from-env")
    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "http://local:1234/v1")
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "compat-key")

    store = CredentialStore.from_env()

    assert store.get("openai", "api_key") == "sk-from-env"
    assert store.get("ollama", "base_url") == "http://gpu-host:11434"
    assert store.get("kimi", "api_key") == "kimi-from-env"
    assert store.get("openai_compat", "base_url") == "http://local:1234/v1"
    assert store.get("openai_compat", "api_key") == "compat-key"
