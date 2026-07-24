#!/usr/bin/env python3
"""Create and administer local BMC Hub accounts without enabling web registration.

Run from the project root (or /opt/bmc-hub after deployment).  Passwords are
requested from the terminal and are never written to command history.
"""

import argparse
import getpass
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_local_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()
sys.path.insert(0, str(ROOT))

from app.database import connection, init_db  # noqa: E402
from app.security import hash_password  # noqa: E402


ROLES = ("contributor", "reviewer", "admin")


def password_from_terminal() -> str:
    password = getpass.getpass("Password (at least 8 characters): ")
    confirmation = getpass.getpass("Repeat password: ")
    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters.")
    if password != confirmation:
        raise ValueError("Passwords do not match.")
    return password


def create_user(username: str, role: str) -> None:
    username = username.strip()
    if len(username) < 2:
        raise ValueError("Username must contain at least 2 characters.")
    password = password_from_terminal()
    db = connection()
    try:
        db.execute(
            "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
            (username, hash_password(password), role),
        )
        db.commit()
    finally:
        db.close()
    print(f"Created {username} with role {role}.")


def set_role(username: str, role: str) -> None:
    db = connection()
    try:
        cursor = db.execute("UPDATE users SET role=? WHERE username=?", (role, username.strip()))
        if not cursor.rowcount:
            raise ValueError("User does not exist.")
        db.commit()
    finally:
        db.close()
    print(f"Updated {username} to role {role}.")


def list_users() -> None:
    db = connection()
    try:
        rows = db.execute("SELECT username,role,created_at FROM users ORDER BY username").fetchall()
    finally:
        db.close()
    for row in rows:
        print(f"{row['username']}\t{row['role']}\t{row['created_at']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Create a local account")
    create.add_argument("--username", required=True)
    create.add_argument("--role", choices=ROLES, default="contributor")
    role = commands.add_parser("set-role", help="Change an existing account role")
    role.add_argument("--username", required=True)
    role.add_argument("--role", choices=ROLES, required=True)
    commands.add_parser("list", help="List accounts and roles")
    args = parser.parse_args()

    init_db()
    if args.command == "create":
        create_user(args.username, args.role)
    elif args.command == "set-role":
        set_role(args.username, args.role)
    else:
        list_users()


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(2)
