from __future__ import annotations

import pytest

from backend.services.knowledge.abcd import read_conversation
from backend.services.knowledge.extraction import redact_conversation
from backend.services.knowledge.privacy import Redactor

from .conftest import COMPANY

RECORD = {
    "customer_name": "joyce wu",
    "username": "joycewu5",
    "email": "joycewu5@email.com",
    "phone": "(319) 151-0701",
    "member_level": "gold",
    "address": {
        "street": "4146 circle drive",
        "city": "raleigh",
        "state": "tx",
        "zip_code": "62499",
        "full_address": "4146 circle drive  raleigh, tx 62499",
    },
    "order": {"order_id": "2643034282", "purchase_date": "2020-02-19"},
}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("my name is Joyce Wu", "my name is [CUSTOMER_NAME]"),
        ("Thanks Joyce!", "Thanks [CUSTOMER_NAME]!"),
        ("it's Joyse", "it's [CUSTOMER_NAME]"),  # misspelt by the customer
        ("joycewu5@email.com", "[EMAIL]"),
        ("my username is joycewu5", "my username is [USERNAME]"),
        ("call 319.151.0701", "call [PHONE]"),
        ("(319) 151-0701", "[PHONE]"),
        ("4146 Circle Drive  Raleigh, TX 62499", "[ADDRESS]"),
        ("order 2643034282 please", "order [ORDER_ID] please"),
        ("Account ID: QPDRTK8Q1R", "Account ID: [ACCOUNT_DETAIL]"),
        ("my account id is 78985", "my account id is [ACCOUNT_DETAIL]"),
        ("Your new password is 2qn8hu24nf5", "Your new password is [ACCOUNT_DETAIL]"),
        ("Your new promo code is PX1CE", "Your new promo code is [CODE]"),
        ("Card 4567-9900-2352-1109", "Card [CARD_NUMBER]"),
        ("bought on 3/4/2020", "bought on [DATE]"),
        ("I moved to 1908 Lexington Ave", "I moved to [ADDRESS]"),
    ],
)
def test_personal_details_become_typed_placeholders(text, expected):
    assert Redactor(RECORD).redact(text).text == expected


@pytest.mark.parametrize(
    "text",
    [
        "Gold members get unlimited returns.",
        "Promo codes are valid for 7 days.",
        "It costs $39.99 for items of 5 pounds or less.",
        "You can return it within 90 days of purchase.",
        "That one is mine, not hers.",  # close to "joyce"/"wu"? no: ordinary words stay
        "The 1st and 2nd items shipped.",
        "Two-factor authentication (2FA) can be reset.",
    ],
)
def test_useful_meaning_is_kept(text):
    assert Redactor(RECORD).redact(text).text == text


def test_redaction_is_idempotent_and_counted():
    redactor = Redactor(RECORD)
    once = redactor.redact("Joyce Wu, joycewu5@email.com, (319) 151-0701")
    assert once.counts == {"CUSTOMER_NAME": 1, "EMAIL": 1, "PHONE": 1}
    assert redactor.redact(once.text).text == once.text


def test_leak_check_finds_unredacted_values():
    redactor = Redactor(RECORD)
    assert set(redactor.leaks("hello joycewu5@email.com and 4146 circle drive")) >= {
        "EMAIL",
        "ADDRESS",
    }
    assert redactor.leaks("Gold members get unlimited returns.") == []


def test_no_customer_record_value_survives_in_any_abcd_turn(abcd_records):
    for record in abcd_records:
        redacted = redact_conversation(read_conversation(record, COMPANY))
        for turn_id, text in redacted.texts.items():
            assert redacted.redactor.leaks(text) == [], (turn_id, text)
