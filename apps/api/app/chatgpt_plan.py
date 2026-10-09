from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import httpx
import jwt

AUTHORIZATION_SCOPES = frozenset(
    {
        "chatgpt.tokens.use.direct",
        "offline_access",
        "openid",
        "profile",
        "email",
        "resource.invoke",
    }
)
REQUIRED_SCOPES = frozenset(
    {"chatgpt.tokens.use.direct", "offline_access", "resource.invoke"}
)
TOKEN_ENDPOINT = "https://auth.openai.com/api/accounts/oauth/token"
JWKS_URL = "https://auth.openai.com/.well-known/jwks.json"
ISSUER = "https://auth.openai.com"
RESPONSES_RESOURCE = "https://api.openai.com/v1"
MODELS_URL = "https://api.openai.com/v1/models"


class ChatGPTPlanError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ChatGPTCredentialStore:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.credentials_path = self.directory / "credentials.json"
        self.host_id_path = self.directory / "host-id"
        self._refresh_lock = asyncio.Lock()

    def ensure_host_id(self) -> str:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            host_id = self.host_id_path.read_text(encoding="utf-8").strip()
            if host_id.startswith("urn:uuid:"):
                uuid.UUID(host_id.removeprefix("urn:uuid:"))
                return host_id
        except (OSError, ValueError):
            pass
        host_id = f"urn:uuid:{uuid.uuid4()}"
        _atomic_write_text(self.host_id_path, host_id + "\n")
        return host_id

    def host_info(self) -> dict[str, str | None]:
        credentials = self._read_optional()
        client_id = credentials.get("client_id") if credentials else None
        return {
            "ext_agent_host_id": self.ensure_host_id(),
            "client_id": client_id if isinstance(client_id, str) else None,
        }

    def is_connected(self) -> bool:
        credentials = self._read_optional()
        if credentials is None:
            return False
        scopes = credentials.get("scopes")
        return (
            isinstance(credentials.get("client_id"), str)
            and bool(credentials.get("access_token"))
            and bool(credentials.get("refresh_token"))
            and isinstance(scopes, list)
            and REQUIRED_SCOPES.issubset(
                {scope for scope in scopes if isinstance(scope, str)}
            )
        )

    def _read_optional(self) -> dict[str, object] | None:
        try:
            contents = self.credentials_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as error:
            raise ChatGPTPlanError(
                "connection_storage_error",
                "Não foi possível acessar com segurança a conexão com o ChatGPT.",
            ) from error
        try:
            value: object = json.loads(contents)
        except json.JSONDecodeError as error:
            raise ChatGPTPlanError(
                "invalid_credentials",
                "A conexão com o ChatGPT está inválida. Reconecte sua conta.",
            ) from error
        if not isinstance(value, dict):
            raise ChatGPTPlanError(
                "invalid_credentials",
                "A conexão com o ChatGPT está inválida. Reconecte sua conta.",
            )
        return cast(dict[str, object], value)

    def import_credentials(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ChatGPTPlanError(
                "invalid_credentials", "Os dados recebidos para conexão são inválidos."
            )
        data = cast(dict[str, object], payload)
        client_id = _required_string(data, "client_id")
        if client_id == "dynamic_agent_client":
            raise ChatGPTPlanError(
                "invalid_credentials", "O registro da conexão com o ChatGPT não foi concluído."
            )
        host_id = self.ensure_host_id()
        if data.get("ext_agent_host_id") != host_id:
            raise ChatGPTPlanError(
                "host_mismatch",
                "A autorização foi iniciada para outra máquina. Inicie a conexão novamente.",
            )
        access_token = _required_string(data, "access_token")
        refresh_token = _required_string(data, "refresh_token")
        id_token = _required_string(data, "id_token")
        nonce = _required_string(data, "oauth_nonce")
        expires_in = data.get("expires_in")
        if not isinstance(expires_in, int) or isinstance(expires_in, bool) or expires_in <= 0:
            raise ChatGPTPlanError(
                "invalid_credentials", "A resposta de autorização não tem prazo de validade."
            )
        raw_scope = data.get("scope")
        if not isinstance(raw_scope, str):
            raise ChatGPTPlanError(
                "plan_scope_missing",
                "A conta não autorizou o uso do plano ChatGPT pela SophIA.",
            )
        scopes = sorted(set(raw_scope.split()))
        if not REQUIRED_SCOPES.issubset(scopes):
            raise ChatGPTPlanError(
                "plan_scope_missing",
                "A autorização não incluiu o uso do plano ChatGPT. "
                "Conecte novamente e aceite essa permissão.",
            )

        subject = _validate_id_token(id_token, client_id, nonce)
        previous = self._read_optional()
        if previous is not None:
            previous_client_id = previous.get("client_id")
            previous_subject = previous.get("subject")
            if previous_client_id != client_id:
                raise ChatGPTPlanError(
                    "client_mismatch",
                    "A nova autorização não corresponde ao registro já salvo nesta VM.",
                )
            if previous_subject != subject:
                raise ChatGPTPlanError(
                    "account_mismatch",
                    "A autorização retornou outra conta ChatGPT. "
                    "A conexão anterior foi preservada.",
                )

        saved_at = datetime.now(UTC)
        record: dict[str, object] = {
            "issuer": ISSUER,
            "subject": subject,
            "client_id": client_id,
            "ext_agent_host_id": host_id,
            "id_token": id_token,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_at": (saved_at + timedelta(seconds=expires_in)).isoformat(),
            "scopes": scopes,
            "saved_at": saved_at.isoformat(),
        }
        _atomic_write_json(self.credentials_path, record)

    async def get_access_token(self) -> str:
        async with self._refresh_lock:
            credentials = self._read_optional()
            if credentials is None or not self.is_connected():
                raise ChatGPTPlanError(
                    "connection_required",
                    "Conecte o plano ChatGPT da sua conta para usar o assistente. "
                    "A SophIA não usará uma API paga.",
                )
            expires_at = credentials.get("expires_at")
            try:
                expires = datetime.fromisoformat(cast(str, expires_at))
            except (TypeError, ValueError):
                expires = datetime.min.replace(tzinfo=UTC)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires > datetime.now(UTC) + timedelta(minutes=5):
                return cast(str, credentials["access_token"])
            refreshed = await self._refresh(credentials)
            return cast(str, refreshed["access_token"])

    async def _refresh(self, credentials: dict[str, object]) -> dict[str, object]:
        client_id = credentials.get("client_id")
        refresh_token = credentials.get("refresh_token")
        if not isinstance(client_id, str) or not isinstance(refresh_token, str):
            raise ChatGPTPlanError(
                "reconnect_required",
                "A conexão com o ChatGPT expirou. Conecte sua conta novamente.",
            )
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
                response = await client.post(
                    TOKEN_ENDPOINT,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": client_id,
                        "refresh_token": refresh_token,
                        "resource": RESPONSES_RESOURCE,
                    },
                )
        except httpx.TimeoutException as error:
            raise ChatGPTPlanError(
                "timeout", "A conexão com o ChatGPT demorou mais que o esperado."
            ) from error
        except httpx.RequestError as error:
            raise ChatGPTPlanError(
                "network_error", "Não foi possível conectar ao serviço do ChatGPT."
            ) from error

        if response.is_error:
            error_code = _oauth_error_code(response)
            if error_code in {
                "invalid_grant",
                "invalid_refresh_token",
                "token_expired",
                "refresh_token_expired",
                "refresh_token_invalidated",
                "refresh_token_reused",
            }:
                raise ChatGPTPlanError(
                    "reconnect_required",
                    "A conexão com o ChatGPT expirou ou foi revogada. Conecte sua conta novamente.",
                )
            if error_code == "invalid_client":
                raise ChatGPTPlanError(
                    "invalid_client",
                    "O registro da SophIA no ChatGPT foi recusado. Revise a configuração.",
                )
            raise ChatGPTPlanError(
                "provider_unavailable",
                "Não foi possível renovar a conexão com o ChatGPT. Tente novamente mais tarde.",
            )
        try:
            value: object = response.json()
        except ValueError as error:
            raise ChatGPTPlanError(
                "invalid_response", "O serviço do ChatGPT retornou uma resposta inválida."
            ) from error
        if not isinstance(value, dict):
            raise ChatGPTPlanError(
                "invalid_response", "O serviço do ChatGPT retornou uma resposta inválida."
            )
        refreshed = cast(dict[str, object], value)
        new_access_token = refreshed.get("access_token")
        expires_in = refreshed.get("expires_in")
        if (
            not isinstance(new_access_token, str)
            or not new_access_token
            or not isinstance(expires_in, int)
            or isinstance(expires_in, bool)
            or expires_in <= 0
        ):
            raise ChatGPTPlanError(
                "invalid_response", "O serviço do ChatGPT não retornou uma sessão válida."
            )

        scope_value = refreshed.get("scope")
        scopes = (
            sorted(set(scope_value.split()))
            if isinstance(scope_value, str)
            else credentials.get("scopes", [])
        )
        if not isinstance(scopes, list) or not REQUIRED_SCOPES.issubset(
            {scope for scope in scopes if isinstance(scope, str)}
        ):
            raise ChatGPTPlanError(
                "plan_scope_missing",
                "A conexão não tem permissão para usar o plano ChatGPT. "
                "Conecte sua conta novamente.",
            )

        updated = dict(credentials)
        updated["access_token"] = new_access_token
        replacement_refresh = refreshed.get("refresh_token")
        if isinstance(replacement_refresh, str) and replacement_refresh:
            updated["refresh_token"] = replacement_refresh
        replacement_id_token = refreshed.get("id_token")
        if isinstance(replacement_id_token, str) and replacement_id_token:
            updated["id_token"] = replacement_id_token
        updated["expires_at"] = (
            datetime.now(UTC) + timedelta(seconds=expires_in)
        ).isoformat()
        updated["scopes"] = scopes
        updated["saved_at"] = datetime.now(UTC).isoformat()
        _atomic_write_json(self.credentials_path, updated)
        return updated

    async def available_models(self) -> list[dict[str, str]]:
        access_token = await self.get_access_token()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
                response = await client.get(
                    MODELS_URL, headers={"Authorization": f"Bearer {access_token}"}
                )
                response.raise_for_status()
                value: object = response.json()
        except httpx.TimeoutException as error:
            raise ChatGPTPlanError(
                "timeout", "A consulta de modelos do ChatGPT demorou mais que o esperado."
            ) from error
        except httpx.HTTPStatusError as error:
            raise ChatGPTPlanError(
                "models_unavailable", "Não foi possível consultar os modelos desta conta."
            ) from error
        except httpx.RequestError as error:
            raise ChatGPTPlanError(
                "network_error", "Não foi possível conectar ao serviço do ChatGPT."
            ) from error
        except ValueError as error:
            raise ChatGPTPlanError(
                "invalid_response", "O serviço do ChatGPT retornou uma lista inválida."
            ) from error

        raw_models = value.get("models") if isinstance(value, dict) else None
        if not isinstance(raw_models, list):
            raise ChatGPTPlanError(
                "invalid_response", "O serviço do ChatGPT retornou uma lista inválida."
            )
        models: list[dict[str, str]] = []
        for item in raw_models:
            if not isinstance(item, dict) or item.get("visibility") != "list":
                continue
            slug = item.get("slug")
            display_name = item.get("display_name")
            if isinstance(slug, str) and isinstance(display_name, str):
                models.append({"slug": slug, "display_name": display_name})
        return models


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ChatGPTPlanError(
            "invalid_credentials", "Os dados recebidos para conexão são inválidos."
        )
    return value.strip()


def _validate_id_token(token: str, client_id: str, nonce: str) -> str:
    try:
        jwks = jwt.PyJWKClient(JWKS_URL, timeout=10)
        signing_key = jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=ISSUER,
            leeway=60,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
        )
    except (jwt.PyJWTError, OSError, ValueError) as error:
        raise ChatGPTPlanError(
            "invalid_identity",
            "Não foi possível validar a identidade recebida do ChatGPT.",
        ) from error
    if claims.get("nonce") != nonce:
        raise ChatGPTPlanError(
            "invalid_identity", "A confirmação de segurança do login não corresponde."
        )
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise ChatGPTPlanError(
            "invalid_identity", "O ChatGPT não retornou uma identidade válida."
        )
    return subject


def _oauth_error_code(response: httpx.Response) -> str:
    try:
        value: object = response.json()
    except ValueError:
        return ""
    if not isinstance(value, dict):
        return ""
    code = value.get("error")
    return code if isinstance(code, str) else ""


def _atomic_write_text(path: Path, contents: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".credential-",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            os.chmod(temporary_path, 0o600)
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _atomic_write_json(path: Path, data: dict[str, object]) -> None:
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def _main() -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Conexão da SophIA com o plano ChatGPT.")
    parser.add_argument("command", choices=("host-info", "import-credentials", "models", "status"))
    parser.add_argument(
        "--auth-dir",
        default=os.environ.get("CHATGPT_AUTH_DIR", "/home/app/.config/sophia"),
    )
    args = parser.parse_args()
    store = ChatGPTCredentialStore(args.auth_dir)

    if args.command == "host-info":
        print(json.dumps(store.host_info()))
        return 0
    if args.command == "import-credentials":
        try:
            payload: object = json.load(sys.stdin)
            store.import_credentials(payload)
        except ChatGPTPlanError as error:
            print(str(error), file=sys.stderr)
            return 2
        except (json.JSONDecodeError, OSError):
            print("Não foi possível importar a conexão com o ChatGPT.", file=sys.stderr)
            return 2
        print("Conexão do plano ChatGPT validada e protegida na VM.")
        return 0
    if args.command == "status":
        print("conectada" if store.is_connected() else "não conectada")
        return 0
    try:
        print(json.dumps(asyncio.run(store.available_models()), ensure_ascii=False, indent=2))
    except ChatGPTPlanError as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
