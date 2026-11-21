"""Plain-Python rules: notice parsing, the reason-code table and record consistency checks.

No LLM is used anywhere in this file.
"""
import re
from datetime import datetime


class NoticeError(ValueError):
    """The chargeback notice could not be parsed."""


# Reason-code table: what evidence each dispute reason requires.
REASON_CODES = {
    "GNR": {
        "label": "Goods or services not received",
        "required": [
            ("order_record", "Order record exists"),
            ("payment_record", "Payment record exists"),
            ("delivery_record", "Delivery record with status DELIVERED"),
            ("delivery_proof", "Proof of delivery (OTP or signature)"),
        ],
    },
    "UNAUTH": {
        "label": "Unauthorised transaction",
        "required": [
            ("order_record", "Order record exists"),
            ("payment_record", "Payment record exists"),
            ("auth_proof", "Payment authentication verified (UPI PIN or OTP)"),
            ("device_history", "Earlier successful order by the same customer on the same device"),
        ],
    },
}

_FIELDS = {
    "dispute_id": r"^Dispute ID:\s*(\S+)\s*$",
    "merchant_id": r"^Merchant ID:\s*(\S+)\s*$",
    "order_id": r"^Order ID:\s*(\S+)\s*$",
    "reason_code": r"^Reason Code:\s*(\S+)\s*$",
    "amount": r"^Disputed Amount:\s*INR\s*([\d,]+(?:\.\d+)?)\s*$",
    "raised_at": r"^Raised On:\s*(\S+)\s*$",
    "respond_by": r"^Respond By:\s*(\S+)\s*$",
}


def parse_notice(text: str) -> dict:
    """Extract the fields of a chargeback notice.

    Header fields are read only from the part BEFORE 'Customer Statement:', so
    nothing a customer writes can overwrite the reason code, amount or deadline.
    """
    if not text or "Customer Statement:" not in text:
        raise NoticeError("Notice has no 'Customer Statement:' section")
    header, statement = text.split("Customer Statement:", 1)
    parsed = {}
    for field, pattern in _FIELDS.items():
        match = re.search(pattern, header, flags=re.MULTILINE)
        if not match:
            raise NoticeError(f"Notice is missing the field '{field}'")
        parsed[field] = match.group(1)
    try:
        parsed["amount"] = float(parsed["amount"].replace(",", ""))
        datetime.fromisoformat(parsed["raised_at"])
        datetime.fromisoformat(parsed["respond_by"])
    except ValueError as exc:
        raise NoticeError(f"Notice has an unreadable amount or date: {exc}") from exc
    parsed["reason_code"] = parsed["reason_code"].upper()
    parsed["customer_statement"] = statement.strip()
    return parsed


def check_evidence(parsed: dict, bundle: dict) -> list[dict]:
    """Return one row per required evidence item: present or not, and which record backs it."""
    code = parsed["reason_code"]
    if code not in REASON_CODES:
        return [{"item": "supported_reason_code", "description": f"Reason code '{code}' is supported",
                 "present": False, "record_id": None}]

    order, payment, delivery = bundle.get("order"), bundle.get("payment"), bundle.get("delivery")
    history = bundle.get("history") or []
    found = {
        "order_record": (order is not None, order and order["order_id"]),
        "payment_record": (payment is not None, payment and payment["txn_id"]),
        "delivery_record": (bool(delivery and delivery["status"] == "DELIVERED"),
                            delivery and delivery["delivery_id"]),
        "delivery_proof": (bool(delivery and delivery["status"] == "DELIVERED"
                                and delivery["proof_type"] in ("OTP", "SIGNATURE")
                                and delivery["proof_ref"]),
                           delivery and delivery["delivery_id"]),
        "auth_proof": (bool(payment and payment["auth_verified"] and payment["auth_method"]),
                       payment and payment["txn_id"]),
        "device_history": (len(history) > 0, history[0]["order_id"] if history else None),
    }
    rows = []
    for item, description in REASON_CODES[code]["required"]:
        present, record_id = found[item]
        rows.append({"item": item, "description": description, "present": bool(present),
                     "record_id": record_id if present else None})
    return rows


def check_consistency(parsed: dict, bundle: dict) -> list[str]:
    """Return contradictions between the records and the dispute. Empty list = consistent."""
    problems = []
    order, payment, delivery = bundle.get("order"), bundle.get("payment"), bundle.get("delivery")
    amount = parsed["amount"]

    if order and abs(order["amount"] - amount) > 0.01:
        problems.append(f"Disputed amount {amount:.2f} does not match order amount "
                        f"{order['amount']:.2f} [{order['order_id']}]")
    if payment:
        if abs(payment["amount"] - amount) > 0.01:
            problems.append(f"Disputed amount {amount:.2f} does not match payment amount "
                            f"{payment['amount']:.2f} [{payment['txn_id']}]")
        if payment["status"] != "SUCCESS":
            problems.append(f"Payment status is {payment['status']}, not SUCCESS [{payment['txn_id']}]")

    if parsed["reason_code"] == "GNR" and delivery and delivery.get("delivered_at"):
        delivered = datetime.fromisoformat(delivery["delivered_at"])
        if payment and delivered < datetime.fromisoformat(payment["paid_at"]):
            problems.append(f"Delivery is dated before the payment [{delivery['delivery_id']}]")
        if delivered > datetime.fromisoformat(parsed["raised_at"]):
            problems.append("Delivery is dated after the dispute was raised, so the customer's "
                            f"claim was true when made [{delivery['delivery_id']}]")

    if parsed["reason_code"] == "UNAUTH" and order and payment:
        if order["device_id"] != payment["device_id"]:
            problems.append(f"Payment device {payment['device_id']} differs from order device "
                            f"{order['device_id']} [{payment['txn_id']}]")
    return problems
