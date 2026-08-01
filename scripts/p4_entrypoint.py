"""Load infrastructure bootstrap files without printing them, then exec a command."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote


def _read(name: str) -> str:
    value = (Path("/run/p4-runtime") / name).read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"runtime file is empty: {name}")
    return value


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("command required")
    password = quote(_read("postgres_password"), safe="")
    os.environ["DATABASE_URL"] = f"postgresql+psycopg://alpha:{password}@db:5432/renewable_p4"
    redis_password = quote(_read("redis_password"), safe="")
    os.environ["REDIS_URL"] = f"redis://:{redis_password}@redis:6379/0"
    os.environ["SECRET_KEY"] = _read("application_signing_key")
    os.execvpe(sys.argv[1], sys.argv[1:], os.environ)


if __name__ == "__main__":
    main()
