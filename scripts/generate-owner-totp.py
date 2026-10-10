#!/usr/bin/env python3
"""Gera uma chave TOTP de proprietário sem gravá-la em arquivos."""

from __future__ import annotations

import base64
import secrets
from urllib.parse import quote, urlencode


def main() -> None:
    secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
    label = quote("SophIA: proprietário", safe="")
    parameters = urlencode(
        {
            "secret": secret,
            "issuer": "SophIA",
            "algorithm": "SHA1",
            "digits": "6",
            "period": "30",
        }
    )
    print("Adicione esta chave ao app autenticador usando a configuração manual:")
    print(secret)
    print("\nURI otpauth (mantenha privada):")
    print(f"otpauth://totp/{label}?{parameters}")
    print("\nGuarde a chave no .env da VM como OWNER_TOTP_SECRET; não a envie ao GitHub.")


if __name__ == "__main__":
    main()
