"""Validate tracked image metadata before it can enter Compose or a shell."""
from pathlib import Path
import re
import sys


def read_image(path, app):
    lines = [line.strip() for line in Path(path).read_text().splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        return {}
    key = app.upper()
    if len(lines) != 2:
        raise ValueError(f"{app}: expected exactly IMAGE and VERSION")
    image, version = lines
    if not re.fullmatch(key + r"_IMAGE=ghcr\.io/womenup-d/" + app + r"@sha256:[0-9a-f]{64}", image):
        raise ValueError(f"{app}: invalid immutable image reference")
    if not re.fullmatch(key + "_VERSION=" + app + r"-[0-9a-f]{40}", version):
        raise ValueError(f"{app}: invalid source version")
    return dict(line.split("=", 1) for line in lines)


if __name__ == "__main__":
    for app in ("backend", "frontend"):
        read_image(Path(sys.argv[1]) / "apps" / app / "image.env", app)
