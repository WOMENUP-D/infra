"""Reject malformed Compose mount entries that config parsing alone accepts."""
import json
import sys


config = json.load(sys.stdin)
services = config.get("services", {})
if "postgres" in services or "redis" in services:
    raise SystemExit("Do not provision shared services or add a new Redis arrangement")
for name in ("database", "ingress"):
    if not config["networks"][name].get("external"):
        raise SystemExit(f"{name}: expected an existing external network")
for name in ("backend", "worker", "migrate"):
    if name in services and "database" not in services[name]["networks"]:
        raise SystemExit(f"{name}: shared database network required")
for name, service in services.items():
    if service.get("ports"):
        raise SystemExit(f"{name}: host ports would conflict with existing ingress")
    if name != "caddy" and "ingress" in service.get("networks", {}):
        raise SystemExit(f"{name}: only the WomanUP proxy may join shared ingress")
for service_name, service in config.get("services", {}).items():
    for mount in service.get("tmpfs", []):
        path = mount.split(":", 1)[0]
        if not path.startswith("/"):
            raise SystemExit(f"{service_name}: tmpfs path must be absolute: {mount}")
