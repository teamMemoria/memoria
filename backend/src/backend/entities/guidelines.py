"""Exact, reviewable source bindings for the scoped ABCD pilot."""

from dataclasses import dataclass

GUIDELINE_URL = (
    "https://github.com/asappresearch/abcd/blob/"
    "6b8700ce67c6b37b062dd7a60abc76d7ef832a97/data/guidelines.json"
)


@dataclass(frozen=True)
class Guideline:
    title: str
    question: str
    answer: str
    quote: str


SHIPPING_FEE = "layer2-abc-shipping-fee-v1"
OVERNIGHT = "layer2-abc-overnight-v1"
RETURN_COLOUR = "layer2-abc-return-colour-v1"
RETURN_SIZE = "layer2-abc-return-size-v1"
CART = "layer2-abc-cart-v1"
PRICE = "layer2-abc-price-yesterday-v1"
PROMO_AGE = "layer2-abc-promo-typical-age-v1"
GOLD_RETURN_TERMS = (
    "Gold members: > Gold members get unlimited returns\n"
    "Since the customer will print out a shipping label for the return, you need their full address.  You can give this explanation if the customer asks why you need the address.\n"
    "Options include: 'By Mail', 'In Store', or 'Drop off Center'"
)
GOLD_RETURN_UPDATE = (
    GOLD_RETURN_TERMS
    + "\nFill in the form with one of these three values and submit to [Update Order]"
)

GUIDELINES = {
    SHIPPING_FEE: Guideline(
        "Shipping fee waiver or partial refund",
        "How does the order's shipping status affect a shipping-fee request?",
        "For a shipping-fee request, look up the account, collect purchase details, "
        "and check shipping status. At Order Received or In Transit, offer to waive "
        "the shipping fee and record the waiver. At Out for Delivery or Delivered, "
        "offer a partial shipping refund of $8.",
        (
            "Start by confirming that their purchase is valid with [Validate Purchase]:\n"
            "Ask the customer for the shipping status\n"
            "If the status is 'Order Received' or  'In Transit', then offer to waive the fee on their shipment\n"
            "Enter 'waive fee' in the input form\n"
            "Click on [Update Order]\n"
            "Alternatively, if the status is 'Out for Delivery' or 'Delivered', then the best you can do is to give them part of the shipping fee back.\n"
            "Standard shipping is $8.00, so enter '8' into the box\n"
            "Then click on [Offer Refund]"
        ),
    ),
    OVERNIGHT: Guideline(
        "Overnight shipping upgrade",
        "When can a customer upgrade an order to overnight shipping?",
        "For an overnight upgrade, collect the customer's name, account ID and order ID, then ask for shipping status. Order Received can proceed. In Transit, Out for Delivery and Delivered are too late. Gold has the fee waived; ask Guest, Bronze or Silver to approve a $20 card charge, then enter tomorrow and update the eligible order.",
        (
            "Start by looking up the order using the [Verify Identity] fields.\n"
            "If the item is 'In Transit', 'Out for Delivery', or 'Delivered' then it is too late\n"
            "Guest, Bronze or Silver members: > Ask them if they can charge $20 to the credit card on their account\n"
            "Enter 'tomorrow' and then select [Update Order]"
        ),
    ),
    RETURN_COLOUR: Guideline(
        "Return due to colour",
        "What applies when a customer requests a return for the wrong colour?",
        "For a wrong-colour return, collect name or account ID and purchase identifiers. Confirm the tier; Gold has unlimited returns for this workflow. Collect the full label address and record the chosen mail, store or drop-off method.",
        "Get Full Name or Account ID for [Pull up Account]\n"
        "Confirm that their purchase is valid with [Validate Purchase]\n"
        + GOLD_RETURN_UPDATE,
    ),
    RETURN_SIZE: Guideline(
        "Return due to size",
        "What applies when a customer requests a return because of fit?",
        "For a wrong-size return, confirm the tier. Gold has unlimited returns for this workflow. Collect the full label address and record the chosen mail, store or drop-off method.",
        GOLD_RETURN_UPDATE,
    ),
    CART: Guideline(
        "Cart not updating",
        "What troubleshooting options apply to a cart that fails to update?",
        "If the cart is not updating, refresh and re-add the item or sign out and back in. The troubleshooting options have no mandatory order and the matching UI actions are recorded separately.",
        (
            "The customer is trying to place an item in their shopping cart, but the cart is not updating.  Choose actions in any order you want.\n"
            "Instruct the customer to refresh the page and add the item again.\n"
            "Instruct the customer to log out of their account and log back in."
        ),
    ),
    PRICE: Guideline(
        "Price increase since yesterday",
        "What should an Agent do when yesterday’s price was lower?",
        "For a price dispute where yesterday's price was lower, record the reason and explain that prices can change dynamically. If the customer keeps asking, generate and share a promo code.",
        (
            "The customer is calling in to call about a bad price.   The customer will give the reason yesterday’s price was lower.\n"
            "Either 'competitor' or 'yesterday'\n"
            "For example, Our pricing algorithms will often dynamically change the price of an item.\n"
            "If the customer keeps pushing, offer them a discount using [Promo Code]\n"
            "Generate the code and share that with them"
        ),
    ),
    PROMO_AGE: Guideline(
        "Typical promo-code duration",
        "What is the typical duration when a promo code is rejected?",
        "Typically promotions only last 7 days. This does not establish the expiry of an individual code or its replacement eligibility.",
        "Typically promotions only last 7 days so check if the code was issued a long time ago.   That might be the reason it doesn’t work.",
    ),
    "layer2-abc-initial-refund-method-v1": Guideline(
        "Initial refund methods",
        "What information is needed for each initial refund method?",
        "For an initial refund, collect the full address for a gift card or paper check. "
        "Collect the account ID for an account credit or credit-card refund.",
        "If the customer chose gift card or paper check then enter the full address\n"
        "If the customer chose add value or credit card then enter the account ID",
    ),
    "layer2-abc-update-refund-total-v1": Guideline(
        "Adding an item to a refund",
        "How is the amount calculated when an item is added to an existing refund?",
        "Ask for the price of the added item. The new total is the previous refund plus the added item's price.",
        "Ask for the price of the product from the customer\n"
        "The total refund is the amount of their previous refund plus their current one. > ie. if their old amount is $100 and their new item is $30, then the total is '130'",
    ),
    "layer2-abc-refund-status-escalation-v1": Guideline(
        "Refund status escalation",
        "What can the Agent do when a customer disagrees with an existing refund status?",
        "When the customer is unhappy with the existing refund status and wants it changed, notify the Manager and explain the escalation.",
        "If the customer is not satisfied with your answer, and would like to change their refund\n"
        "If they do not like the status: > Enter 'manager' into [Notify Internal Team] > Explain that you have escalated the issue to the manager",
    ),
    "layer2-abc-stained-item-gold-return-v1": Guideline(
        "Gold returns for a stained item",
        "Can a Gold member return a stained item, and what method can they choose?",
        "Gold members have unlimited returns in the stained-item workflow. For an eligible return, collect the full label address and allow mail, store or drop-off.",
        GOLD_RETURN_TERMS,
    ),
    "layer2-abc-site-search-troubleshooting-v1": Guideline(
        "Site search troubleshooting",
        "What troubleshooting options can the Agent suggest when site search fails?",
        "If site search is failing, the Agent can suggest signing out and back in or clearing browser cookies.",
        "Instruct the customer to log out of their account and log back in.\n"
        "Tell the customer to try clearing out their cookies.",
    ),
}
