"""When the Layer 2 pilot, and with it auto-approval, is switched on."""

import pytest

from backend.core.config import Settings


@pytest.mark.parametrize(
    ("app_env", "public_demo", "pilot", "enabled"),
    [
        ("development", False, True, True),
        ("production", True, True, True),
        ("production", False, True, False),
        ("production", True, False, False),
    ],
)
def test_pilot_runs_locally_and_in_the_public_demo_only(
    app_env, public_demo, pilot, enabled
):
    settings = Settings(
        app_env=app_env, public_demo=public_demo, layer2_template_pilot=pilot
    )
    assert settings.layer2_pilot_enabled is enabled
