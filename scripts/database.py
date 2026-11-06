"""Operate only on WomanUP using application credentials and shared client tools.

The password travels over stdin, never argv, Docker's environment option, or logs.
The existing PostgreSQL container is never started, stopped or reconfigured.
"""
import argparse
from pathlib import Path
import subprocess
import sys

CONTAINER = "infrastructure-postgres-postgres-1"


def settings(config):
    values = dict(line.split("=", 1) for line in (config / "database.env").read_text().splitlines())
    if values["DB_NAME"] != "womanup_db" or values["DB_USER"] != "womanup_user":
        raise ValueError("Refusing a database or role outside WomanUP")
    if not values["POSTGRES_PASSWORD"]:
        raise ValueError("Missing application password")
    return values


def command(values, executable, *options):
    return ["docker", "exec", "-i", CONTAINER, "sh", "-c",
            'IFS= read -r PGPASSWORD; export PGPASSWORD; exec "$@"', "sh",
            executable, "-h", values["DB_HOST"], "-p", values["DB_PORT"],
            "-U", values["DB_USER"], "-w", *options]


def query(values, sql):
    result = subprocess.run(command(values, "psql", "-X", "-v", "ON_ERROR_STOP=1",
                                   "-d", values["DB_NAME"], "-At"),
                            input=(values["POSTGRES_PASSWORD"] + "\n" + sql).encode(),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError("WomanUP database query failed; check application access")
    return result.stdout.decode().strip()


def preflight(values):
    identity = query(values, """
        SELECT current_database(), current_user,
               pg_get_userbyid(d.datdba) = current_user,
               NOT (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR
                    r.rolreplication OR r.rolbypassrls),
               has_schema_privilege(current_user, 'public', 'CREATE')
        FROM pg_database d JOIN pg_roles r ON r.rolname = current_user
        WHERE d.datname = current_database();
    """)
    if identity != "womanup_db|womanup_user|t|t|t":
        raise RuntimeError("WomanUP role must own its database without administrator privileges")
    extensions = set(query(values, "SELECT extname FROM pg_extension;").splitlines())
    if not {"vector", "pg_trgm", "uuid-ossp"} <= extensions:
        raise RuntimeError("Administrator must preinstall vector, pg_trgm and uuid-ossp in womanup_db")


def revision(values):
    if query(values, "SELECT to_regclass('public.alembic_version') IS NOT NULL;") == "t":
        return query(values, "SELECT version_num FROM public.alembic_version ORDER BY version_num;")
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("action", choices=("preflight", "revision", "dump", "restore"))
    parser.add_argument("--file", type=Path)
    parser.add_argument("--confirm")
    args = parser.parse_args()
    values = settings(args.config)
    if args.action == "preflight":
        preflight(values)
        print("WomanUP database access, ownership and extensions verified.")
    elif args.action == "revision":
        print(revision(values))
    elif args.action == "dump":
        if args.file is None:
            parser.error("dump requires --file")
        with args.file.open("xb") as destination:
            args.file.chmod(0o600)
            subprocess.run(command(values, "pg_dump", "-d", values["DB_NAME"],
                                   "--format=custom", "--schema=public", "--no-owner", "--no-acl"),
                           input=(values["POSTGRES_PASSWORD"] + "\n").encode(),
                           stdout=destination, check=True)
    else:
        if args.file is None or args.confirm != "womanup_db":
            parser.error("restore requires --file and --confirm womanup_db")
        preflight(values)
        # No --create, role restoration, extension installation or cluster dump.
        process = subprocess.Popen(command(values, "pg_restore", "-d", values["DB_NAME"],
                                           "--schema=public", "--clean", "--if-exists", "--no-owner", "--no-acl",
                                           "--exit-on-error", "--single-transaction"),
                                   stdin=subprocess.PIPE)
        try:
            with args.file.open("rb") as source:
                process.stdin.write((values["POSTGRES_PASSWORD"] + "\n").encode())
                while chunk := source.read(1024 * 1024):
                    process.stdin.write(chunk)
            process.stdin.close()
        except BaseException:
            process.kill()
            process.wait()
            raise
        if process.wait():
            raise RuntimeError("WomanUP restore failed")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error) if isinstance(error, (ValueError, RuntimeError))
              else "WomanUP database operation failed", file=sys.stderr)
        sys.exit(1)
