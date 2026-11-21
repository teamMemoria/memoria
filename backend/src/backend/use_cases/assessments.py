"""Assessment execution policy. The caller owns scheduling and transactions."""

from typing import Protocol

from backend.entities.assessments import AnalysisRequest, ParsedReport


class AssessmentInputBoundary(Protocol):
    async def execute(self, request: AnalysisRequest) -> ParsedReport: ...


class AssessmentInteractor:
    def __init__(self, generate, parse, validate):
        self.generate = generate
        self.parse = parse
        self.validate = validate

    async def execute(self, request: AnalysisRequest) -> ParsedReport:
        report = await self.generate(request)
        parsed = self.parse(request, report)
        if parsed.assessment_report is not None:
            self.validate(request, parsed)
        return parsed
