"""JSON-schema tool definitions sent to the LLM. Handlers live in merchant_tools / distributor_tools."""


def _tool(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or []}}}


_SUPPLIER = {"type": "string", "description": "Supplier name as the user said it (fuzzy matched)"}
_MONTH = {"type": "string", "description": "Month as YYYY-MM"}

MERCHANT_SPECS = [
    _tool("get_dues", "What the merchant owes suppliers, grouped by supplier, with due dates and a total.",
          {"period": {"type": "string", "enum": ["today", "week", "month"]}, "supplier": _SUPPLIER}),
    _tool("get_supplier_ledger", "A supplier's bills, payments, credit notes, balance and open issues.",
          {"supplier": _SUPPLIER}, ["supplier"]),
    _tool("list_alerts", "Open alerts: duplicates, mismatches, missing credit notes, GSTIN risks.",
          {"type": {"type": "string", "description": "Optional alert type filter"}}),
    _tool("explain_invoice", "Validation results and payment status of one bill, in plain words.",
          {"invoice_id": {"type": "integer"}}, ["invoice_id"]),
    _tool("log_cash_payment", "Record a cash payment to a supplier. Creates a pending entry the user must confirm.",
          {"supplier": _SUPPLIER, "amount": {"type": "number", "description": "Amount in INR"},
           "date": {"type": "string", "description": "YYYY-MM-DD, defaults to today"}}, ["supplier", "amount"]),
    _tool("request_credit_note", "Ask a supplier for a credit note against a bill.",
          {"invoice_id": {"type": "integer"}, "amount": {"type": "number"}}, ["invoice_id", "amount"]),
    _tool("forecast_cash", "14-day cash forecast with the day and size of any shortfall.",
          {"days": {"type": "integer", "description": "Horizon in days, default 14"}}),
    _tool("set_cash_balance", "Record how much cash or bank balance the merchant has right now, so the cash forecast starts from it.",
          {"amount": {"type": "number", "description": "Current balance in INR"}}, ["amount"]),
    _tool("get_hisaab_score", "The merchant's Hisaab Score (300-900) and the top reasons behind it."),
    _tool("get_credit_offer", "Whether the merchant is eligible for a working-capital credit offer, and its size.",
          {"purpose": {"type": "string"}}),
    _tool("draft_payment", "Prepare a payment to a supplier. It is NOT sent until the user confirms.",
          {"supplier": _SUPPLIER, "amount": {"type": "number"}, "source": {"type": "string", "enum": ["bank", "credit"]}},
          ["supplier", "amount"]),
    _tool("ims_suggestions", "GST IMS accept/reject/pending suggestions for a month (regular-GST merchants).", {"month": _MONTH}),
    _tool("export_purchase_register", "Create the purchase register CSV for the CA for a month.", {"month": _MONTH}),
]

DISTRIBUTOR_SPECS = [
    _tool("get_receivables", "Retailers who owe the distributor: outstanding, overdue days, reliability, suggested limit.",
          {"limit": {"type": "integer", "description": "Max retailers to return, default 10"}}),
    _tool("draft_reminders", "Draft polite payment reminders for overdue retailers. Does not send them.",
          {"retailer": {"type": "string", "description": "Optional single retailer name"},
           "language": {"type": "string", "enum": ["hi", "en"]}}),
    _tool("match_settlements", "Re-match UPI receipts to invoices (MDR shown separately) and list the latest receipts."),
    _tool("suggest_credit_limit", "Suggested credit limit and reasoning for one retailer.",
          {"retailer": {"type": "string", "description": "Retailer name"}}, ["retailer"]),
]
