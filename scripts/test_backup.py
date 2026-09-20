"""What the backups must keep doing.

Run: python3 scripts/test_backup.py

Taking the dump needs a server, a running postgres and the real database, so
most of this reads the scripts rather than running them: it pins the orderings
that make a backup worth having — verified before it is named, taken before a
migration touches anything, never all deleted at once — so that a later edit
cannot quietly undo them again.

The pruning rule is the exception. It is the one piece that can delete data,
so it is executed here against fabricated files.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).parent
BACKUP = (SCRIPTS / "backup.sh").read_text()
RESTORE = (SCRIPTS / "restore.sh").read_text()
DEPLOY = (SCRIPTS / "deploy.sh").read_text()
BOOTSTRAP = (SCRIPTS / "bootstrap.sh").read_text()
COMMON = (SCRIPTS / "common.sh").read_text()


def test_the_deploy_backs_up_before_it_stops_anything():
    body = DEPLOY[DEPLOY.index("deploy_backend() {") : DEPLOY.index("\ndeploy_frontend() {")]
    backup = body.index("scripts/backup.sh")
    assert backup < body.index("c stop backend worker")
    assert backup < body.index("c run --rm --no-deps migrate")
    # And it must be able to stop the deploy.
    assert re.search(r"if ! bash [^\n]*backup\.sh[^\n]*; then", body)
    assert "the running release was left untouched" in body


def test_a_dump_is_verified_before_it_is_named():
    partial = BACKUP.index('"$name.partial"')
    verify = BACKUP.index("pg_restore --list")
    rename = BACKUP.index('mv -- "$name.partial" "$name"')
    assert partial < verify < rename, "a dump nobody can read must not look like a backup"
    assert 'trap \'rm -f -- "$name.partial"\' EXIT' in BACKUP
    assert 'test -s "$name.partial"' in BACKUP


def test_the_backup_refuses_to_fill_the_disk():
    assert "pg_database_size" in BACKUP
    assert "df -PB1" in BACKUP
    space = BACKUP.index("available < needed")
    assert space < BACKUP.index("pg_dump"), "the space check must come before the dump"


def test_the_restore_cannot_be_run_by_accident():
    assert '[[ "${3:-}" == RESTORE ]]' in RESTORE
    assert '[[ "$backup" == "$ROOT/backups/"* && "$backup" == *.dump ]]' in RESTORE
    # It reads the dump before stopping anything, and keeps what it replaces.
    assert RESTORE.index("pg_restore --list") < RESTORE.index("c stop backend worker")
    assert RESTORE.index("backup.sh") < RESTORE.index("c stop backend worker")
    assert "pre-restore" in RESTORE
    # Nothing calls it on its own.
    for name in ("deploy.sh", "receive.sh", "ship.sh", "bootstrap.sh"):
        assert "restore.sh" not in (SCRIPTS / name).read_text(), name


def test_the_server_installs_the_nightly_timer():
    assert "womanup-backup.timer" in BOOTSTRAP
    assert "systemctl enable --now womanup-backup.timer" in BOOTSTRAP
    assert "rm -f /etc/systemd/system/womanup-backup.timer" not in BOOTSTRAP
    assert '"$ROOT/backups"' in BOOTSTRAP, "the directory must exist before the first run"
    assert '"$ROOT/backups"' in COMMON
    # The unit must not run before a release is unpacked.
    assert "ConditionPathExists=$ROOT/current/scripts/backup.sh" in BOOTSTRAP


def test_no_script_prints_a_configuration_value():
    for name in ("backup.sh", "restore.sh"):
        for line in (SCRIPTS / name).read_text().splitlines():
            stripped = line.strip()
            if not stripped.startswith(("echo", "printf")):
                continue
            assert "CONFIG_DIR" not in stripped, f"{name}: {stripped}"
            assert not re.search(r"\$\{?(JWT|SMTP|POSTGRES|ANTHROPIC|FIREBASE)", stripped), (
                f"{name}: {stripped}"
            )


# --------------------------------------------------------- the pruning rule


def prune(directory: Path) -> None:
    """Run backup.sh's pruner, and nothing else, against this directory."""
    function = BACKUP[BACKUP.index("KEEP_DAYS=") : BACKUP.index("free_bytes() {")]
    script = f'set -euo pipefail\nROOT="$1"\n{function}\nprune_old_backups\n'
    subprocess.run(
        ["bash", "-c", script, "bash", str(directory)], check=True, capture_output=True, text=True
    )


def dumps(directory: Path, ages_in_days: list[int]) -> list[Path]:
    (directory / "backups").mkdir(parents=True, exist_ok=True)
    made = []
    for index, age in enumerate(ages_in_days):
        path = directory / "backups" / f"2026090{index}T000000000000000Z-daily.dump"
        path.write_text("dump")
        when = time.time() - age * 86400
        os.utime(path, (when, when))
        made.append(path)
    return made


def test_a_fortnight_of_failed_timers_still_leaves_something_to_restore():
    """The rule this replaces deleted every dump older than a week — all of them."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        made = dumps(root, [40, 30, 20, 15, 12])
        prune(root)
        surviving = sorted(p.name for p in (root / "backups").iterdir())
        assert len(surviving) == 3, surviving
        # The three newest, whatever their age.
        assert surviving == sorted(p.name for p in made[-3:]), surviving


def test_this_week_is_never_pruned():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        dumps(root, [6, 5, 4, 3, 2, 1, 0])
        prune(root)
        assert len(list((root / "backups").iterdir())) == 7


def test_an_empty_directory_is_not_an_error():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "backups").mkdir()
        prune(root)


def test_only_dumps_are_deleted():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        dumps(root, [40, 39, 38, 37])
        stray = root / "backups" / "README"
        stray.write_text("not a dump")
        os.utime(stray, (time.time() - 90 * 86400,) * 2)
        prune(root)
        assert stray.exists()


if __name__ == "__main__":
    for name, case in sorted(vars().items()):
        if name.startswith("test_") and callable(case):
            case()
            print(f"ok  {name}")
    print("backups: all checks passed", file=sys.stdout)
