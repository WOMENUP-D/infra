"""The order the deploy does things in.

Run: python3 scripts/test_deploy_order.py

These are checks on the scripts themselves, not on a running deployment: a
real run needs Docker, a server and the images. They pin the three orderings
the outage of 12 September 2026 turned on — ask before stopping, restore after
a failed migration, and promote the last-known-good configuration only once a
release is healthy — so a later edit cannot quietly put them back.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent
DEPLOY = (SCRIPTS / "deploy.sh").read_text()
RECEIVE = (SCRIPTS / "receive.sh").read_text()


def backend_body() -> str:
    start = DEPLOY.index("deploy_backend() {")
    return DEPLOY[start : DEPLOY.index("\ndeploy_frontend() {", start)]


def test_the_preflight_runs_before_anything_is_stopped():
    body = backend_body()
    preflight = body.index("scripts/preflight.py")
    stop = body.index("c stop backend worker")
    assert preflight < stop, "the preflight must run while the old release is still serving"
    # And it must be able to fail the deploy.
    assert re.search(r"if ! c run [^\n]*preflight\.py[^\n]*; then", body)
    assert "the running release was left untouched" in body


def test_a_failed_migration_restores_the_running_release():
    body = backend_body()
    failure = body[body.index("if ! c run --rm --no-deps migrate; then") :]
    assert "restore_backend" in failure.split("return 1")[0]
    # Only when the schema is untouched; a half-applied schema is not
    # something to paper over.
    assert '"$before" == "$after"' in failure
    assert "apps remain stopped" in failure  # the honest branch still exists


def test_the_restore_puts_the_previous_image_and_config_back():
    restore = DEPLOY[DEPLOY.index("restore_backend() {") : DEPLOY.index("deploy_backend() {")]
    assert "config.previous/backend.env" in restore
    assert "BACKEND_IMAGE=\"$old_image\"" in restore
    assert "c up -d --no-deps --wait" in restore
    assert "postgres.env" in restore, "credentials must match before restoring"


def test_the_last_known_good_config_is_promoted_only_after_both_apps_are_up():
    promotion = 'cp -a "$CONFIG_DIR/." "$ROOT/config.previous/"'
    assert promotion in DEPLOY, "nothing promotes the working configuration"
    assert DEPLOY.index("deploy_frontend\n") < DEPLOY.index(promotion)
    # And the incoming release must not overwrite it on arrival any more.
    assert 'cp -a "$ROOT/config/." "$ROOT/config.previous/"' not in RECEIVE


def test_no_script_prints_a_configuration_value():
    for name, text in (("deploy.sh", DEPLOY), ("receive.sh", RECEIVE)):
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith(("echo", "printf")):
                continue
            assert "CONFIG_DIR" not in stripped, f"{name}: {stripped}"
            assert not re.search(r"\$\{?(JWT|SMTP|POSTGRES|ANTHROPIC|FIREBASE)", stripped), (
                f"{name}: {stripped}"
            )


if __name__ == "__main__":
    for name, case in sorted(vars().items()):
        if name.startswith("test_") and callable(case):
            case()
            print(f"ok  {name}")
    print("deploy order: all checks passed", file=sys.stdout)
