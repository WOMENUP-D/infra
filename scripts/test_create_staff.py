"""The button that opens a desk account, and the password it carries.

Run: python3 scripts/test_create_staff.py

This is the one path in the repository that moves a person's password from a
secret store onto the production server. It reads the scripts rather than
running them — that needs the server — and pins how the password travels: on
stdin, then through the environment, never in an argument (visible in `ps`)
and never in a message (visible in the public Actions log).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
SCRIPT = (HERE / "create_staff.sh").read_text()
WORKFLOW = (HERE.parent / ".github/workflows/create-staff-account.yml").read_text()


def test_the_password_arrives_on_stdin_and_leaves_through_the_environment():
    assert "IFS= read -r WOMANUP_STAFF_PASSWORD" in SCRIPT
    assert "export WOMANUP_STAFF_PASSWORD" in SCRIPT
    # `-e NAME` takes the value from the environment; `-e NAME=value` would put
    # it on the command line.
    assert "-e WOMANUP_STAFF_PASSWORD migrate" in SCRIPT
    assert "WOMANUP_STAFF_PASSWORD=$" not in SCRIPT
    launch = SCRIPT[SCRIPT.index("c run") :]
    assert "$WOMANUP_STAFF_PASSWORD" not in launch, "the password must not be an argument"


def test_the_workflow_sends_the_password_on_stdin_only():
    assert 'printf \'%s\\n\' "$STAFF_PASSWORD" | ssh' in WORKFLOW
    remote = WORKFLOW[WORKFLOW.index('"sudo -n bash') :].split("\n")[0]
    assert "PASSWORD" not in remote, "the password must not be part of the remote command"


def test_nothing_prints_the_password():
    for name, text in (("create_staff.sh", SCRIPT), ("workflow", WORKFLOW)):
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith(("echo", "printf")) or "| ssh" in stripped:
                continue
            # Naming the secret is fine; expanding it is not.
            assert not re.search(r"\$\{?(STAFF_PASSWORD|WOMANUP_STAFF_PASSWORD)", stripped), (
                f"{name}: {stripped}"
            )


def test_values_placed_in_the_remote_command_are_checked_first():
    run = WORKFLOW[WORKFLOW.index("run: |") :]
    ssh = run.index("| ssh")
    for pattern in (r'"\$EMAIL" =~', r'"\$ROLE" =~', r'"\$DEPLOY_ROOT" =~', r'"\$VPS_SSH_PORT" =~'):
        found = re.search(pattern, run)
        assert found and found.start() < ssh, pattern


def test_only_desk_roles_and_only_on_main():
    assert "if: github.ref == 'refs/heads/main'" in WORKFLOW
    assert "environment: prod" in WORKFLOW
    assert "options: [admin, regional_coordinator, moderator, trainer]" in WORKFLOW
    for text in (SCRIPT, WORKFLOW):
        assert "^(admin|regional_coordinator|moderator|trainer)$" in text


def test_it_waits_for_a_running_deploy():
    assert SCRIPT.index("lock_server") < SCRIPT.index("c run")
    assert "group: womanup-prod-server" in WORKFLOW


if __name__ == "__main__":
    for name, case in sorted(vars().items()):
        if name.startswith("test_") and callable(case):
            case()
            print(f"ok  {name}")
    print("create_staff: all checks passed", file=sys.stdout)
