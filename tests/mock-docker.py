#!/usr/bin/env python3
"""A stateful Docker test double for deployment control flow, never production."""
import json
import os
from pathlib import Path
import sys

root = Path(os.environ["MOCK_ROOT"])
args = sys.argv[1:]
state_file = root / "mock-schema"
schema = state_file.read_text() if state_file.exists() else "0012"
with (root / "commands.jsonl").open("a") as log:
    log.write(json.dumps({"args": args, "backend": os.getenv("BACKEND_IMAGE"), "frontend": os.getenv("FRONTEND_IMAGE")}) + "\n")
if args[0] == "inspect":
    print("healthy")
    sys.exit()
if args[0] == "login":
    sys.stdin.read()
    sys.exit()
args = args[args.index("-f") + 2:]
if args[:2] == ["ps", "-q"]:
    print(args[-1])
elif args[0] == "exec":
    if "pg_dump" in args:
        print("verified test dump")
    elif "pg_restore" in args:
        sys.stdin.read()
        print("mock archive listing")
    elif "psql" in args:
        if "-Atc" in args:
            query = args[-1]
            print("t" if "to_regclass" in query else schema)
        else:
            sys.stdin.read()
elif args[0] == "run" and args[-1] == "migrate":
    if os.getenv("MOCK_MIGRATION_FAIL"):
        sys.exit(1)
    if os.getenv("MOCK_NEW_SCHEMA"):
        state_file.write_text(os.environ["MOCK_NEW_SCHEMA"])
elif args[0] == "up":
    image = os.getenv("BACKEND_IMAGE") if "backend" in args else os.getenv("FRONTEND_IMAGE")
    if image and image == os.getenv("MOCK_FAIL_IMAGE"):
        sys.exit(1)
