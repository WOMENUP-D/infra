"""What the renderer must refuse, and what it must never say.

Run: python3 scripts/test_render_config.py

The outage of 12 September 2026 started here: a setting the backend parses as
a number arrived as something else, and nothing noticed until the migration
ran — with the site already stopped. These tests keep that check at the front,
and keep the values out of the message, because this output ends up in a
public Actions log.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import render_config  # noqa: E402

SECRET_PORT = "smtp.example.com"
GOOD = {
    "APP_DOMAIN": "womanup.uz",
    "POSTGRES_PASSWORD": "a" * 64,
    "JWT_SECRET_KEY": "k" * 64,
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "mail@example.com",
    "NEWS_INGEST_ENABLED": "true",
    "AI_MIN_CONFIDENCE": "0.6",
    "EDU_JOB_BASE_URL": "https://edu.example.uz",
}


def render(**overrides):
    """Render into a throwaway directory with only these values in the env."""
    environment = {**GOOD, **overrides}
    for name in list(environment):
        if environment[name] is None:
            del environment[name]
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update({k: v for k, v in environment.items() if v is not None})
    try:
        with tempfile.TemporaryDirectory() as directory:
            render_config.render(Path(directory) / "config")
            return {
                path.name: path.read_text()
                for path in (Path(directory) / "config").iterdir()
            }
    finally:
        os.environ.clear()
        os.environ.update(saved)


def refused(**overrides) -> str:
    try:
        render(**overrides)
    except ValueError as exc:
        return str(exc)
    raise AssertionError(f"the renderer accepted {overrides}")


def test_a_valid_configuration_renders():
    files = render()
    assert set(files) == {
        "deploy.env",
        "backend.env",
        "frontend.env",
        "migration.env",
        "postgres.env",
    }
    assert "SMTP_PORT=587\n" in files["backend.env"]
    assert "ENVIRONMENT=production\n" in files["backend.env"]


def test_a_port_that_is_not_a_port_is_refused_by_name_only():
    for value in (SECRET_PORT, "0", "70000", "smtp:587", "587;rm -rf /"):
        message = refused(SMTP_PORT=value)
        assert "SMTP_PORT" in message, message
        # The value itself is somebody's configuration, and this message is
        # printed into a public log.
        assert value.strip() not in message, message
        assert SECRET_PORT not in message


def test_a_blank_typed_value_counts_as_unset():
    files = render(SMTP_PORT=" ")
    assert "SMTP_PORT" not in files["backend.env"]


def test_quotes_and_spaces_around_a_typed_value_are_tidied_away():
    """The shape a secret store hands back is not a reason to break production."""
    for value in ('"587"', "587 ", " 587", "'587'"):
        files = render(SMTP_PORT=value)
        assert "SMTP_PORT=587\n" in files["backend.env"], value


def test_the_other_typed_settings_are_checked_too():
    assert "OTP_MAX_ATTEMPTS" in refused(OTP_MAX_ATTEMPTS="five")
    assert "AI_MIN_CONFIDENCE" in refused(AI_MIN_CONFIDENCE="2.5")
    assert "NEWS_INGEST_ENABLED" in refused(NEWS_INGEST_ENABLED="maybe")
    assert "EDU_JOB_BASE_URL" in refused(EDU_JOB_BASE_URL="edu.example.uz")
    assert "SMTP_HOST" in refused(SMTP_HOST="smtp example com")
    # Several at once are reported together, so one deploy fixes them all.
    both = refused(SMTP_PORT="x", OTP_LENGTH="long")
    assert "SMTP_PORT" in both and "OTP_LENGTH" in both


def test_missing_required_settings_are_named():
    for name in ("APP_DOMAIN", "POSTGRES_PASSWORD", "JWT_SECRET_KEY"):
        message = refused(**{name: None})
        assert name in message, message


def test_a_secret_never_reaches_the_message():
    password = "f" * 64
    message = refused(POSTGRES_PASSWORD=password, JWT_SECRET_KEY="short")
    assert password not in message
    assert "short" not in message


def test_settings_that_are_not_set_stay_out_of_the_files():
    files = render(SMTP_PORT=None, SMTP_HOST=None)
    assert "SMTP_PORT" not in files["backend.env"]
    assert "SMTP_HOST" not in files["backend.env"]


if __name__ == "__main__":
    for name, case in sorted(vars().items()):
        if name.startswith("test_") and callable(case):
            case()
            print(f"ok  {name}")
    print("render_config: all checks passed")
