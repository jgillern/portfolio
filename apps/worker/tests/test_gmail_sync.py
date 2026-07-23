import json

import pytest
from pydantic import ValidationError

from portfolio_worker.gmail_sync import parse_rules


def test_gmail_rules_require_label_and_allowed_sender() -> None:
    rules = parse_rules(
        json.dumps(
            [
                {
                    "connector": "GMAIL_PATRIA",
                    "query": "label:broker-patria from:synthetic@example.invalid",
                    "broker_code": "PATRIA",
                    "account_ref": "patria-standard",
                }
            ]
        )
    )
    assert rules[0].broker_code == "PATRIA"


@pytest.mark.parametrize(
    "query",
    [
        "label:broker-patria",
        "from:synthetic@example.invalid",
        "is:unread",
    ],
)
def test_gmail_rules_reject_unbounded_queries(query: str) -> None:
    payload = json.dumps(
        [
            {
                "connector": "GMAIL_PATRIA",
                "query": query,
                "broker_code": "PATRIA",
                "account_ref": "patria-standard",
            }
        ]
    )
    with pytest.raises((ValueError, ValidationError)):
        parse_rules(payload)
