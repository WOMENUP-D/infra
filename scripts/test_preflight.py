"""The gate that stands in front of `docker compose stop`.

Run against a checkout of the backend:

    BACKEND_DIR=/path/to/backend BACKEND_PYTHON=/path/to/.venv/bin/python \\
    PREFLIGHT_DATABASE_URL=postgresql+asyncpg://user@localhost:5432/db \\
        python3 scripts/test_preflight.py

Each case runs `scripts/preflight.py` exactly as the deploy runs it — a real
process, the real settings class, a real database connection — and asks two
questions: was the release refused, and did the refusal keep the values to
itself.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
BACKEND = Path(os.environ.get("BACKEND_DIR", "")).expanduser()
PYTHON = os.environ.get("BACKEND_PYTHON", sys.executable)
DATABASE_URL = os.environ.get("PREFLIGHT_DATABASE_URL", "")
SECRET = "s3cret-" + "x" * 60


def run(**overrides) -> subprocess.CompletedProcess:
    """Run the preflight with a clean environment and this configuration."""
    environment = {
        "PATH": os.environ["PATH"],
        "DATABASE_URL": DATABASE_URL,
        "JWT_SECRET_KEY": SECRET,
        "ENVIRONMENT": "production",
        "CORS_ORIGINS": "https://womanup.uz",
        "DEBUG": "false",
        "PYTHONPATH": str(BACKEND),
    }
    for name, value in overrides.items():
        if value is None:
            environment.pop(name, None)
        else:
            environment[name] = value

    with tempfile.TemporaryDirectory() as directory:
        # The image has alembic.ini beside the application; a temporary
        # directory keeps the developer's own .env out of the way.
        work = Path(directory)
        (work / "alembic.ini").symlink_to(BACKEND / "alembic.ini")
        (work / "alembic").symlink_to(BACKEND / "alembic")
        return subprocess.run(
            [PYTHON, str(HERE / "preflight.py")],
            env=environment,
            cwd=work,
            capture_output=True,
            text=True,
            timeout=180,
        )


def refused(**overrides) -> str:
    result = run(**overrides)
    assert result.returncode != 0, f"the preflight accepted {overrides}:\n{result.stdout}"
    output = result.stdout + result.stderr
    assert SECRET not in output, "the secret reached the log"
    return output


def test_a_good_configuration_passes():
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "configuration accepted" in result.stdout
    assert "alembic head" in result.stdout
    assert SECRET not in result.stdout + result.stderr


def test_an_invalid_smtp_port_is_refused_without_showing_it():
    for value in ("smtp.example.com", "0", "not-a-port"):
        output = refused(SMTP_PORT=value)
        assert "SMTP_PORT" in output, output
        assert value not in output, output


def test_a_missing_required_setting_is_named():
    output = refused(DATABASE_URL=None)
    assert "DATABASE_URL" in output
    assert "missing required settings" in output


def test_a_weak_or_default_secret_is_refused():
    assert "JWT_SECRET_KEY" in refused(JWT_SECRET_KEY="short")
    assert "JWT_SECRET_KEY" in refused(JWT_SECRET_KEY="change-me-in-env" + "x" * 40)


def test_a_non_production_environment_is_refused():
    assert "ENVIRONMENT" in refused(ENVIRONMENT="local")
    assert "DEBUG" in refused(DEBUG="true")


def test_an_unusable_database_url_is_refused_without_showing_it():
    password = "p" * 40
    url = f"postgresql+asyncpg://postgres:{password}@127.0.0.1:59999/nowhere"
    output = refused(DATABASE_URL=url)
    assert "DATABASE_URL" in output, output
    assert password not in output, "the database password reached the log"


if __name__ == "__main__":
    if not BACKEND.is_dir() or not DATABASE_URL:
        print("BACKEND_DIR and PREFLIGHT_DATABASE_URL are required", file=sys.stderr)
        raise SystemExit(2)
    for name, case in sorted(vars().items()):
        if name.startswith("test_") and callable(case):
            case()
            print(f"ok  {name}")
    print("preflight: all checks passed")
