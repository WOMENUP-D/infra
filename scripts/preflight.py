"""Read-only collision checks for the already provisioned Docker host."""
import json
from pathlib import Path
import subprocess
import sys


def inspect(*args):
    return json.loads(subprocess.check_output(["docker", *args], text=True))


def check(root):
    if str(root) != "/opt/womanup" or root.is_symlink():
        raise ValueError("Expected isolated /opt/womanup storage")
    env = dict(line.split("=", 1) for line in (root / "config/deploy.env").read_text().splitlines())
    db = inspect("network", "inspect", env["DB_NETWORK"])[0]
    ingress = inspect("network", "inspect", env["INGRESS_NETWORK"])[0]
    if db["Name"] == ingress["Name"]:
        raise ValueError("Database and ingress networks must be separate")
    names = {value["Name"] for value in db.get("Containers", {}).values()}
    if "infrastructure-postgres-postgres-1" not in names:
        raise ValueError("Shared PostgreSQL is not attached to DB_NETWORK")
    # Only the proxy joins ingress; generic app aliases remain project-private.
    for cid in ingress.get("Containers", {}):
        container = inspect("inspect", cid)[0]
        aliases = container["NetworkSettings"]["Networks"][ingress["Name"]].get("Aliases") or []
        if "womanup-proxy" in aliases and container["Config"]["Labels"].get("com.docker.compose.project") != "womanup":
            raise ValueError("womanup-proxy alias belongs to another project")
    ids = subprocess.check_output(["docker", "ps", "-aq", "--filter",
                                   "label=com.docker.compose.project=womanup"], text=True).split()
    for cid in ids:
        labels = inspect("inspect", cid)[0]["Config"]["Labels"]
        directory = Path(labels.get("com.docker.compose.project.working_dir", "/"))
        if root not in directory.parents and directory != root:
            raise ValueError("Compose project womanup is already used outside its root")
    print("WomanUP storage, shared networks and proxy alias verified; no host ports published.")


if __name__ == "__main__":
    check(Path(sys.argv[1]))
