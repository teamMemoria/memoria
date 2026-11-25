"""Score bounded pilot checks with existing template points and saved references."""

from collections.abc import Mapping

from ml.metrics.followup_task import VERSION as FOLLOWUP_VERSION
from ml.metrics.followup_task import binding, make_task, unresolved_rows
from ml.metrics.luna import TRANSCRIPT_METRICS, agreed_checks
from ml.metrics.prepare import digest, faq_question
from ml.metrics.score import MIDPOINT_VERSION, score_checks

from backend.entities.assessments import (
    CRITERION_IDS,
    RESULTS,
    AnalysisUnavailableError,
    CategoryResult,
    ParsedReport,
    ReportRejectedError,
    WeightProfile,
)
from backend.entities.draft_matches import faq_search, promo_days, promo_exchange
from backend.entities.extension import extension_refusal
from backend.entities.fulfilment import OUTCOME, REQUESTS, VALUE, recorded_outcomes
from backend.entities.policies import (
    EXTENSION_KEY,
    FAQ_KEY,
    GOLD_EXTENSION_KEY,
    PROMO_PREFIX,
)
from backend.entities.refund_amount import (
    REFUND_AMOUNT_CHECK,
    SUBSCRIPTION_PRICE_CHECK,
    subscription_refund_claims,
)
from backend.entities.score_policy import overall_for_profile
from backend.interface_adapters.call_checks import QUESTIONS, observed_workflow
from backend.interface_adapters.extension_checks import (
    EXTENSION_LIMITS,
    EXTENSION_QUESTIONS,
    GOLD_QUESTIONS,
    extension_checks,
    gold_checks,
    gold_extension,
)
from backend.interface_adapters.followup_checks import verified_followup
from backend.interface_adapters.fulfilment_checks import (
    fulfilment_request,
    fulfilment_workflow,
)
from backend.interface_adapters.guideline_checks import PUBLISHER_CHECKS, SCOPED_CHECKS
from backend.interface_adapters.policy_evidence import eligible_reference

EXPIRY_QUESTIONS = {
    "answer-support.facts": "Does approved guidance establish that standard promo codes expire?",
    "answer-support.values": "Does the stated expiry in days match the approved policy?",
}
RECORD_QUESTIONS = {
    OUTCOME: "Does the action record corroborate the Agent's claimed outcome?",
    VALUE: "Does the stated refund amount match the completed refund record?",
}


CHECK_SPLITS = {
    "procedure.actions": {
        "procedure.actions.return_method": "Does the update record the agreed return method?",
        "procedure.actions.refund_destination": "Does a matching record establish the requested bank payout?",
    },
    "answer-support.values": {
        SUBSCRIPTION_PRICE_CHECK: "Does an independent reference verify the quoted annual subscription price?",
        REFUND_AMOUNT_CHECK: "Does the refund action record verify the quoted refund amount?",
    },
}

FAQ_LIMIT = "Procedure score covers the FAQ search step only. Product selection, ordering and answer accuracy are outside this pilot."


def _combine_scoped_findings(findings):
    if len(findings) == 1:
        return findings[0]
    outcomes = {outcome for outcome, _, _ in findings}
    reasons = " ".join(dict.fromkeys(reason for _, reason, _ in findings))
    citations = []
    for _, _, evidence in findings:
        for citation in evidence:
            if citation not in citations:
                citations.append(citation)
    if len(outcomes) == 1:
        return findings[0][0], reasons, citations
    return (
        "unresolved",
        f"The applicable guideline checks disagree. {reasons}",
        citations,
    )


class TemplatePilot:
    def __init__(self, config: Mapping, *, luna=None, luna_followup=None):
        self.common = config["common"]
        self.templates = self.common["check_templates"]
        self.categories = {
            category["id"]: category for category in config["categories"]
        }
        self.weight_profiles = {
            name: WeightProfile(
                name, digest([name, category["weights"]]), dict(category["weights"])
            )
            for name, category in self.categories.items()
        }
        self.catalogue_version = config["version"].removeprefix("sha256:")
        self.luna = luna or {}
        self.luna_followup = luna_followup or {}

    def analyse(self, request):
        return self._assessment(request, *self._evaluate_local(request))

    def _evaluate_local(self, request):
        if request.canonical_evidence is None:
            raise AnalysisUnavailableError(
                "The pilot requires canonical ABCD training evidence."
            )
        match = promo_exchange(request.conversation["events"])
        if match is None:
            if evidence := extension_refusal(request.conversation["events"]):
                return self._extension_report(request, evidence)
            if evidence := gold_extension(request.conversation["events"]):
                return self._gold_report(request, evidence)
            if report := self._faq_report(request):
                return report
            return self._observed_report(request)
        question, answer, days = match
        eligible = []
        for reference in self._eligible(request):
            key = reference.get("draft_source_key") or ""
            verification = reference["verification"]
            verified_days = promo_days(verification.get("quote") or "")
            if verified_days is not None and key == PROMO_PREFIX + str(verified_days):
                eligible.append((reference, verified_days))

        def cite(turn):
            return self._conversation_citation(request, turn)

        conversation = [cite(question), cite(answer)]
        checks = {
            "completeness.direct_response": (
                "supported",
                "The answer directly addresses the requested expiry period.",
                conversation,
            ),
            "completeness.promises_next_steps": (
                "not-applicable",
                "This exchange contains no promise or action request.",
                conversation,
            ),
            "completeness.followups": (
                "not-applicable",
                "The complete exchange contains one question and one answer.",
                conversation,
            ),
            "answer-support.recorded_outcomes": (
                "not-applicable",
                "The answer states policy and does not claim a completed action.",
                conversation,
            ),
            "communication-style.clarity": (
                "supported",
                "The wording states a duration and its unit in a direct sentence.",
                [cite(answer)],
            ),
            "communication-style.consistency": (
                "not-applicable",
                "There is only one Agent statement to review.",
                [cite(answer)],
            ),
        }
        if len(eligible) == 1:
            ref, expected = eligible[0]
            # The stored entry wording and the independently verified quotation
            # must agree before its immutable approval version can be cited.
            evidence = [cite(answer), self._reference_citation(ref)]
            checks["answer-support.facts"] = (
                "supported",
                "The verified policy covers standard promo code expiry.",
                evidence,
            )
            checks["answer-support.values"] = (
                "supported" if days == expected else "breach",
                f"The Agent stated {days} days. The approved policy specifies {expected} days.",
                evidence,
            )
        else:
            for part in ("facts", "values"):
                checks[f"answer-support.{part}"] = (
                    "unresolved",
                    "A single eligible, independently verified expiry policy is required.",
                    [cite(answer)],
                )
        return self._evaluate_category(
            request, "pricing", "pricing-pilot-v4", checks, questions=EXPIRY_QUESTIONS
        )

    @staticmethod
    def _eligible(request):
        return (
            ref
            for ref in request.references
            if eligible_reference(ref, request.conversation["id"])
        )

    @staticmethod
    def _conversation_citation(request, turn):
        return {
            "kind": "conversation",
            "conversation_id": request.conversation["id"],
            "transcript_version": request.conversation["transcript_version"],
            "turn_id": turn["turn_id"],
            "event_kind": turn["kind"],
            "quote": turn["text"],
        }

    @staticmethod
    def _reference_citation(ref):
        return {
            "kind": "reference",
            "reference_id": ref["id"],
            "section_id": ref["section_id"],
            "reference_version": ref["version"],
            "quote": ref["text"],
        }

    def _cite_findings(self, request, findings, reference=None):
        source = [] if reference is None else [reference]
        return {
            rule: (
                outcome,
                explanation,
                [
                    *(self._conversation_citation(request, turn) for turn in turns),
                    *source,
                ],
            )
            for rule, (outcome, explanation, turns) in findings.items()
        }

    def _single_reference_citation(self, request, source_key):
        refs = [
            ref
            for ref in self._eligible(request)
            if ref["draft_source_key"] == source_key
        ]
        return self._reference_citation(refs[0]) if len(refs) == 1 else None

    def _faq_report(self, request):
        events = request.conversation["events"]
        lookup = faq_search(events)
        if (
            lookup is None
            or (questions := faq_question(events, lookup[0], lookup[2])) is None
        ):
            return None
        evidence = [
            self._conversation_citation(request, turn)
            for turn in [*questions, *lookup[:2]]
        ]
        if reference := self._single_reference_citation(request, FAQ_KEY):
            evidence.append(reference)
            finding = (
                "supported",
                "The action log records Search FAQ after the product question.",
                evidence,
            )
        else:
            finding = (
                "unresolved",
                "The FAQ step needs eligible, independently verified guidance.",
                evidence,
            )
        return self._evaluate_category(
            request,
            "product",
            "product-faq-pilot-v3",
            {"procedure.actions": finding},
            faq_only=True,
        )

    def _extension_citations(self, request, evidence, source_key):
        reference = self._single_reference_citation(request, source_key)
        turns = {
            key: self._conversation_citation(request, turn)
            for key, turn in evidence.items()
        }
        return turns, reference

    def _extension_report(self, request, evidence):
        turns, reference = self._extension_citations(request, evidence, EXTENSION_KEY)
        return self._evaluate_category(
            request,
            "subscription",
            "subscription-refusal-pilot-v3",
            extension_checks(turns, reference),
            questions=EXTENSION_QUESTIONS,
            limits=EXTENSION_LIMITS,
        )

    def _observed_report(self, request):
        events = request.conversation["events"]
        version = "observed-pilot-v1"
        if (observed := observed_workflow(events)) is None:
            if review := self._luna_entry(request):
                return self._evaluate_category(
                    request,
                    review["category"],
                    "luna-transcript-pilot-v1",
                    {},
                )
            categories = {
                category
                for key, (category, recognize) in SCOPED_CHECKS.items()
                if self._single_reference_citation(request, key) and recognize(events)
            }
            if len(categories) == 1:
                return self._evaluate_category(
                    request, categories.pop(), "scoped-guidelines-v1", {}
                )
            observed = fulfilment_workflow(events)
            if observed is None:
                raise AnalysisUnavailableError(
                    "No single supported request and response could be established."
                )
            version = "fulfilment-routing-v1"
        category, checks, limit = observed
        return self._evaluate_category(
            request,
            category,
            version,
            self._cite_findings(request, checks),
            questions=QUESTIONS,
            limits={"answer-support": limit},
        )

    def _gold_report(self, request, evidence):
        turns, reference = self._extension_citations(
            request, evidence, GOLD_EXTENSION_KEY
        )
        linked = {
            evidence[key]["turn_id"]
            for key in ("duration_question", "name_question")
            if key in evidence
        }
        extra_questions = any(
            turn["speaker"] == "customer"
            and "?" in turn["text"]
            and turn["turn_id"] > evidence["request"]["turn_id"]
            and turn["turn_id"] not in linked
            for turn in request.conversation["events"]
        )
        return self._evaluate_category(
            request,
            "subscription",
            "subscription-gold-pilot-v1",
            gold_checks(turns, reference, extra_questions),
            questions=GOLD_QUESTIONS,
            limits={"procedure": EXTENSION_LIMITS["procedure"]},
        )

    def _scoped_findings(self, request, category_id):
        findings = {}
        for key, (category, recognize) in (SCOPED_CHECKS | PUBLISHER_CHECKS).items():
            if category != category_id or not (
                reference := self._single_reference_citation(request, key)
            ):
                continue
            candidates = self._cite_findings(
                request, recognize(request.conversation["events"]), reference
            )
            for rule, finding in candidates.items():
                findings.setdefault(rule, []).append(finding)
        return {
            rule: _combine_scoped_findings(proposals)
            for rule, proposals in findings.items()
        }

    def _subscription_claim_findings(self, request):
        claims = subscription_refund_claims(request.conversation["events"])
        if claims is None:
            return {}
        price, refund, record = claims
        return {
            SUBSCRIPTION_PRICE_CHECK: (
                "unresolved",
                "The annual subscription price requires an independent price reference.",
                [self._conversation_citation(request, price)],
            ),
            REFUND_AMOUNT_CHECK: (
                "supported" if record is not None else "unresolved",
                "The quoted refund amount matches the completed refund entry."
                if record is not None
                else "A linked refund entry matching the quoted amount is required.",
                [self._conversation_citation(request, refund)]
                + (
                    [self._conversation_citation(request, record)]
                    if record is not None
                    else []
                ),
            ),
        }

    def _fulfilment_findings(self, request, category_id, checks):
        events = request.conversation["events"]
        anchor = fulfilment_request(events, category_id)
        if anchor is None:
            return {}
        observed = fulfilment_workflow(events)
        findings = {}
        if observed is not None and observed[0] == category_id:
            findings.update(observed[1])
        findings.update(
            {
                rule: (finding.outcome, finding.explanation, finding.turns)
                for rule, finding in recorded_outcomes(
                    events, category_id, anchor
                ).items()
            }
        )
        return self._cite_findings(
            request,
            {
                rule: finding
                for rule, finding in findings.items()
                if checks.get(rule, ("unresolved",))[0] == "unresolved"
            },
        )

    def _evaluate_category(
        self,
        request,
        category_id,
        version,
        checks,
        *,
        faq_only=False,
        questions=None,
        limits=None,
    ):
        category = self.categories[category_id]
        if (review := self._luna_entry(request)) and review["category"] == category_id:
            checks = self._add_luna_checks(request, category, checks, review)
            version += "+luna"
        scoped = {} if faq_only else self._scoped_findings(request, category_id)
        if scoped:
            checks = checks | {
                rule: finding
                for rule, finding in scoped.items()
                if checks.get(rule, ("unresolved",))[0] == "unresolved"
            }
            version += "+scoped-guidelines-v1"
            if "procedure.actions.refund_destination" in scoped:
                version += "+return-route-payout-v1"
        if (
            category_id in {"billing", "subscription"}
            and checks.get("answer-support.values", ("unresolved",))[0] == "unresolved"
            and (claims := self._subscription_claim_findings(request))
        ):
            checks = checks | claims
            version += "+subscription-refund-amount-v1"
        if category_id in REQUESTS and (
            findings := self._fulfilment_findings(request, category_id, checks)
        ):
            checks = checks | findings
            questions = (questions or {}) | {
                rule: RECORD_QUESTIONS[rule]
                for rule in findings
                if rule in RECORD_QUESTIONS
            }
            version += "+fulfilment-evidence-v1"
        limits = limits or {}

        def category_rows(outcomes):
            return [
                self._category(
                    name, outcomes, category, faq_only, questions, limits.get(name)
                )
                for name in CRITERION_IDS
            ]

        rows = category_rows(checks)
        if followup := self._followup_findings(request, category, rows, scoped):
            rows = category_rows(checks | followup)
            version += "+" + FOLLOWUP_VERSION
        return category_id, version, rows

    def _assessment(self, request, category_id, version, rows):
        profile = self.weight_profiles[category_id]
        return {
            "schema_version": "assessment-v1",
            "processing_status": "completed",
            "conversation_id": request.conversation["id"],
            "transcript_version": request.conversation["transcript_version"],
            "evaluation_form_version": request.evaluation_form_version,
            "as_of": request.as_of,
            "versions": {
                "rules": f"{version}:{self.catalogue_version}",
                "scoring": MIDPOINT_VERSION,
                "weight_profile": profile.version,
            },
            "human_review": None,
            "approval": None,
            "categories": rows,
            "overall": overall_for_profile(
                profile,
                {r["category"]: r["scoring"]["score"] for r in rows},
                {r["category"]: r["scoring"]["coverage"] for r in rows},
            ),
        }

    def followup_task(self, request, report):
        """Prepare the optional model pass without introducing network I/O here."""
        rows = unresolved_rows(report["categories"])
        category = self.categories[report["overall"]["profile_id"]]
        references = list(self._eligible(request))
        payload, schema = make_task(request, self.common, category, rows, references)
        return binding(request, category, rows, references), payload, schema

    def _followup_findings(self, request, category, categories, local_policy_checks):
        if not self.luna_followup:
            return {}
        source = request.canonical_evidence["conversations"][0]
        entry = self.luna_followup.get(source["id"])
        if not isinstance(entry, dict):
            return {}
        rows = unresolved_rows(categories)
        references = list(self._eligible(request))
        if entry.get("binding") != binding(request, category, rows, references):
            return {}
        return verified_followup(
            request,
            rows,
            entry.get("result"),
            references,
            local_policy_checks,
            lambda turn: self._conversation_citation(request, turn),
        )

    def _luna_entry(self, request):
        if not self.luna:
            return None
        canonical = request.canonical_evidence["conversations"][0]
        review = self.luna.get(canonical["id"])
        if (
            review
            and review["evidence_version"] == canonical["transcript_version"]
            and review["category"] in self.categories
            and review["category"] != "unclear"
            and review["verified_checks"]
        ):
            return review
        return None

    def _add_luna_checks(self, request, category, checks, review):
        # Only add agreed transcript judgments that passed the pilot evidence review.
        # Never change a local judgment or a Procedure / Answer support check.
        rules = {
            item["template"]
            for metric, data in category["metrics"].items()
            if metric in TRANSCRIPT_METRICS
            for item in data["checks"]
        }
        events = request.conversation["events"]
        consensus = agreed_checks(*review["passes"], events, rules)
        by_id = {turn["turn_id"]: turn for turn in events}
        combined = dict(checks)
        for rule, reason in review["verified_checks"].items():
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
                raise ValueError("Invalid reviewed Luna explanation")
            if rule not in consensus:
                raise ValueError("Reviewed Luna check does not have agreeing evidence")
            if rule not in checks:
                row = consensus[rule]
                combined[rule] = (
                    row["outcome"],
                    reason,
                    [
                        self._conversation_citation(request, by_id[number])
                        for number in row["turns"]
                    ],
                )
        return combined

    def _category(self, name, outcomes, category, faq_only, questions, limit):
        checks = []
        for item in category["metrics"][name]["checks"]:
            part = item["template"]
            if faq_only and name == "procedure" and part != "procedure.actions":
                continue
            question = (
                "Did the Agent open Search FAQ for the product question?"
                if faq_only and name == "procedure"
                else (questions or {}).get(part, self.templates[part]["question"])
            )
            parts = CHECK_SPLITS.get(part, {})
            if parts and parts.keys() <= outcomes.keys():
                maximum = item["points"] / len(parts)
                checks.extend(
                    self._scored_check(
                        f"{category['id']}.{rule}", rule, wording, maximum, outcomes
                    )
                    for rule, wording in parts.items()
                )
            else:
                checks.append(
                    self._scored_check(
                        item["id"], part, question, item["points"], outcomes
                    )
                )
        applicable = [c for c in checks if c["outcome"] != "not-applicable"]
        breaches = [c for c in applicable if c["outcome"] == "breach"]
        unknown = [c for c in applicable if c["outcome"] == "unresolved"]
        totals = score_checks(checks)
        verdict = (
            "needs-review"
            if breaches
            else "cannot-assess"
            if unknown or not applicable
            else "meets-criteria"
        )
        notes = list(dict.fromkeys(c["explanation"] for c in unknown))
        if not applicable:
            notes.append("There are no applicable checks in this metric.")
        summary = " ".join(c["explanation"] for c in breaches) or (
            " ".join(notes) if notes else "The applicable pilot checks are supported."
        )
        if faq_only and name == "procedure":
            notes.append(FAQ_LIMIT)
        if limit:
            notes.append(limit)
        return {
            "category": name,
            "status": "completed",
            "result": {
                "category": name,
                "result": verdict,
                "explanation": summary,
                "limitations": notes,
                "findings": [
                    {k: c[k] for k in ("explanation", "advice", "citations")}
                    for c in breaches
                ],
            },
            "scoring": {
                **totals,
                "checks": checks,
                "limitations": notes,
                "processing_error": None,
                "interpretation_limits": category["interpretation_limits"],
                "inventory_complete": True,
            },
        }

    @staticmethod
    def _scored_check(check_id, rule, question, maximum, outcomes):
        outcome, explanation, citations = outcomes.get(
            rule,
            (
                "unresolved",
                "This check is outside the current pilot's evidence coverage.",
                [],
            ),
        )
        return {
            "id": check_id,
            "rule_id": rule,
            "requirement": question,
            "outcome": outcome,
            "maximum": maximum,
            "earned": maximum
            if outcome == "supported"
            else 0
            if outcome == "breach"
            else None,
            "explanation": explanation,
            "advice": (
                "Check the completed refund record before stating the amount."
                if question == RECORD_QUESTIONS[VALUE]
                else "Check and state the approved expiry period."
            )
            if outcome == "breach"
            else "",
            "citations": citations,
            "critical": False,
        }

    def parse(self, request, report):
        # Recompute the bounded policy instead of trusting supplied points or findings.
        if report != self.analyse(request):
            raise ReportRejectedError(
                "invalid-template-report", "Report differs from the configured pilot."
            )
        categories = {}
        for row in report["categories"]:
            result = row["result"]
            categories[row["category"]] = CategoryResult(
                RESULTS[result["result"]],
                result["explanation"],
                " ".join(f["advice"] for f in result["findings"]) or None,
                [],
                [],
            )
        return ParsedReport(
            categories,
            None,
            digest(report["versions"]),
            report,
            weight_profile=self.weight_profiles[report["overall"]["profile_id"]],
        )
