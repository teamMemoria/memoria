"""Load everything the demo needs, in order, with one command.

Usage (from backend/, with the database migrated):

    uv run setup-demo [CONVERSATIONS_DIR] [--organization default]

Runs the steps in backend/README.md one after another: import-conversations,
assign-topics, assign-synthetic-dates, seed-demo-profiles and seed-demo-policies, each with its
default settings. CONVERSATIONS_DIR is the curated/conversations directory of
the docs repo; it defaults to $MEMORIA_CONVERSATIONS_DIR, else to the docs repo
cloned next to this one.

Safe to re-run: every step updates existing rows in place, and the generated
dates use a fixed seed, so a second run leaves the same data.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from backend.data import (
    assign_synthetic_dates,
    assign_topics,
    import_conversations,
    seed_demo_profiles,
    seed_policies,
)

# <repo>/backend/src/backend/data/setup_demo.py -> the folder that holds <repo>.
DEFAULT_CONVERSATIONS_DIR = (
    Path(__file__).resolve().parents[5]
    / "uoft-ftli-2026-genesys-docs"
    / "curated"
    / "conversations"
)


def conversations_dir(argument: Path | None) -> Path:
    if argument is not None:
        return argument
    configured = os.environ.get("MEMORIA_CONVERSATIONS_DIR")
    return Path(configured) if configured else DEFAULT_CONVERSATIONS_DIR


async def run(path: Path, organization_slug: str) -> None:
    print("1/5 Importing conversations")
    await import_conversations.run(path, organization_slug)
    print("2/5 Assigning topics")
    await assign_topics.run(assign_topics.DEFAULT_MAPPING, organization_slug)
    print("3/5 Assigning synthetic dates")
    await assign_synthetic_dates.run(
        assign_synthetic_dates.DEFAULT_START,
        assign_synthetic_dates.DEFAULT_WEEKS,
        assign_synthetic_dates.DEFAULT_SEED,
        organization_slug,
    )
    print("4/5 Creating demo profiles")
    await seed_demo_profiles.run(organization_slug)
    print("5/5 Loading Layer 1 policy drafts")
    await seed_policies.run(organization_slug)
    print("Demo data is ready")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        help="the curated/conversations directory of the docs repo",
    )
    parser.add_argument(
        "--organization",
        default="default",
        help="organization slug to load into (default: default)",
    )
    args = parser.parse_args()
    path = conversations_dir(args.path)
    # Docker creates an empty folder when the docs repo is missing, so check for files.
    if not path.is_dir() or not any(path.glob("*.json")):
        sys.exit(
            f"Conversations not found at {path}. Clone "
            "uoft-ftli-2026-genesys-docs next to this repo, or pass its "
            "curated/conversations directory."
        )
    asyncio.run(run(path, args.organization))


if __name__ == "__main__":
    main()
