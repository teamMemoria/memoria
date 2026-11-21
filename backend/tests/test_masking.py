"""Masking tests. All names, numbers and addresses here are made up."""

import re

import pytest

from backend.data.masking import known_details, mask_text, mask_transcript

ABCD_RECORD = {
    "customer_name": "jordan testperson",
    "username": "jordantest123",
    "email": "jordantest123@email.com",
    "phone": "(555) 010-4477",
    "member_level": "gold",
    "address": {
        "street": "1234 maple lane",
        "city": "springfield",
        "state": "ca",
        "zip_code": "90210",
        "full_address": "1234 maple lane  springfield, ca 90210",
    },
    "order": {
        "order_id": "0123456789",
        "payment_method": "credit card",
        "products": [{"brand": "acme", "product_type": "jacket", "amount": 74}],
    },
}

ABCD_TRANSCRIPT = [
    "Hello and welcome to AcmeCorp, how can I help you today?",
    "Hi, I need to change the address on my account.",
    "Sure. Could I have your full name?",
    "Jordan Testperson",
    "Account has been pulled up for Jordan Testperson.",
    "Thanks Jordan. What's the new address?",
    "1234 Maple Lane, Springfield CA 90210",
    "And your phone number, email and username?",
    "555 010 4477, jordantest123@email.com, username is jordantest123",
    "Details of jordantest123@email.com have been entered.",
    "My order ID is 0123456789 and account id is QWERTYUIOP",
    "I've refunded $74.00 to your card. Refunds take 5 to 7 business days.",
]

HVB_RECORD = {
    "customer_name": "Casey Example",
    "captured_by_agent": {
        "company name": "Brightwater Power",
        "money amount": "212",
        "company address": "99 River Rd, Harper Valley, Ca, 55501",
        "phone": "5550199123",
    },
}

HVB_TRANSCRIPT = [
    "hello this is harper valley national bank my name is sam how can i help you today",
    "hi my name is casey example i would like to pay a bill",
    "who is the bill to",
    "brightwater power at ninety nine river road",
    "the amount is two hundred and twelve dollars",
    "and the last four digits of your phone number",
    "nine one two three",
    (
        "okay we will send your payment to brightwater power in the amount of "
        "two hundred and twelve dollars"
    ),
    "it will arrive in three to five business days",
]


def leaked(masked: list[str], record) -> list[str]:
    text = "\n".join(masked).lower()
    found = []
    for value, _ in known_details(record):
        if re.search(r"(?<!\w)" + re.escape(value.lower()) + r"(?!\w)", text):
            found.append(value)
    return found


def test_abcd_transcript_has_no_customer_details_left():
    masked = mask_transcript(ABCD_TRANSCRIPT, ABCD_RECORD)
    joined = "\n".join(masked)

    assert leaked(masked, ABCD_RECORD) == []
    assert "5550104477" not in re.sub(r"\D", "", joined)
    assert "QWERTYUIOP" not in joined
    assert "$74" not in joined
    assert masked[4] == "Account has been pulled up for [NAME]."
    assert masked[5] == "Thanks [NAME]. What's the new address?"
    assert masked[8] == "[PHONE], [EMAIL], username is [USERNAME]"


def test_hvb_transcript_has_no_customer_details_left():
    masked = mask_transcript(HVB_TRANSCRIPT, HVB_RECORD)
    joined = "\n".join(masked)

    assert leaked(masked, HVB_RECORD) == []
    assert "two hundred and twelve dollars" not in joined
    assert "nine one two three" not in joined
    assert masked[1] == "hi my name is [NAME] i would like to pay a bill"
    assert masked[3] == "[NAME] at [ADDRESS]"
    assert masked[4] == "the amount is [AMOUNT]"


def test_bank_name_and_general_answers_are_untouched():
    masked = mask_transcript(HVB_TRANSCRIPT, HVB_RECORD)
    assert masked[0].startswith("hello this is harper valley national bank")
    assert masked[-1] == "it will arrive in three to five business days"
    assert mask_transcript(ABCD_TRANSCRIPT, ABCD_RECORD)[-1].endswith(
        "Refunds take 5 to 7 business days."
    )


@pytest.mark.parametrize(
    "text",
    [
        "New cards arrive in 5 to 7 business days.",
        "It usually takes 2-3 business days for items to appear.",
        "Your order will be shipped within the next 24 hours.",
        "Gold members get unlimited returns; silver members get 3 per year.",
        "The branch is open nine to five monday to friday.",
        "Please wait 7 days before contacting us again.",
        "You can reset your password from the login page.",
        "The annual sale runs during the last week of January.",
        "It's a one way trip, take the second road on the left.",
    ],
)
def test_general_answers_are_left_alone(text):
    assert mask_text(text) == text
    assert mask_text(text, ABCD_RECORD) == text


@pytest.mark.parametrize(
    "text, expected",
    [
        ("email me at someone.else@example.org", "email me at [EMAIL]"),
        ("i'm someone@emailcom", "i'm [EMAIL]"),
        ("call (555) 123-4567 or 555.123.4567", "call [PHONE] or [PHONE]"),
        ("I live at 42 Old Mill Road now", "I live at [ADDRESS] now"),
        ("at twelve oak tree lane", "at [ADDRESS]"),
        ("that will be $1,250.50", "that will be [AMOUNT]"),
        ("about a hundred and five dollars", "about [AMOUNT]"),
        ("twenty dollars and fifty cents", "[AMOUNT]"),
        ("my account number is 88812345", "my account number is [NUMBER]"),
        ("it's one two three four five", "it's [NUMBER]"),
        ("my name is alex", "my name is [NAME]"),
        ("my name is alex and i need help", "my name is [NAME] and i need help"),
        ("my username is someone_99", "my username is [USERNAME]"),
    ],
)
def test_patterns_mask_details_without_a_record(text, expected):
    assert mask_text(text) == expected


def test_non_identifying_record_fields_are_not_masked():
    values = {v for v, _ in known_details(ABCD_RECORD)}
    assert "gold" not in values
    assert "credit card" not in values
    assert "ca" not in values
    # Written addresses keep only their street and zip parts.
    assert "Harper Valley" not in {v for v, _ in known_details(HVB_RECORD)}


def test_empty_record_is_fine():
    assert known_details(None) == []
    assert mask_transcript(["hello"], None) == ["hello"]
