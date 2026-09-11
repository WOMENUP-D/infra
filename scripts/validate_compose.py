"""Reject malformed Compose mount entries that config parsing alone accepts."""
import json
import sys


config = json.load(sys.stdin)
for service_name, service in config.get("services", {}).items():
    for mount in service.get("tmpfs", []):
        path = mount.split(":", 1)[0]
        if not path.startswith("/"):
            raise SystemExit(f"{service_name}: tmpfs path must be absolute: {mount}")
