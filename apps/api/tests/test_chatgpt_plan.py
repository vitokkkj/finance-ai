from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app import chatgpt_plan
from app.chatgpt_plan import REQUIRED_SCOPES, ChatGPTCredentialStore, ChatGPTPlanError


def _credentials(store: ChatGPTCredentialStore) -> dict[str, object]:
    return {
        "client_id": "oaiapp_test_client",
        "ext_agent_host_id": store.ensure_host_id(),
        "access_token": "access-token-test-value",
        "refresh_token": "refresh-token-test-value",
        "id_token": "id-token-test-value",
        "oauth_nonce": "nonce-test-value",
        "expires_in": 3600,
        "scope": " ".join(sorted(REQUIRED_SCOPES | {"email", "openid", "profile"})),
    }


@pytest.mark.skipif(os.name == "nt", reason="Permissões POSIX são verificadas no host Linux.")
def test_host_id_is_stable_and_opaque(tmp_path: Path) -> None:
    store = ChatGPTCredentialStore(tmp_path)

    first = store.ensure_host_id()
    second = store.ensure_host_id()

    assert first == second
    assert first.startswith("urn:uuid:")
    assert "@" not in first
    assert os.stat(store.host_id_path).st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name == "nt", reason="Permissões POSIX são verificadas no host Linux.")
def test_import_validates_scope_and_stores_tokens_with_private_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ChatGPTCredentialStore(tmp_path)
    monkeypatch.setattr(chatgpt_plan, "_validate_id_token", lambda *_: "subject-test")

    store.import_credentials(_credentials(store))

    saved = json.loads(store.credentials_path.read_text(encoding="utf-8"))
    assert store.is_connected()
    assert saved["subject"] == "subject-test"
    assert saved["client_id"] == "oaiapp_test_client"
    assert saved["ext_agent_host_id"] == store.ensure_host_id()
    assert saved["access_token"] == "access-token-test-value"
    assert saved["refresh_token"] == "refresh-token-test-value"
    assert os.stat(store.credentials_path).st_mode & 0o777 == 0o600


def test_import_rejects_missing_plan_scope_without_writing_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ChatGPTCredentialStore(tmp_path)
    monkeypatch.setattr(chatgpt_plan, "_validate_id_token", lambda *_: "subject-test")
    payload = _credentials(store)
    payload["scope"] = "openid profile email"

    with pytest.raises(ChatGPTPlanError) as caught:
        store.import_credentials(payload)

    assert caught.value.code == "plan_scope_missing"
    assert not store.credentials_path.exists()


def test_import_rejects_other_vm_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ChatGPTCredentialStore(tmp_path)
    monkeypatch.setattr(chatgpt_plan, "_validate_id_token", lambda *_: "subject-test")
    payload = _credentials(store)
    payload["ext_agent_host_id"] = "urn:uuid:00000000-0000-0000-0000-000000000000"

    with pytest.raises(ChatGPTPlanError) as caught:
        store.import_credentials(payload)

    assert caught.value.code == "host_mismatch"
    assert not store.credentials_path.exists()


def test_reauthorization_cannot_replace_saved_account_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ChatGPTCredentialStore(tmp_path)
    monkeypatch.setattr(chatgpt_plan, "_validate_id_token", lambda *_: "first-subject")
    first = _credentials(store)
    store.import_credentials(first)
    original = store.credentials_path.read_text(encoding="utf-8")

    monkeypatch.setattr(chatgpt_plan, "_validate_id_token", lambda *_: "different-subject")
    replacement = _credentials(store)
    replacement["access_token"] = "replacement-token"

    with pytest.raises(ChatGPTPlanError) as caught:
        store.import_credentials(replacement)

    assert caught.value.code == "account_mismatch"
    assert store.credentials_path.read_text(encoding="utf-8") == original


def test_missing_connection_fails_closed_without_paid_provider(tmp_path: Path) -> None:
    store = ChatGPTCredentialStore(tmp_path)

    async def get_token() -> str:
        return await store.get_access_token()

    import asyncio

    with pytest.raises(ChatGPTPlanError) as caught:
        asyncio.run(get_token())

    assert caught.value.code == "connection_required"
    assert "API paga" in str(caught.value)
