"""Executable dependency rules: no exceptions in the business core."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from tests.architecture_rules import violations

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend/src/backend"


def imports(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""


def test_business_dependencies_point_inward():
    for layer in ("entities", "use_cases"):
        for path in (BACKEND / layer).rglob("*.py"):
            module = "backend." + ".".join(
                path.relative_to(BACKEND).with_suffix("").parts
            )
            assert not violations(path.read_text(), module), path


@pytest.mark.parametrize(
    "source",
    [
        "from backend.frameworks.database import models",
        "from ..frameworks.database import models",
        "from .. import frameworks",
        "from backend.schemas.reviews import DecisionInput",
        "from pathlib import Path; Path('x').read_text()",
        "import os as system; system.getenv('SETTING')",
        "from datetime import datetime as clock; clock.now()",
        "import datetime as d; d.date.today()",
        "from time import monotonic as tick; tick()",
        "from builtins import open as read; read('x')",
        "import importlib as loader; loader.import_module('backend.models')",
        "__import__('backend.models')",
    ],
)
def test_guard_rejects_boundary_violations(source):
    assert violations(source, "backend.entities.example")


def test_guard_allows_pure_value_operations():
    assert not violations(
        "from datetime import datetime; x = datetime(2026, 1, 1)\n"
        "from urllib.parse import urlparse; urlparse('https://example.test')\n"
        "from .results import FindingResult\nrequests = []; requests.append(1)",
        "backend.entities.example",
    )


def test_pure_core_imports_without_database_http_or_ml():
    code = r"""
import importlib, importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'sqlalchemy', 'fastapi', 'pydantic', 'ml'}:
            raise RuntimeError(fullname)
sys.meta_path.insert(0, Block())
for name in ['entities.assessments', 'entities.scoring', 'entities.knowledge',
             'entities.knowledge_import', 'entities.inferred_knowledge', 'use_cases.assessments', 'use_cases.assessment_runs', 'use_cases.record_review_decision', 'use_cases.knowledge', 'use_cases.inferred_knowledge']:
    importlib.import_module('backend.' + name)
from backend.use_cases.record_review_decision import ReviewDecisionInput, validate_review_decision
try:
    validate_review_decision(ReviewDecisionInput('corrected', None, 'Reason', 'Feedback'))
except ValueError:
    pass
else:
    raise AssertionError('Domain correction rule did not run')
"""
    subprocess.run([sys.executable, "-c", code], cwd=ROOT / "backend", check=True)


def test_startup_without_optional_engines():
    code = r"""
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ml', 'openai', 'ollama', 'groq'}:
            raise RuntimeError(fullname)
sys.meta_path.insert(0, Block())
from backend.main import create_app
from backend.core.config import Settings
app = create_app(settings=Settings(app_env='test'))
assert app.openapi()['paths']['/api/manager/knowledge/drafts/{draft_id}/approve']
"""
    subprocess.run([sys.executable, "-c", code], cwd=ROOT / "backend", check=True)


def test_ml_helpers_have_no_io_dependencies():
    for path in [
        *(ROOT / "ml").glob("*.py"),
        ROOT / "ml/metrics/score.py",
    ]:
        if path.name.startswith("test_") or path.name == "generate_narration.py":
            continue
        module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
        assert not violations(path.read_text(), module, layer="ml"), path


def test_frontend_presenters_do_not_load_or_score():
    for path in (ROOT / "frontend/src/features").glob("*/presenter.ts"):
        source = path.read_text()
        assert "from 'react'" not in source
        assert "fetch(" not in source
        assert "httpApi" not in source


def test_presenters_have_no_persistence_dependency():
    paths = [
        *(BACKEND / "interface_adapters/presenters").glob("*.py"),
        BACKEND / "interface_adapters/records.py",
    ]
    for path in paths:
        assert not [
            name
            for name in imports(path)
            if name.startswith(
                ("sqlalchemy", "backend.frameworks", "backend.models", "backend.db")
            )
        ], path
    code = r"""
import importlib, importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'sqlalchemy':
            raise RuntimeError(fullname)
sys.meta_path.insert(0, Block())
for name in ['assessments', 'reviews', 'knowledge_review']:
    importlib.import_module('backend.interface_adapters.presenters.' + name)
"""
    subprocess.run([sys.executable, "-c", code], cwd=ROOT / "backend", check=True)


def test_analysis_http_uses_application_boundary():
    path = BACKEND / "frameworks/http/analysis.py"
    assert not [
        name
        for name in imports(path)
        if name.startswith(
            (
                "backend.frameworks.data_access",
                "backend.frameworks.database",
                "backend.models",
            )
        )
    ]
    assert "AssessmentRunsInputBoundary" in path.read_text()


def test_review_http_uses_interactor_and_sql_does_not_construct_it():
    route = BACKEND / "frameworks/http/reviews.py"
    repository = BACKEND / "frameworks/data_access/reviews.py"
    assert "RecordReviewDecision().execute" in route.read_text()
    assert "decision_repository" in route.read_text()
    assert "RecordReviewDecision" not in repository.read_text()
