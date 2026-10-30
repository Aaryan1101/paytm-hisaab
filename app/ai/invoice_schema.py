"""The field list we ask Sarvam Document AI to extract (JSON-schema, descriptions guide the model)."""

LINE_ITEM = {
    "type": "object",
    "properties": {
        "description": {"type": "string", "description": "Item name as printed on the bill row"},
        "hsn": {"type": "string", "description": "HSN or SAC code of the item, digits only"},
        "qty": {"type": "number", "description": "Quantity of the item"},
        "unit": {"type": "string", "description": "Unit of measure such as kg, pkt, pcs, box"},
        "rate": {"type": "number", "description": "Price per unit before tax in INR"},
        "taxable_value": {"type": "number", "description": "Line amount before GST in INR"},
        "gst_rate": {"type": "number", "description": "Total GST rate for the item as a percent, e.g. 5 or 18"},
        "cgst": {"type": "number", "description": "CGST amount in INR for this line"},
        "sgst": {"type": "number", "description": "SGST amount in INR for this line"},
        "igst": {"type": "number", "description": "IGST amount in INR for this line"},
    },
}

INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "document_title": {"type": "string", "description": "Title printed at the top, e.g. Tax Invoice, Bill, Credit Note"},
        "is_handwritten": {"type": "boolean", "description": "True if the bill is handwritten or an informal paper slip"},
        "supplier_name": {"type": "string", "description": "Name of the seller / shop that issued the bill"},
        "supplier_gstin": {"type": "string", "description": "Seller GSTIN, 15 characters, exactly as printed"},
        "buyer_gstin": {"type": "string", "description": "Buyer GSTIN, 15 characters, exactly as printed"},
        "invoice_no": {"type": "string", "description": "Invoice or bill number"},
        "invoice_date": {"type": "string", "description": "Invoice date exactly as printed"},
        "due_date": {"type": "string", "description": "Payment due date exactly as printed, if any"},
        "place_of_supply": {"type": "string", "description": "Place of supply or state, if printed"},
        "line_items": {"type": "array", "description": "One entry per item row on the bill", "items": LINE_ITEM},
        "taxable_total": {"type": "number", "description": "Total taxable value before GST in INR"},
        "tax_total": {"type": "number", "description": "Total GST amount in INR"},
        "round_off": {"type": "number", "description": "Round-off adjustment in INR, negative if deducted"},
        "grand_total": {"type": "number", "description": "Final payable total in INR"},
    },
}
