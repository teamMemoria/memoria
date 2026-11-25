"""Compose the opt-in pilot with the normal import and analysis services."""

import json
from pathlib import Path

from ml.metrics.followup_task import VERSION as FOLLOWUP_VERSION
from ml.metrics.luna import VERSION
from ml.metrics.prepare import (
    catalogue,
    category_entries,
    expand_category,
    expand_common,
)
from ml.metrics.score import MIDPOINT_VERSION, midpoint_percentage

from backend.entities.score_policy import PercentagePolicy
from backend.frameworks.data_access.analysis import AnalysisService
from backend.frameworks.data_access.draft_setup import pilot_knowledge_import
from backend.interface_adapters.policy_review import VERSION as POLICY_VERSION
from backend.interface_adapters.policy_review import PolicyScoring
from backend.interface_adapters.scorer import TemplatePilot


def pilot_services(sessions, settings):
    folder = Path(__file__).resolve().parents[5] / "ml" / "metric_categories"
    common = expand_common(json.loads((folder / "common.json").read_text()))
    catalog = json.loads((folder / "catalog.json").read_text())
    categories = []
    for item in category_entries(catalog):
        if item["file"] != item["id"] + ".json":
            raise ValueError("Invalid category catalogue path")
        category = json.loads((folder / item["file"]).read_text())
        if category["id"] != item["id"]:
            raise ValueError("Category catalogue ID differs from its template")
        categories.append(
            expand_category(common, catalog["category_defaults"], category)
        )
    config = catalogue(common, categories)
    pilot = TemplatePilot(
        config,
        luna=_load_review(settings.layer2_luna_review, config["version"], VERSION),
        luna_followup=_load_review(
            settings.layer2_luna_followup, config["version"], FOLLOWUP_VERSION
        ),
    )
    if settings.layer2_policy_assessments:
        pilot = PolicyScoring(
            pilot,
            _load_review(
                settings.layer2_policy_assessments, config["version"], POLICY_VERSION
            ),
        )
    return (
        AnalysisService(
            sessions,
            adapter=pilot,
            report_parser=pilot.parse,
            include_knowledge_provenance=True,
            percentage_policy=PercentagePolicy(MIDPOINT_VERSION, midpoint_percentage),
        ),
        pilot_knowledge_import(sessions, settings),
    )


def _load_review(path, configuration, prompt_version):
    if not path:
        return {}
    review = json.loads(Path(path).read_text())
    if (
        review.get("configuration") != configuration
        or review.get("prompt_version") != prompt_version
        or not isinstance(review.get("cases"), dict)
    ):
        raise ValueError("Luna review is incompatible with this template configuration")
    return review["cases"]
