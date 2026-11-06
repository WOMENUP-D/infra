"""Project-only snapshots. Never back up a cluster, roles or Docker volumes."""
import database as db_client
from datetime import datetime, timezone
import hashlib
import json
import shutil
import time
import re
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile
import uuid


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def media_members(archive):
    members = archive.getmembers()
    for member in members:
        path = PurePosixPath(member.name)
        if (path.is_absolute() or ".." in path.parts or not path.parts
                or path.parts[0] != "media" or not (member.isdir() or member.isfile())):
            raise ValueError("Media archive must contain only regular files under media/")
    return members


def database(root, action, *options):
    subprocess.run([sys.executable, str(Path(__file__).with_name("database.py")),
                    str(root / "config"), action, *map(str, options)], check=True)


def backup(root):
    backup_root = root / "backups"
    backup_root.mkdir(mode=0o700, exist_ok=True)
    values = db_client.settings(root / "config")
    size = int(db_client.query(values, "SELECT pg_database_size(current_database());"))
    media_size = sum(p.stat().st_size for p in (root / "data/media").rglob("*") if p.is_file())
    if shutil.disk_usage(backup_root).free < (size + media_size) * 3 // 2 + 268435456:
        raise RuntimeError("Insufficient space for WomanUP snapshot")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    snapshot = backup_root / stamp
    snapshot.mkdir(mode=0o700)
    database(root, "dump", "--file", snapshot / "database.dump")
    with (snapshot / "database.dump").open("rb") as source:
        subprocess.run(["docker", "exec", "-i", db_client.CONTAINER,
                        "pg_restore", "--list"], stdin=source,
                       stdout=subprocess.DEVNULL, check=True)
    media = root / "data/media"
    if media.is_symlink():
        raise ValueError("Media directory cannot be a symlink")
    with tarfile.open(snapshot / "media.tar.gz", "w:gz") as archive:
        archive.add(media, arcname="media", filter=reject_links)
    manifest = {"database": "womanup_db", "role": "womanup_user", "schema": "public",
                "media": "local-only", "sha256": {name: digest(snapshot / name)
                for name in ("database.dump", "media.tar.gz")}}
    # The manifest is written last: partial snapshots can never be restored.
    (snapshot / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    prune(backup_root)
    print(f"WomanUP database and local media snapshot: {snapshot}")
    print("External S3 media, when used, requires a separate bucket-scoped snapshot.")
    return snapshot


def prune(directory):
    """Retain at least three complete snapshots and every snapshot from this week."""
    snapshots = []
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_dir() or not re.fullmatch(r"\d{8}T\d{6}Z-[a-f0-9]{8}", path.name):
            continue
        manifest = path / "manifest.json"
        if manifest.is_file() and json.loads(manifest.read_text()).get("database") == "womanup_db":
            snapshots.append(path)
    snapshots.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for path in snapshots[3:]:
        if path.stat().st_mtime >= time.time() - 7 * 86400:
            continue
        if {p.name for p in path.iterdir()} != {"database.dump", "media.tar.gz", "manifest.json"}:
            continue
        for file in path.iterdir():
            file.unlink()
        path.rmdir()


def reject_links(member):
    if not (member.isfile() or member.isdir()):
        raise ValueError("Media backup refuses symlinks and special files")
    return member


def restore(root, snapshot):
    manifest = json.loads((snapshot / "manifest.json").read_text())
    if (manifest.get("database"), manifest.get("role"), manifest.get("schema"), manifest.get("media")) != (
            "womanup_db", "womanup_user", "public", "local-only"):
        raise ValueError("Snapshot does not belong to this project's database and local media")
    for name in ("database.dump", "media.tar.gz"):
        if digest(snapshot / name) != manifest["sha256"][name]:
            raise ValueError("Snapshot checksum mismatch")
    media = root / "data/media"
    if media.is_symlink():
        raise ValueError("Media directory cannot be a symlink")
    # Validate and stage media before making any database change.
    with tempfile.TemporaryDirectory(prefix="restore-", dir=root / "data") as stage:
        with tarfile.open(snapshot / "media.tar.gz", "r:gz") as archive:
            members = media_members(archive)
            archive.extractall(stage, members=members, filter="data")
        if not (Path(stage) / "media").is_dir():
            raise ValueError("Snapshot lacks a media directory")
        safety = backup(root)
        database(root, "restore", "--file", snapshot / "database.dump", "--confirm", "womanup_db")
        # Retain existing files rather than deleting them during recovery.
        preserved = root / "data" / ("media-before-" + safety.name)
        media.rename(preserved)
        (Path(stage) / "media").rename(media)
    print(f"WomanUP restored; previous media retained at {preserved}. Services remain stopped.")


if __name__ == "__main__":
    root = Path(sys.argv[1])
    if root != Path("/opt/womanup") or root.is_symlink():
        raise ValueError("Expected isolated /opt/womanup storage")
    if sys.argv[2] == "backup":
        backup(root)
    elif sys.argv[2] == "restore":
        restore(root, Path(sys.argv[3]))
    else:
        raise ValueError("Expected backup or restore")
