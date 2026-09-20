"""Check a release against its rendered configuration before anything stops.

Runs inside the incoming image, with the same environment files the backend
and the migration will use. It answers one question: would this image start
and migrate with this configuration? The deploy only stops the running
containers once the answer is yes.

This exists because it once answered no in the worst possible order. On
12 September 2026 the deploy stopped the API and the worker, then ran the
migration, which failed while reading the settings — a mistyped SMTP port —
and left production down. Nothing had touched the database; the outage was
entirely avoidable by asking first.

Nothing here prints a value. A rejected setting is reported by name, because
the values are secrets and this output goes into a public Actions log.
"""

from __future__ import annotations

import os
import sys

#: Without these the backend cannot start at all.
REQUIRED = ("DATABASE_URL", "JWT_SECRET_KEY", "ENVIRONMENT", "CORS_ORIGINS")


def fail(message: str) -> None:
    print(f"preflight: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_required() -> None:
    missing = [name for name in REQUIRED if not os.environ.get(name, "").strip()]
    if missing:
        fail(f"missing required settings: {', '.join(missing)}")


def check_settings():
    """Build the real Settings object: every typed field is validated here."""
    try:
        from pydantic import ValidationError
    except ModuleNotFoundError:  # pragma: no cover - the image always has it
        ValidationError = Exception  # type: ignore[assignment,misc]
    try:
        from app.core.config import Settings
    except Exception as exc:  # noqa: BLE001 - the type is all we may print
        fail(f"the application package could not be imported: {type(exc).__name__}")
    try:
        return Settings()
    except ValidationError as exc:  # type: ignore[misc]
        names = sorted({".".join(str(part) for part in error["loc"]) for error in exc.errors()})
        fail(f"settings rejected: {', '.join(names)} (values are not shown)")
    except Exception as exc:  # noqa: BLE001
        fail(f"settings rejected: {type(exc).__name__}")


def check_production(settings) -> None:
    problems: list[str] = []
    if settings.environment != "production":
        problems.append("ENVIRONMENT")
    if len(settings.jwt_secret_key) < 48 or "change-me" in settings.jwt_secret_key:
        problems.append("JWT_SECRET_KEY")
    if settings.debug:
        problems.append("DEBUG")
    port = os.environ.get("SMTP_PORT", "").strip()
    if port and settings.smtp_port is None:
        # The application degrades to "no e-mail" rather than refusing to
        # start; a deploy should not quietly ship that.
        problems.append("SMTP_PORT")
    if os.environ.get("SMTP_HOST", "").strip() and settings.smtp_port is None:
        problems.append("SMTP_PORT")
    if problems:
        fail(f"not usable in production: {', '.join(sorted(set(problems)))} (values are not shown)")


def check_alembic() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    for candidate in ("alembic.ini", "/app/alembic.ini"):
        if os.path.exists(candidate):
            try:
                script = ScriptDirectory.from_config(Config(candidate))
                head = script.get_current_head()
            except Exception as exc:  # noqa: BLE001
                fail(f"alembic configuration is unusable: {type(exc).__name__}")
            if not head:
                fail("alembic has no head revision")
            return str(head)
    fail("alembic.ini was not found in the image")
    return ""


def check_database(settings) -> str:
    """Connect with the rendered credentials and read the schema revision."""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def ask() -> str:
        engine = create_async_engine(str(settings.database_url), connect_args={"timeout": 10})
        try:
            async with engine.connect() as connection:
                exists = await connection.scalar(
                    text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
                )
                if not exists:
                    return "none (first deployment)"
                revisions = (
                    await connection.scalars(text("SELECT version_num FROM alembic_version"))
                ).all()
                return ", ".join(sorted(revisions)) or "none"
        finally:
            await engine.dispose()

    try:
        return asyncio.run(ask())
    except Exception as exc:  # noqa: BLE001
        fail(f"the database refused the rendered DATABASE_URL: {type(exc).__name__}")
        return ""


def main() -> None:
    check_required()
    settings = check_settings()
    check_production(settings)
    head = check_alembic()
    current = check_database(settings)
    print(
        "preflight: configuration accepted "
        f"(environment={settings.environment}, alembic head={head}, database at {current})"
    )


if __name__ == "__main__":
    main()
