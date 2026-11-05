"""Fictional fixture records for local development and tests.

Written in the same camelCase JSON the API returns, so they read like real
responses. IDs that also appear in the frontend's development data (Alex Morgan,
C1042, RP-01) are kept identical so both sides line up when they are connected.

Coverage:
- C1042  ready call with a procedure finding (copied from the frontend dev data)
- C1043  ready call with non-contiguous turn numbers and a Manager decision
- C1044  transcript unavailable, so every criterion is cannot-assess
- C1045  still processing
- C1046  listed, but its call record is unavailable (provider returns None)
- C2001  another agent in the same organization
- C3001  another organization
- Knowledge entries in every status, one approved entry Alex cannot see,
  and one approved entry with unknown dates
"""

NORTHWIND = "org-northwind"
HARBOR = "org-harbor"

ALEX = "agent-alex-morgan"
SAM = "agent-sam-rivera"
RILEY = "agent-riley-chen"

VIEWERS = {
    NORTHWIND: [
        {"id": ALEX, "displayName": "Alex Morgan", "role": "agent"},
        {"id": SAM, "displayName": "Sam Rivera", "role": "agent"},
        {"id": "manager-maya-chen", "displayName": "Maya Chen", "role": "manager"},
    ],
    HARBOR: [
        {"id": RILEY, "displayName": "Riley Chen", "role": "agent"},
    ],
}

CONVERSATIONS = {
    NORTHWIND: [
        {
            "id": "C1042",
            "topic": "Refund request",
            "agentId": ALEX,
            "agentName": "Alex Morgan",
            "date": "2026-10-08",
            "automatedResult": "needs-review",
            "reviewStatus": "feedback-ready",
        },
        {
            "id": "C1043",
            "topic": "Delivery address change",
            "agentId": ALEX,
            "agentName": "Alex Morgan",
            "date": "2026-10-10",
            "automatedResult": "meets-criteria",
            "reviewStatus": "review-complete",
        },
        {
            "id": "C1044",
            "topic": "Warranty question",
            "agentId": ALEX,
            "agentName": "Alex Morgan",
            "date": "2026-10-12",
            "automatedResult": "cannot-assess",
            "reviewStatus": "feedback-ready",
        },
        {
            "id": "C1045",
            "topic": "Order status",
            "agentId": ALEX,
            "agentName": "Alex Morgan",
            "date": "2026-10-14",
            "automatedResult": "processing",
            "reviewStatus": None,
        },
        {
            "id": "C1046",
            "topic": "Gift card balance",
            "agentId": ALEX,
            "agentName": "Alex Morgan",
            "date": "2026-10-03",
            "automatedResult": "meets-criteria",
            "reviewStatus": "feedback-ready",
        },
        {
            "id": "C2001",
            "topic": "Exchange request",
            "agentId": SAM,
            "agentName": "Sam Rivera",
            "date": "2026-10-09",
            "automatedResult": "needs-review",
            "reviewStatus": "review-requested",
        },
    ],
    HARBOR: [
        {
            "id": "C3001",
            "topic": "Subscription cancellation",
            "agentId": RILEY,
            "agentName": "Riley Chen",
            "date": "2026-10-11",
            "automatedResult": "processing",
            "reviewStatus": None,
        },
    ],
}

REFUND_PROCEDURE = {
    "id": "RP-01",
    "title": "Refund handling",
    "topic": "Refunds",
    "kind": "procedure",
    "status": "approved",
    "availableToAgentIds": [ALEX, SAM],
    "version": "v1",
    "approvedAt": "2026-10-01",
    "approvedBy": None,
    "effectiveAt": "2026-10-01",
    "lastConfirmedAt": None,
    "owner": "Customer Support Operations",
    "source": {"title": "Refund handling procedure RP-01 v1", "url": None},
    "paragraphs": ["Applies to damaged-item refund requests, including C1042."],
    "steps": [
        {"number": 1, "text": "Identify the customer."},
        {
            "number": 2,
            "text": "Verify the order, customer match and refund eligibility before offering a refund.",
        },
        {
            "number": 3,
            "text": "For an eligible purchase paid by card, explain that the refund may return to "
            "the original payment card. Obtain the customer's agreement.",
        },
        {
            "number": 4,
            "text": "Submit the refund and confirm the method and next step.",
        },
    ],
}

ADDRESS_CHANGE = {
    "id": "KB-02",
    "title": "Changing a delivery address",
    "topic": "Delivery",
    "kind": "knowledge",
    "status": "approved",
    "availableToAgentIds": [ALEX],
    "version": "v3",
    # Imported without approval history: these stay unknown instead of being guessed.
    "approvedAt": None,
    "approvedBy": None,
    "effectiveAt": None,
    "lastConfirmedAt": None,
    "owner": None,
    "source": None,
    "paragraphs": [
        "An address can be changed until the order is marked as shipped.",
        "Confirm the full new address back to the customer before saving it.",
    ],
    "steps": [],
}


def _knowledge(entry_id, title, status, agents=(ALEX,)):
    return {
        "id": entry_id,
        "title": title,
        "topic": "Warranty",
        "kind": "knowledge",
        "status": status,
        "availableToAgentIds": list(agents),
        "version": "v1",
        "approvedAt": None,
        "approvedBy": None,
        "effectiveAt": None,
        "lastConfirmedAt": None,
        "owner": "Customer Support Operations",
        "source": {"title": f"{entry_id} draft notes", "url": None},
        "paragraphs": [f"{title}."],
        "steps": [],
    }


KNOWLEDGE = {
    NORTHWIND: [
        REFUND_PROCEDURE,
        ADDRESS_CHANGE,
        _knowledge("KB-03", "Warranty length for outerwear", "draft"),
        _knowledge("KB-04", "Warranty claims without a receipt", "disputed"),
        _knowledge("KB-05", "Legacy warranty extension offer", "stale"),
        _knowledge("KB-06", "Automatic warranty replacement", "rejected"),
        _knowledge("KB-07", "Exchange window for footwear", "approved", agents=(SAM,)),
    ],
    HARBOR: [
        _knowledge(
            "KB-90", "Cancelling an annual subscription", "approved", agents=(RILEY,)
        ),
    ],
}

_C1042_TURNS = [
    (1, "Agent", "Thanks for calling. How can I help?", "0:00"),
    (2, "Customer", "I need help with a jacket I received.", "0:15"),
    (3, "Agent", "Of course. Let me pull up your details.", "0:32"),
    (4, "Agent", "Could I have your full name?", "1:18"),
    (5, "Customer", "Jordan Lee.", "1:28"),
    (6, "Agent", "Thank you, Jordan.", "1:35"),
    (7, "Customer", "The jacket arrived damaged.", "1:48"),
    (8, "Agent", "I can offer you a refund.", "2:02"),
    (9, "Customer", "Can it go back to my card?", "2:15"),
    (10, "Agent", "Yes, I can arrange that.", "2:27"),
    (11, "Agent", "May I have your order number to verify the purchase?", "2:41"),
    (12, "Customer", "The order number is J4821.", "3:00"),
    (13, "Agent", "I've verified the purchase. The jacket is eligible.", "3:25"),
    (14, "Customer", "Please refund the original card.", "3:40"),
    (
        15,
        "Agent",
        "Your refund has been submitted to the original payment card. I'll email the confirmation.",
        "4:05",
    ),
    (16, "Customer", "Yes, that answers all my questions. Thank you.", "4:32"),
]

# Turns 3-4 and 7-8 were removed upstream (hold music and a dropped segment).
# The original numbers are kept so evidence still points at the right place.
_C1043_TURNS = [
    (1, "Agent", "Hi, thanks for calling Northwind. What can I do for you?", "0:00"),
    (
        2,
        "Customer",
        "I moved last week and need to change my delivery address.",
        "0:09",
    ),
    (
        5,
        "Agent",
        "I can help with that. The order hasn't shipped yet, so we can still update it.",
        "1:40",
    ),
    (6, "Customer", "Great, it's 42 Maple Street, Unit 3.", "1:52"),
    (9, "Agent", "Thanks. That's 42 Maple Street, Unit 3. Is that right?", "2:30"),
    (10, "Customer", "Yes, that's right.", "2:36"),
    (11, "Agent", "Done. You'll get an email confirming the new address.", "2:45"),
]


def _turns(rows):
    return [
        {"number": number, "speaker": speaker, "text": text, "time": time}
        for number, speaker, text, time in rows
    ]


def _criterion(
    criterion_id, title, result, explanation, turns, finding_id=None, reference_id=None
):
    return {
        "id": criterion_id,
        "title": title,
        "result": result,
        "explanation": explanation,
        "evidenceTurnNumbers": turns,
        "findingId": finding_id,
        "referenceId": reference_id,
    }


CALLS = {
    NORTHWIND: [
        {
            "id": "C1042",
            "agentId": ALEX,
            "agentName": "Alex Morgan",
            "topic": "Damaged jacket refund",
            "date": "2026-10-08",
            "duration": "4:32",
            "summary": "Refund submitted to the original payment card.",
            "status": "ready",
            "criteria": [
                _criterion(
                    "procedure",
                    "Procedure",
                    "needs-review",
                    "The refund was offered at turn 8. Purchase verification followed at turn 13. "
                    "RP-01 v1, step 2, requires verification before a refund offer.",
                    [8, 13],
                    finding_id="procedure-order",
                    reference_id="RP-01",
                ),
                _criterion(
                    "answer-support",
                    "Answer support",
                    "meets-criteria",
                    "The original-card refund agrees with RP-01 v1, step 3. The customer requests "
                    "this method at turn 9; the agent confirms submission at turn 15.",
                    [9, 15],
                    reference_id="RP-01",
                ),
                _criterion(
                    "completeness",
                    "Completeness",
                    "meets-criteria",
                    "The conversation addresses the damaged jacket, refund eligibility, payment "
                    "method and confirmation. At turn 16, the customer says their questions were answered.",
                    [7, 9, 13, 15, 16],
                ),
                _criterion(
                    "communication-style",
                    "Communication style",
                    "meets-criteria",
                    "The agent uses a polite request at turn 4, thanks Jordan at turn 6, and explains "
                    "the refund outcome at turn 15. Text only. This assessment does not measure vocal tone.",
                    [4, 6, 15],
                ),
            ],
            "findings": [
                {
                    "id": "procedure-order",
                    "title": "Refund offered before purchase verification.",
                    "criterionId": "procedure",
                    "explanation": "The refund was offered at turn 8. Purchase verification followed "
                    "at turn 13. RP-01 v1, step 2, requires verification before a refund offer.",
                    "suggestion": "Verify the purchase before offering a refund.",
                    "evidenceTurnNumbers": [8, 10, 11, 13],
                    "referenceId": "RP-01",
                    "referenceStep": 2,
                    "procedureSteps": [
                        {
                            "label": "Identify customer",
                            "status": "observed",
                            "turnNumbers": [4],
                            "note": None,
                        },
                        {
                            "label": "Verify purchase",
                            "status": "observed",
                            "turnNumbers": [13],
                            "note": "After offer",
                        },
                        {
                            "label": "Offer refund",
                            "status": "observed",
                            "turnNumbers": [8],
                            "note": None,
                        },
                    ],
                }
            ],
            "transcript": {
                "complete": True,
                "turns": _turns(_C1042_TURNS),
                "unavailableReason": None,
            },
            "references": [REFUND_PROCEDURE],
            "decision": None,
        },
        {
            "id": "C1043",
            "agentId": ALEX,
            "agentName": "Alex Morgan",
            "topic": "Delivery address change",
            "date": "2026-10-10",
            "duration": "2:51",
            "summary": "Delivery address updated before shipping.",
            "status": "ready",
            "criteria": [
                _criterion(
                    "procedure",
                    "Procedure",
                    "meets-criteria",
                    "The agent checks the order has not shipped at turn 5 and reads the address back at turn 9.",
                    [5, 9],
                    reference_id="KB-02",
                ),
                _criterion(
                    "answer-support",
                    "Answer support",
                    "meets-criteria",
                    "The statement at turn 5 agrees with KB-02 v3.",
                    [5],
                    reference_id="KB-02",
                ),
                _criterion(
                    "completeness",
                    "Completeness",
                    "meets-criteria",
                    "The address is confirmed at turn 10 and the follow-up email is explained at turn 11.",
                    [10, 11],
                ),
                _criterion(
                    "communication-style",
                    "Communication style",
                    "meets-criteria",
                    "The agent greets the customer at turn 1 and confirms the outcome clearly at turn 11.",
                    [1, 11],
                ),
            ],
            "findings": [],
            "transcript": {
                "complete": False,
                "turns": _turns(_C1043_TURNS),
                "unavailableReason": None,
            },
            "references": [ADDRESS_CHANGE],
            "decision": {
                "outcome": "confirmed",
                "reason": "The address was read back before saving.",
                "feedback": "Good confirmation of the new address.",
                "managerName": "Maya Chen",
                "decidedAt": "2026-10-13T15:20:00Z",
            },
        },
        {
            "id": "C1044",
            "agentId": ALEX,
            "agentName": "Alex Morgan",
            "topic": "Warranty question",
            "date": "2026-10-12",
            "duration": "6:10",
            "summary": "Transcript unavailable.",
            "status": "ready",
            "criteria": [
                _criterion(
                    criterion_id,
                    title,
                    "cannot-assess",
                    "The transcript for this call is unavailable, so this criterion cannot be assessed.",
                    [],
                )
                for criterion_id, title in [
                    ("procedure", "Procedure"),
                    ("answer-support", "Answer support"),
                    ("completeness", "Completeness"),
                    ("communication-style", "Communication style"),
                ]
            ],
            "findings": [],
            "transcript": None,
            "references": [],
            "decision": None,
        },
        {
            "id": "C1045",
            "agentId": ALEX,
            "agentName": "Alex Morgan",
            "topic": "Order status",
            "date": "2026-10-14",
            "duration": "3:05",
            "summary": "",
            "status": "processing",
            "criteria": [],
            "findings": [],
            "transcript": None,
            "references": [],
            "decision": None,
        },
        # C1046 is intentionally missing: it appears in the list but its call record is unavailable.
        {
            "id": "C2001",
            "agentId": SAM,
            "agentName": "Sam Rivera",
            "topic": "Exchange request",
            "date": "2026-10-09",
            "duration": "1:12",
            "summary": "Exchange offered before checking the order.",
            "status": "ready",
            "criteria": [
                _criterion(
                    "procedure",
                    "Procedure",
                    "needs-review",
                    "The exchange is offered at turn 2 before the order is checked.",
                    [2],
                ),
                _criterion(
                    "answer-support",
                    "Answer support",
                    "cannot-assess",
                    "No reference applies.",
                    [],
                ),
                _criterion(
                    "completeness",
                    "Completeness",
                    "meets-criteria",
                    "Next steps given at turn 3.",
                    [3],
                ),
                _criterion(
                    "communication-style",
                    "Communication style",
                    "meets-criteria",
                    "Polite throughout.",
                    [1, 3],
                ),
            ],
            "findings": [],
            "transcript": {
                "complete": True,
                "turns": _turns(
                    [
                        (1, "Agent", "Hello, how can I help?", "0:00"),
                        (2, "Agent", "I can exchange those shoes for you.", "0:20"),
                        (3, "Agent", "You'll receive a return label by email.", "0:58"),
                    ]
                ),
                "unavailableReason": None,
            },
            "references": [],
            "decision": None,
        },
    ],
    HARBOR: [
        {
            "id": "C3001",
            "agentId": RILEY,
            "agentName": "Riley Chen",
            "topic": "Subscription cancellation",
            "date": "2026-10-11",
            "duration": "2:00",
            "summary": "Subscription cancelled.",
            "status": "processing",
            "criteria": [],
            "findings": [],
            "transcript": None,
            "references": [],
            "decision": None,
        },
    ],
}
