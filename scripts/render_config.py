"""Render only explicitly selected prod environment values; never log secrets."""
import json
import os
from pathlib import Path
import re


def object_env(name):
    value = json.loads(os.environ.get(name) or "{}")
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def render(destination):
    domain = os.environ.get("APP_DOMAIN", "womanup.uz")
    if not re.fullmatch(r"(?=.{1,253}$)[a-z0-9]+(?:[-.][a-z0-9]+)*\.[a-z]{2,}", domain):
        raise ValueError("APP_DOMAIN must be a bare DNS name")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    if not re.fullmatch(r"[0-9a-fA-F]{64,128}", password):
        raise ValueError("POSTGRES_PASSWORD must be 64-128 hexadecimal characters")
    backend = object_env("BACKEND_VARS_JSON") | object_env("BACKEND_SECRETS_JSON")
    if len(str(backend.get("JWT_SECRET_KEY", ""))) < 48:
        raise ValueError("BACKEND_SECRETS_JSON needs a JWT_SECRET_KEY of at least 48 characters")
    backend.update(
        ENVIRONMENT="production", DEBUG="false", DB_ECHO="false",
        DATABASE_URL=f"postgresql+asyncpg://postgres:{password}@postgres:5432/womanup",
        CORS_ORIGINS=f"https://{domain}",
    )
    backend.setdefault("NEWS_INGEST_ENABLED", "false")
    frontend = {key: os.environ.get(key, "") for key in (
        "FIREBASE_WEB_API_KEY", "FIREBASE_WEB_AUTH_DOMAIN", "FIREBASE_WEB_PROJECT_ID",
        "FIREBASE_WEB_APP_ID", "FIREBASE_WEB_STORAGE_BUCKET", "FIREBASE_WEB_SENDER_ID",
    )}
    files = {
        "deploy.env": {"APP_DOMAIN": domain},
        "backend.env": backend,
        "frontend.env": frontend,
        "migration.env": {"DATABASE_URL": f"postgresql+asyncpg://postgres:{password}@postgres:5432/womanup"},
        "postgres.env": {"POSTGRES_USER": "postgres", "POSTGRES_DB": "womanup", "POSTGRES_PASSWORD": password},
    }
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, values in files.items():
        lines = []
        for key, value in sorted(values.items()):
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                raise ValueError("Invalid environment key")
            if isinstance(value, bool):
                value = str(value).lower()
            elif isinstance(value, (list, dict)):
                value = json.dumps(value, separators=(",", ":"))
            else:
                value = str(value)
            if "\x00" in value or "\r" in value:
                raise ValueError(f"Invalid control character in {key}")
            value = value.replace("\n", "\\n")
            lines.append(f"{key}={value}\n")
        path = destination / name
        path.write_text("".join(lines), encoding="utf-8")
        path.chmod(0o600)


if __name__ == "__main__":
    import sys
    render(Path(sys.argv[1]))
