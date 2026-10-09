from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import cast

AUTH = "https://auth.openai.com/api/accounts/authorize"
TOKEN = "https://auth.openai.com/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
REDIRECT = "http://127.0.0.1:1455/auth/callback"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"


class CallbackServer(HTTPServer):
    expected_state: str
    result: dict[str, str] | None = None
    error: str | None = None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        server = cast(CallbackServer, self.server)
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if parsed.path != "/auth/callback" or params.get("state", [""])[0] != server.expected_state:
            server.error = "A confirmação de segurança do login não corresponde."
            self._respond(400, "Não foi possível validar este retorno.")
            return
        error = params.get("error", [""])[0]
        if error:
            server.error = "Autorização cancelada." if error == "access_denied" else "Login não concluído."
            self._respond(400, "Autorização não concluída. Feche esta janela.")
            return
        code = params.get("code", [""])[0]
        if not code:
            server.error = "O retorno do login não continha o código de autorização."
            self._respond(400, "Resposta de autorização inválida.")
            return
        server.result = {
            "code": code,
            "client_id": params.get("client_id", [""])[0],
        }
        self._respond(200, "Conexão autorizada. Volte ao terminal para concluir.")

    def _respond(self, status: int, message: str) -> None:
        body = (
            "<!doctype html><html lang='pt-BR'><meta charset='utf-8'>"
            "<title>Conexão da SophIA</title><body style='font:16px system-ui'>"
            f"<h1>SophIA</h1><p>{message}</p></body></html>"
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        # The callback query contains a one-time authorization code.
        _ = format, args


def find_ssh() -> str:
    found = shutil.which("ssh")
    if found:
        return found
    local_app_data = os.environ.get("LOCALAPPDATA")
    candidate = Path(local_app_data or "") / "Programs/Git/usr/bin/ssh.exe"
    if candidate.is_file():
        return str(candidate)
    raise RuntimeError("Não encontrei o OpenSSH. Instale o cliente OpenSSH ou o Git for Windows.")


def remote_command(project_dir: str, subcommand: str) -> str:
    return (
        f"cd {shlex.quote(project_dir)} && "
        f"docker compose exec -T api python -m app.chatgpt_plan {subcommand}"
    )


def ssh_args(ssh: str, target: str, identity: str | None, command: str) -> list[str]:
    args = [
        ssh, "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", "ConnectTimeout=8",
    ]
    if identity:
        args += ["-i", identity]
    return args + [target, command]


def call_remote(
    ssh: str,
    target: str,
    identity: str | None,
    project_dir: str,
    command: str,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ssh_args(ssh, target, identity, remote_command(project_dir, command)),
        input=input_text, text=True, capture_output=True, check=False,
    )


def pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def exchange_code(client_id: str, code: str, verifier: str) -> dict[str, object]:
    form = urllib.parse.urlencode({
        "grant_type": "authorization_code", "client_id": client_id, "code": code,
        "code_verifier": verifier, "redirect_uri": REDIRECT, "resource": RESOURCE,
    }).encode("ascii")
    request = urllib.request.Request(
        TOKEN, data=form, headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value: object = json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"A OpenAI recusou a autorização (HTTP {error.code}). Inicie o login novamente."
        ) from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("Não foi possível conectar à OpenAI para concluir o login.") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError("A resposta de autorização da OpenAI estava inválida.") from None
    if not isinstance(value, dict):
        raise RuntimeError("A resposta de autorização da OpenAI estava inválida.")
    return cast(dict[str, object], value)


def connect(args: argparse.Namespace) -> int:
    ssh = find_ssh()
    info_result = call_remote(ssh, args.ssh_target, args.identity, args.project_dir, "host-info")
    if info_result.returncode:
        raise RuntimeError(
            "Não consegui consultar a VM via SSH. Confira o destino, a chave e o caminho do Compose."
        )
    try:
        info: object = json.loads(info_result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("A VM retornou dados inválidos de configuração.") from None
    if not isinstance(info, dict):
        raise RuntimeError("A VM retornou dados inválidos de configuração.")
    host = cast(dict[str, object], info)
    host_id, previous_client_id = host.get("ext_agent_host_id"), host.get("client_id")
    if not isinstance(host_id, str):
        raise RuntimeError("A VM não retornou um identificador de host válido.")

    first = not isinstance(previous_client_id, str) or not previous_client_id
    client_id = "dynamic_agent_client" if first else previous_client_id
    verifier, challenge = pkce_pair()
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    params = {
        "client_id": client_id,
        "ext_agent_host_id": host_id,
        "response_type": "code",
        "redirect_uri": REDIRECT,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    if first:
        params["agent_name_hint"] = "SophIA"
    auth_url = f"{AUTH}?{urllib.parse.urlencode(params)}"

    server = CallbackServer(("127.0.0.1", 1455), Handler)
    server.expected_state = state
    server.timeout = 1
    print("Abrindo o login do ChatGPT. Autorize o uso do plano pela SophIA.")
    try:
        webbrowser.open(auth_url)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline and server.result is None:
            if server.error:
                raise RuntimeError(server.error)
            server.handle_request()
    finally:
        server.server_close()
    if server.error:
        raise RuntimeError(server.error)
    if server.result is None:
        raise RuntimeError("O tempo para concluir o login expirou.")

    returned_client_id = server.result["client_id"]
    if first and not returned_client_id:
        raise RuntimeError("O registro da SophIA não foi concluído pelo ChatGPT.")
    issued_id = returned_client_id or client_id
    if not first and returned_client_id and returned_client_id != client_id:
        raise RuntimeError("O ChatGPT retornou outro registro para esta conexão.")

    response = exchange_code(issued_id, server.result["code"], verifier)
    scope = response.get("scope")
    if not isinstance(scope, str) or "chatgpt.tokens.use.direct" not in scope.split():
        raise RuntimeError(
            "A autorização não incluiu o uso do plano ChatGPT. Nenhum token foi transferido."
        )
    for name in ("access_token", "refresh_token", "id_token"):
        if not isinstance(response.get(name), str) or not response[name]:
            raise RuntimeError("A OpenAI não retornou uma sessão completa para a SophIA.")
    expires_in = response.get("expires_in")
    if not isinstance(expires_in, int) or isinstance(expires_in, bool):
        raise RuntimeError("A OpenAI não retornou o prazo da sessão.")

    credentials = {
        "client_id": issued_id,
        "ext_agent_host_id": host_id,
        "access_token": response["access_token"],
        "refresh_token": response["refresh_token"],
        "id_token": response["id_token"],
        "oauth_nonce": nonce,
        "expires_in": expires_in,
        "scope": scope,
    }
    transferred = call_remote(
        ssh,
        args.ssh_target,
        args.identity,
        args.project_dir,
        "import-credentials",
        json.dumps(credentials, separators=(",", ":")),
    )
    if transferred.returncode:
        raise RuntimeError(
            transferred.stderr.strip()
            or "A VM não validou a conexão. Os tokens não foram exibidos."
        )
    print(transferred.stdout.strip() or "Conexão transferida com segurança para a VM.")
    models = call_remote(ssh, args.ssh_target, args.identity, args.project_dir, "models")
    if models.returncode == 0 and models.stdout.strip():
        print("Modelos disponíveis nesta conta:")
        print(models.stdout.strip())
    else:
        print("A conexão foi salva; não foi possível listar os modelos agora.")
    print("A VM manterá e renovará os tokens. Este computador pode ser desligado.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Usa a franquia ChatGPT na SophIA hospedada em uma VM."
    )
    parser.add_argument("--ssh-target", required=True, help="Ex.: usuario@IP-TAILSCALE-DA-VM")
    parser.add_argument("--project-dir", required=True, help="Diretório do compose na VM")
    parser.add_argument("--identity", help="Caminho da chave privada SSH")
    try:
        return connect(parser.parse_args())
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
