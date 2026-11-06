"""Render only explicitly selected prod environment values; never log secrets."""
import json
import os
from pathlib import Path
import re
from urllib.parse import quote


def selected_env(names):
    return {name: os.environ[name] for name in names if os.environ.get(name, "") != ""}


def render(destination):
    domain = os.environ.get("APP_DOMAIN", "")
    if not re.fullmatch(r"(?=.{1,253}$)[a-z0-9]+(?:[-.][a-z0-9]+)*\.[a-z]{2,}", domain):
        raise ValueError("APP_DOMAIN must be a bare DNS name")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    if not password or any(c in password for c in "\r\n\x00"):
        raise ValueError("POSTGRES_PASSWORD must be a nonempty single-line application password")
    database = {key: os.environ.get(key, "") for key in
                ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_NETWORK", "INGRESS_NETWORK")}
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*", database["DB_HOST"]):
        raise ValueError("Invalid DB_HOST")
    if not database["DB_PORT"].isascii() or not database["DB_PORT"].isdigit() or not 0 < int(database["DB_PORT"]) < 65536:
        raise ValueError("Invalid DB_PORT")
    # These are the database and owner verified on the dedicated host. Fail closed
    # rather than risk restoring or migrating another tenant through a typo.
    if database["DB_NAME"] != "womanup_db" or database["DB_USER"] != "womanup_user":
        raise ValueError("Expected the provisioned WomanUP database and role")
    for key in ("DB_NETWORK", "INGRESS_NETWORK"):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", database[key]):
            raise ValueError(f"Invalid {key}")
    url = (f"postgresql+asyncpg://{quote(database['DB_USER'], safe='')}:"
           f"{quote(password, safe='')}@{database['DB_HOST']}:"
           f"{database['DB_PORT']}/{database['DB_NAME']}")
    backend = selected_env((
        "JWT_SECRET_KEY", "FIREBASE_PRIVATE_KEY", "ANTHROPIC_API_KEY",
        "SMS_PROVIDER_TOKEN", "SMTP_PASSWORD", "EDU_JOB_CLIENT_SECRET",
        "INVEST_HUB_CLIENT_SECRET", "COMMERCE_CLIENT_SECRET", "S3_ACCESS_KEY",
        "S3_SECRET_KEY", "DB_POOL_SIZE", "DB_MAX_OVERFLOW",
        "ACCESS_TOKEN_TTL_MINUTES", "REFRESH_TOKEN_TTL_DAYS", "OTP_LENGTH",
        "OTP_TTL_SECONDS", "OTP_MAX_ATTEMPTS", "OTP_RESEND_COOLDOWN_SECONDS",
        "FIREBASE_PROJECT_ID", "FIREBASE_CLIENT_EMAIL", "FIREBASE_ALLOWED_DOMAIN",
        "DEFAULT_LANGUAGE", "AI_MODEL", "AI_EFFORT", "AI_MAX_TOKENS",
        "ASSISTANT_GUEST_QUESTIONS", "AI_RAG_TOP_K", "AI_MIN_CONFIDENCE",
        "EMBEDDING_DIMENSIONS", "NEWS_INGEST_ENABLED", "NEWS_INGEST_INTERVAL_HOURS",
        "NEWS_INGEST_MAX_POSTS", "NEWS_INGEST_LOOKBACK_HOURS",
        "NEWS_INGEST_DEDUP_DAYS", "NEWS_INGEST_AUTO_PUBLISH",
        "NEWS_INGEST_ALLOWED_DOMAINS", "SMS_PROVIDER_URL", "SMTP_HOST",
        "SMTP_PORT", "SMTP_USER", "SMTP_FROM", "EDU_JOB_BASE_URL",
        "EDU_JOB_CLIENT_ID", "INVEST_HUB_BASE_URL", "INVEST_HUB_CLIENT_ID",
        "COMMERCE_BASE_URL", "COMMERCE_CLIENT_ID", "INTEGRATION_TIMEOUT_SECONDS",
        "INTEGRATION_MAX_RETRIES", "S3_ENDPOINT_URL", "S3_BUCKET",
        "RATE_LIMIT_PER_MINUTE",
    ))
    if len(backend.get("JWT_SECRET_KEY", "")) < 48:
        raise ValueError("JWT_SECRET_KEY must be at least 48 characters")
    backend.update(
        ENVIRONMENT="production", DEBUG="false", DB_ECHO="false",
        DATABASE_URL=url,
        CORS_ORIGINS=f"https://{domain}",
    )
    frontend = {key: os.environ.get(key, "") for key in (
        "FIREBASE_WEB_API_KEY", "FIREBASE_WEB_AUTH_DOMAIN", "FIREBASE_WEB_PROJECT_ID",
        "FIREBASE_WEB_APP_ID", "FIREBASE_WEB_STORAGE_BUCKET", "FIREBASE_WEB_SENDER_ID",
    )}
    files = {
        "deploy.env": {"APP_DOMAIN": domain, "DB_NETWORK": database["DB_NETWORK"],
                       "INGRESS_NETWORK": database["INGRESS_NETWORK"]},
        "backend.env": backend,
        "frontend.env": frontend,
        "database.env": {key: database[key] for key in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER")}
                        | {"POSTGRES_PASSWORD": password},
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
