"""Demo profile definitions and naming rules; no database or CLI dependencies."""

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROFILES_FILE = Path(__file__).with_name("demo_profiles.toml")
# Every demo profile ID starts with this, so demo users are easy to tell apart
# from real ones.
DEMO_PREFIX = "demo-"


def profile_display_name(external_id: str, name: str) -> str:
    """Keep legacy demo metadata out of names, without changing identity IDs."""
    if not external_id.startswith(DEMO_PREFIX):
        return name
    name = name.removesuffix(" (demo)")
    return "Manager" if name == "Demo Manager" else name


@dataclass(frozen=True)
class DemoAgent:
    id: str
    name: str
    conversations: tuple[str, ...]


@dataclass(frozen=True)
class DemoProfiles:
    dataset: str
    split: str
    manager_id: str
    manager_name: str
    agents: tuple[DemoAgent, ...]


def load_profiles(path: Path = PROFILES_FILE) -> DemoProfiles:
    """Read and check the profiles file. Fails loudly on any mistake."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    agents = tuple(
        DemoAgent(
            a["id"], profile_display_name(a["id"], a["name"]), tuple(a["conversations"])
        )
        for a in data["agents"]
    )
    profiles = DemoProfiles(
        dataset=data["dataset"],
        split=data["split"],
        manager_id=data["manager"]["id"],
        manager_name=profile_display_name(
            data["manager"]["id"], data["manager"]["name"]
        ),
        agents=agents,
    )

    ids = [profiles.manager_id, *(a.id for a in agents)]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path.name}: profile IDs must be unique")
    if not all(i.startswith(DEMO_PREFIX) for i in ids):
        raise ValueError(f"{path.name}: profile IDs must start with {DEMO_PREFIX!r}")
    listed = [c for a in agents for c in a.conversations]
    if len(set(listed)) != len(listed):
        raise ValueError(f"{path.name}: a conversation is listed for two profiles")
    return profiles


@lru_cache
def demo_agent_ids() -> dict[tuple[str, str], str]:
    """(dataset, original conversation ID) -> demo profile ID."""
    profiles = load_profiles()
    return {
        (profiles.dataset, conversation): agent.id
        for agent in profiles.agents
        for conversation in agent.conversations
    }
