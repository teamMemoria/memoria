"""Build the local ABCD guideline snapshot used to check drafts (#19).

Usage (from backend/):
    uv run python scripts/build_reference_snapshot.py path/to/abcd/data/guidelines.json

guidelines.json is in https://github.com/asappresearch/abcd at commit
6b8700ce67c6b37b062dd7a60abc76d7ef832a97 (data/guidelines.json, MIT licence).
Every action text and sub-point becomes one reference passage, copied word for
word, with the subflows it applies to.

Every passage is written with ``approval.status: "unreviewed"``. Nothing in the
snapshot can verify a draft until a person has reviewed it and recorded that
(see data/references/README.md). The script never approves anything.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND / "data" / "references" / "abcd-guidelines.snapshot.json"
ABCD_COMMIT = "6b8700ce67c6b37b062dd7a60abc76d7ef832a97"

FLOWS = {
    "Product Defect": "product_defect",
    "Order Issue": "order_issue",
    "Account Access": "account_access",
    "Troubleshoot Site": "troubleshoot_site",
    "Manage Account": "manage_account",
    "Purchase Dispute": "purchase_dispute",
    "Shipping Issue": "shipping_issue",
    "Subscription Inquiry": "subscription_inquiry",
    "Single-Item Query": "single_item_query",
    "Storewide Query": "storewide_query",
}
# Guideline subflow titles whose snake_case form is not the ABCD subflow value.
SUBFLOW_OVERRIDES = {
    ("product_defect", "Initiate Refund"): {"subflow": "refund_initiate"},
    ("product_defect", "Update Refund"): {"subflow": "refund_update"},
    ("product_defect", "Refund Status"): {"subflow": "refund_status"},
    ("product_defect", "Return Due to Stain"): {"subflow": "return_stain"},
    ("product_defect", "Return Due to Color"): {"subflow": "return_color"},
    ("product_defect", "Return Due to Size"): {"subflow": "return_size"},
    ("account_access", "Reset Two-Factor Auth"): {"subflow": "reset_2fa"},
    ("troubleshoot_site", "Invalid Credit Card"): {"subflow": "credit_card"},
    ("troubleshoot_site", "Cart Not Updating"): {"subflow": "shopping_cart"},
    ("troubleshoot_site", "Search Not Working"): {"subflow": "search_results"},
    ("troubleshoot_site", "Website Too Slow"): {"subflow": "slow_speed"},
    ("purchase_dispute", "Out-of-Stock General"): {"subflow": "out_of_stock_general"},
    ("purchase_dispute", "Out-of-Stock One Item"): {"subflow": "out_of_stock_one_item"},
    ("shipping_issue", "Shipping Status"): {"subflow": "status"},
    ("shipping_issue", "Manage Shipping"): {"subflow": "manage"},
    ("shipping_issue", "Missing Item"): {"subflow": "missing"},
    ("shipping_issue", "Shipping Cost"): {"subflow": "cost"},
    ("single_item_query", "Boots FAQ"): {"subflow_prefix": "boots_"},
    ("single_item_query", "Shirt FAQ"): {"subflow_prefix": "shirt_"},
    ("single_item_query", "Jeans FAQ"): {"subflow_prefix": "jeans_"},
    ("single_item_query", "Jacket FAQ"): {"subflow_prefix": "jacket_"},
    ("storewide_query", "Pricing FAQ"): {"subflow_prefix": "pricing_"},
    ("storewide_query", "Membership FAQ"): {"subflow_prefix": "membership_"},
    ("storewide_query", "Timing FAQ"): {"subflow_prefix": "timing_"},
    ("storewide_query", "Policy FAQ"): {"subflow_prefix": "policy_"},
}


def snake(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    raw = Path(argv[0]).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    guidelines = json.loads(raw)
    version = f"abcd-guidelines@{ABCD_COMMIT[:12]}"
    passages = []
    for flow_title, flow in guidelines.items():
        flow_id = FLOWS[flow_title]
        for subflow_title, body in flow["subflows"].items():
            scope = {
                "flow": flow_id,
                **SUBFLOW_OVERRIDES.get(
                    (flow_id, subflow_title), {"subflow": snake(subflow_title)}
                ),
            }
            key = scope.get("subflow") or scope["subflow_prefix"].rstrip("_") + "_faq"
            for i, action in enumerate(body["actions"], 1):
                base = {
                    "scope": scope,
                    "guideline": {
                        "flow": flow_title,
                        "subflow": subflow_title,
                        "button": action["button"],
                        "type": action["type"],
                    },
                }
                passages.append(
                    {
                        "reference_id": f"abcd:{flow_id}/{key}#a{i}",
                        "text": action["text"],
                        "parent": None,
                        **base,
                    }
                )
                for j, sub in enumerate(action["subtext"], 1):
                    passages.append(
                        {
                            "reference_id": f"abcd:{flow_id}/{key}#a{i}.{j}",
                            "text": sub,
                            "parent": f"abcd:{flow_id}/{key}#a{i}",
                            **base,
                        }
                    )
            for i, line in enumerate(body.get("instructions", []), 1):
                passages.append(
                    {
                        "reference_id": f"abcd:{flow_id}/{key}#i{i}",
                        "text": line,
                        "parent": None,
                        "scope": scope,
                        "guideline": {
                            "flow": flow_title,
                            "subflow": subflow_title,
                            "button": None,
                            "type": "instruction",
                        },
                    }
                )
    snapshot = {
        "snapshot_id": version,
        "kind": "authoritative_reference_snapshot",
        "source": {
            "dataset": "ABCD",
            "url": "https://github.com/asappresearch/abcd",
            "commit": ABCD_COMMIT,
            "file": "data/guidelines.json",
            "sha256": digest,
            "licence": "MIT, (c) 2021 ASAPP Research. See data/abcd/LICENSE-ABCD.",
            "note": "ABCD guidance is not real company policy. Passages are copied verbatim.",
        },
        "review": {
            "status": "unreviewed",
            "reviewed_by": None,
            "reviewed_at": None,
            "note": "A person must review these passages before any of them can verify a draft.",
        },
        "passages": [
            {
                **p,
                "version": version,
                "approval": {
                    "status": "unreviewed",
                    "approved_by": None,
                    "approved_at": None,
                },
                "eligibility": {
                    "status": "eligible",
                    "valid_until": None,
                    "reason": None,
                },
            }
            for p in passages
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {len(passages)} passages to {OUT.relative_to(BACKEND)} (all unreviewed)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
