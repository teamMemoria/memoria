"""Fail the CI gate before attempting an ambiguous migration graph."""

from alembic.config import Config
from alembic.script import ScriptDirectory


def require_single_head(config: Config) -> str:
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError(
            f"Expected exactly one Alembic head, found {len(heads)}: {heads}"
        )
    return heads[0]


if __name__ == "__main__":
    print(require_single_head(Config("alembic.ini")))
