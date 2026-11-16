"""Run status and command wiring use neutral contracts, including HTTP callers."""

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx

from backend.core.config import Settings
from backend.frameworks.data_access.analysis import AnalysisRunsAdapter
from backend.main import create_app
from backend.providers import create_fixture_providers
from backend.use_cases.assessment_runs import (
    AssessmentRunsInteractor,
    RunOutput,
    StartOutput,
)


class Repository:
    def __init__(self):
        self.values, self.executed, self.args = [], [], None

    async def runs(self, organization_id, conversation_id):
        return self.values

    async def start(
        self, organization_id, conversation_id, *, requested_by, retry=False
    ):
        self.args = (organization_id, conversation_id, requested_by, retry)
        value = RunOutput(
            1,
            1,
            "queued",
            None,
            None,
            requested_by,
            datetime(2026, 1, 1, tzinfo=UTC),
            None,
            None,
        )
        self.values = [value]
        return StartOutput(value, True)

    async def execute(self, run_id):
        self.executed.append(run_id)


async def test_run_interactor_reports_status_without_database():
    repository = Repository()
    interactor = AssessmentRunsInteractor(repository)
    assert (await interactor.status("org", "call")).status == "not-started"
    start, status = await interactor.start(
        "org", "call", requested_by="manager", retry=True
    )
    assert repository.args == ("org", "call", "manager", True)
    assert status.runs == [start.run] and status.status == "queued"
    await interactor.execute(start.run.id)
    assert repository.executed == [1]


async def test_adapter_detaches_legacy_records():
    record = SimpleNamespace(
        id=1,
        attempt=2,
        status=SimpleNamespace(value="queued"),
        error_code=None,
        error_message=None,
        requested_by=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        started_at=None,
        finished_at=None,
    )

    class Service:
        async def runs(self, *args):
            return [record]

    result = (await AnalysisRunsAdapter(Service()).runs("org", "call"))[0]
    record.attempt = 99
    assert type(result) is RunOutput and result.attempt == 2


async def test_http_uses_injected_input_boundary():
    app = create_app(
        providers=create_fixture_providers(), settings=Settings(app_env="test")
    )
    repository = Repository()
    app.state.assessment_runs = AssessmentRunsInteractor(repository)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client,
    ):
        response = await client.post(
            "/api/manager/conversations/C1/analysis",
            headers={"X-Dev-User": "manager-maya-chen"},
            json={"retry": True},
        )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert repository.executed == [1]
