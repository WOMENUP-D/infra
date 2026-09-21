"""Render only explicitly selected prod environment values; never log secrets."""
import json
import os
from pathlib import Path
import re


def selected_env(names):
    return {name: os.environ[name] for name in names if os.environ.get(name, "") != ""}


# Settings the backend parses as something other than text. A value that does
# not parse used to reach the server and fail inside the migration — after the
# running containers had been stopped. They are checked here instead, in CI,
# before anything is shipped. Ranges are the ones the application accepts.
INTEGERS = {
    "SMTP_PORT": (1, 65535),
    "DB_POOL_SIZE": (1, 1000),
    "DB_MAX_OVERFLOW": (0, 1000),
    "ACCESS_TOKEN_TTL_MINUTES": (1, 1440),
    "REFRESH_TOKEN_TTL_DAYS": (1, 365),
    "OTP_LENGTH": (4, 8),
    "OTP_TTL_SECONDS": (30, 3600),
    "OTP_MAX_ATTEMPTS": (1, 20),
    "OTP_RESEND_COOLDOWN_SECONDS": (0, 3600),
    "AI_MAX_TOKENS": (256, 200000),
    "ASSISTANT_GUEST_QUESTIONS": (0, 100),
    "AI_RAG_TOP_K": (1, 50),
    "EMBEDDING_DIMENSIONS": (64, 4096),
    "NEWS_INGEST_INTERVAL_HOURS": (1, 168),
    "NEWS_INGEST_MAX_POSTS": (1, 100),
    "NEWS_INGEST_LOOKBACK_HOURS": (1, 720),
    "NEWS_INGEST_DEDUP_DAYS": (1, 365),
    "INTEGRATION_TIMEOUT_SECONDS": (1, 120),
    "INTEGRATION_MAX_RETRIES": (0, 20),
    "RATE_LIMIT_PER_MINUTE": (1, 100000),
}
BOOLEANS = ("NEWS_INGEST_ENABLED", "NEWS_INGEST_AUTO_PUBLISH")
FRACTIONS = {"AI_MIN_CONFIDENCE": (0.0, 1.0)}
URLS = (
    "SMS_PROVIDER_URL",
    "EDU_JOB_BASE_URL",
    "INVEST_HUB_BASE_URL",
    "COMMERCE_BASE_URL",
    "S3_ENDPOINT_URL",
)
HOSTNAMES = ("SMTP_HOST",)
#: Nothing starts without these.
REQUIRED = ("APP_DOMAIN", "POSTGRES_PASSWORD", "JWT_SECRET_KEY")


TYPED = (
    tuple(INTEGERS) + BOOLEANS + tuple(FRACTIONS) + URLS + HOSTNAMES
)


def tidy_typed(values):
    """Strip the spaces and quotes a secret store adds around a typed value.

    `SMTP_PORT="587"` is unambiguous, and refusing the deploy over the quotes
    would help nobody. A value that still does not parse afterwards is a real
    mistake and `check_types` refuses it.
    """
    for name in TYPED:
        raw = values.get(name)
        if raw is None:
            continue
        text = raw.strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
            text = text[1:-1].strip()
        if text:
            values[name] = text
        else:
            # Nothing but spaces or empty quotes: the same as never set, and
            # the backend's own default applies.
            del values[name]
    return values


def check_types(values):
    """Reject settings that will not parse. Names only: values are secrets."""
    bad = []
    for name, (low, high) in INTEGERS.items():
        raw = values.get(name)
        if raw in (None, ""):
            continue
        text = raw.strip()
        if not re.fullmatch(r"[0-9]+", text) or not low <= int(text) <= high:
            bad.append(name)
    for name in BOOLEANS:
        raw = values.get(name)
        if raw not in (None, "") and raw.strip().lower() not in {
            "true", "false", "1", "0", "yes", "no", "on", "off",
        }:
            bad.append(name)
    for name, (low, high) in FRACTIONS.items():
        raw = values.get(name)
        if raw in (None, ""):
            continue
        try:
            number = float(raw.strip())
        except ValueError:
            bad.append(name)
        else:
            if not low <= number <= high:
                bad.append(name)
    for name in URLS:
        raw = values.get(name)
        if raw not in (None, "") and not re.fullmatch(r"https?://[^\s\"']+", raw.strip()):
            bad.append(name)
    for name in HOSTNAMES:
        raw = values.get(name)
        if raw not in (None, "") and not re.fullmatch(
            r"(?=.{1,253}$)[a-zA-Z0-9]+(?:[-.][a-zA-Z0-9]+)*", raw.strip()
        ):
            bad.append(name)
    if bad:
        raise ValueError(
            "These production settings are not in the form the backend expects: "
            + ", ".join(sorted(set(bad)))
            + ". Write a bare value with no quotes or spaces. (Values are not shown.)"
        )


def render(destination):
    absent = [name for name in REQUIRED if not os.environ.get(name, "").strip()]
    if absent:
        raise ValueError(f"Missing required production settings: {', '.join(absent)}")
    domain = os.environ.get("APP_DOMAIN", "")
    if not re.fullmatch(r"(?=.{1,253}$)[a-z0-9]+(?:[-.][a-z0-9]+)*\.[a-z]{2,}", domain):
        raise ValueError("APP_DOMAIN must be a bare DNS name")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    if not re.fullmatch(r"[0-9a-fA-F]{64,128}", password):
        raise ValueError("POSTGRES_PASSWORD must be 64-128 hexadecimal characters")
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
    check_types(tidy_typed(backend))
    backend.update(
        ENVIRONMENT="production", DEBUG="false", DB_ECHO="false",
        DATABASE_URL=f"postgresql+asyncpg://postgres:{password}@postgres:5432/womanup",
        CORS_ORIGINS=f"https://{domain}",
    )
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
