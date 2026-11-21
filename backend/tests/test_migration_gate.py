import os
import subprocess
from pathlib import Path

import pytest
from alembic.config import Config

from backend.frameworks.database.migrations import require_single_head


@pytest.mark.parametrize("count", [0, 1, 2])
def test_gate_rejects_empty_and_multiple_real_migration_heads(tmp_path, count):
    versions = tmp_path / "versions"
    versions.mkdir()
    for number in range(count):
        (versions / f"revision_{number}.py").write_text(
            f"revision = 'revision_{number}'\ndown_revision = None\n"
        )
    config = Config()
    config.set_main_option("script_location", str(tmp_path))
    if count == 1:
        assert require_single_head(config) == "revision_0"
    else:
        with pytest.raises(RuntimeError, match="exactly one Alembic head"):
            require_single_head(config)


@pytest.mark.parametrize("migration_exit", [0, 7])
def test_startup_only_launches_app_after_successful_migration(tmp_path, migration_exit):
    # Intercept the executable boundary to prove a migration failure never
    # starts a server, and the host's PORT reaches the successful start command.
    binary = tmp_path / "uv"
    binary.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$START_LOG"\n'
        f'if [ "$2" = "alembic" ]; then exit {migration_exit}; fi\n'
    )
    binary.chmod(0o755)
    log = tmp_path / "commands"
    result = subprocess.run(
        [str(Path(__file__).resolve().parents[1] / "start.sh")],
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "START_LOG": str(log),
            "PORT": "8123",
        },
        check=False,
        capture_output=True,
    )
    commands = log.read_text().splitlines()
    assert commands[0] == "run alembic upgrade head"
    assert result.returncode == migration_exit
    if migration_exit:
        assert len(commands) == 1
    else:
        assert commands[1] == "run uvicorn backend.main:app --host 0.0.0.0 --port 8123"


def test_broken_migration_exits_nonzero_for_ci(tmp_path):
    import sys

    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "broken.py").write_text(
        "revision = 'broken'\ndown_revision = None\n"
        "def upgrade():\n    raise RuntimeError('broken migration sentinel')\n"
        "def downgrade():\n    pass\n"
    )
    (tmp_path / "env.py").write_text(
        "from alembic import context\n"
        "from sqlalchemy import URL, create_engine\n"
        "with create_engine(URL.create('sqlite')).connect() as conn:\n"
        "    context.configure(connection=conn)\n"
        "    with context.begin_transaction():\n"
        "        context.run_migrations()\n"
    )
    config = tmp_path / "alembic.ini"
    config.write_text(f"[alembic]\nscript_location = {tmp_path}\n")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(config), "upgrade", "head"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "broken migration sentinel" in result.stderr
