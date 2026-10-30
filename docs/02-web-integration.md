# Web integration guide (distributor dashboard) + full API reference

For the Next.js / TypeScript dashboard used by the distributor (**Sharma Traders**, merchant id `3`). Part 1 is how to
integrate; Part 2 is the reference for **every endpoint** in the backend (43 operations), because the same API also powers
the Android app and WhatsApp.

Prerequisite: the backend is running ([setup guide](01-backend-setup.md)). Live, interactive docs are at `/docs`.

---

# Part 1: Integrating the dashboard

## 1.1 Connect

```ts
// .env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
```

- **No login.** The demo is single-tenant per persona: use the distributor id in the path (`/distributors/3/...`).
- **CORS:** the backend only accepts browser calls from origins listed in `CORS_ORIGINS` (default `http://localhost:3000`).
  If you serve the dashboard elsewhere, add that origin there and restart the backend.
- **Typed client:** generate types from the contract instead of hand-writing them:
  ```bash
  npx openapi-typescript http://localhost:8000/openapi.json -o src/api/schema.d.ts
  ```

## 1.2 Conventions

| Topic | Rule |
|---|---|
| Format | JSON in, JSON out. Two endpoints take `multipart/form-data` (`/invoices/ingest`, `/agent/voice`) |
| Money | Plain numbers in **INR** (`42300.0`). Format on the client: `new Intl.NumberFormat("en-IN", {style:"currency", currency:"INR", maximumFractionDigits:0})` → `₹42,300` |
| Dates | `YYYY-MM-DD`. Timestamps are ISO-8601 **without** a timezone (server local time) |
| "Today" | Pinned to `2026-10-31` in the demo, so "overdue" and "this week" are relative to that date |
| Language | Messages come in pairs: `message_en` and `message_hi` (Hinglish). Pick one per user |
| IDs | Integers. Never assume they are contiguous |

### Errors

Business errors always have this shape:

```json
{ "error": "not_found", "message": "Merchant not found" }
```

| HTTP | `error` | Meaning |
|---|---|---|
| 403 | `consent_required` | Credit offer requested before the user gave data consent |
| 404 | `not_found` | Unknown id, or the object belongs to another merchant |
| 409 | `not_applicable` | Feature does not apply to this merchant (IMS for a composition-scheme retailer) |
| 422 | `invalid` | Rule violated (e.g. amount exceeds credit limit, answering a query twice) |
| 422 | `unreadable` | A bill photo could not be read (`message` lists the missing fields) |
| 422 | – | **Request validation** (wrong type / missing field) uses FastAPI's own shape: `{"detail":[{"loc":[...],"msg":"..."}]}` |

Handle both 422 shapes: check for `body.error` first, then `body.detail`.

### A typed fetch wrapper

```ts
const BASE = process.env.NEXT_PUBLIC_API_URL!;

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: init?.json ? { "Content-Type": "application/json", ...init?.headers } : init?.headers,
    body: init?.json ? JSON.stringify(init.json) : init?.body,
  });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const code = body.error ?? "validation";
    const msg = body.message ?? body.detail?.[0]?.msg ?? res.statusText;
    throw new ApiError(res.status, code, msg);
  }
  return body as T;
}
```

## 1.3 Pages → endpoints

| Dashboard page | Calls | Notes |
|---|---|---|
| **Receivables** | `GET /distributors/3/receivables` | Already sorted: most overdue first. Show `reliability` as a badge, `suggested_limit`, and `reason_en`/`reason_hi` as the tooltip |
| **Retailer detail** | `GET /distributors/3/retailers/{id}` + `GET /distributors/3/settlements` (filter by `payer_name`) | There is no per-retailer invoice list endpoint yet: show the summary row and that retailer's receipts |
| **Settlements** | `GET /distributors/3/settlements` | Show `gross`, `mdr` (own column), `net`, and `matched[]`. `status` is `matched` or `unmatched` |
| **Reminders** | `POST /distributors/3/reminders` with `send:false` to preview, then again with `send:true` and the chosen `retailer_ids` | Drafts are AI-written in Hindi/English with the tone picked from days overdue (`friendly`, `polite`, `firm`, `final`) |
| **New invoice** | `POST /distributors/3/invoices` | Lands in the retailer's ledger and WhatsApp immediately, already confirmed (matching becomes exact) |
| **Assistant panel** | `POST /agent/chat` with `merchant_id: 3` | Ask "kaun kitna dena hai?" etc. Render `text`; optionally show `tool_calls` for transparency |
| **Live payment banner** | poll `GET /merchants/3/events?after_id=` every 2–3 s | Each event is a soundbox-style line, e.g. `Rs 31,500 prapt hue` |
| **Demo panel** (hidden) | `POST /demo/simulate-payment`, `POST /demo/reset` | Fires the live payment on stage |

### Receivables table

```ts
type Receivable = {
  retailer_id: number; name: string;
  outstanding: number; overdue_amount: number; days_overdue: number;
  reliability: number;          // 0-100
  suggested_limit: number;      // INR
  reason_en: string; reason_hi: string;
};

const rows = await api<Receivable[]>("/distributors/3/receivables");
// Suggested badge colours: >=70 green, 40-70 amber, <40 red.
```

### Settlement matching after MDR (the S6/S10 demo)

```ts
type Settlement = {
  collection_id: number; received_at: string; payer_name: string;
  gross: number; mdr: number; net: number;
  matched: { invoice_no: string; amount: number }[];
  status: "matched" | "unmatched";
};
// Display: "₹31,500 received · ₹126 MDR · ₹31,374 net · cleared ST-2308 + ST-2309"
```

MDR is 0.4% on UPI payments above ₹2,000, capped at ₹300. **Match on `gross`**, show `mdr` separately.

### Live-payment demo flow

```ts
let lastEvent = 0;
setInterval(async () => {
  const ev = await api<{ id: number; text: string }[]>(`/merchants/3/events?after_id=${lastEvent}`);
  ev.forEach(e => { toast(e.text); lastEvent = Math.max(lastEvent, e.id); });
  if (ev.length) refetchSettlements();
}, 2500);

// On stage:
await api("/demo/simulate-payment", { method: "POST", json: { payer_id: 1 } });
```

---

# Part 2: API reference (all endpoints)

Base URL: `http://localhost:8000`. `*` marks a required query parameter. Examples are real responses (lists trimmed).

## 2.0 System

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{"ok": true}` |
| GET | `/openapi.json`, `/docs` | Contract and interactive docs |

## 2.1 Merchants and home

### `GET /merchants`
The three demo personas, for the merchant switcher.
```json
[{"id":1,"name":"Ramesh General Store","role":"retailer","gst_scheme":"composition","language":"hi"},
 {"id":2,"name":"Gupta Wholesale","role":"wholesaler","gst_scheme":"regular","language":"hi"},
 {"id":3,"name":"Sharma Traders","role":"distributor","gst_scheme":"regular","language":"en"}]
```
`role` is `retailer | wholesaler | distributor`; `gst_scheme` is `composition | regular`.

### `GET /merchants/{id}`
One merchant (same shape). `404` if unknown.

### `GET /merchants/{id}/home`
Everything the app's Home screen needs in one call.
```json
{"merchant": {"id":1,"name":"Ramesh General Store","role":"retailer","gst_scheme":"composition","language":"hi"},
 "owe_this_week": 112400.0, "suppliers_due_this_week": 5, "alert_count": 2, "score": 819,
 "shortfall_date": "2026-11-05", "shortfall_amount": 38000.0,
 "forecast": [{"day":"2026-11-01","inflow":17119.11,"outflow":5168.98,"balance":30393.09,"low":27381.48,"high":33404.71}]}
```
`shortfall_date` / `shortfall_amount` are `null` / `0` when no shortfall is forecast.

## 2.2 Dues, suppliers, ledger

### `GET /merchants/{id}/dues?period=week`
`period`: `today | week | month` (default `week`; anything else → `422`). Includes overdue bills. Sorted by due date.
```json
{"period":"week","total":112400.0,"items":[
  {"supplier_id":3,"supplier_name":"Gupta Oil Mills","amount":19800.0,"next_due":"2026-11-03","invoice_nos":["GO-5531"]}]}
```

### `GET /merchants/{id}/suppliers`
Supplier list with balance, next due date and a risk badge, sorted by next due.
```json
[{"id":1,"name":"Sharma Traders","balance_due":73800.0,"next_due":"2026-11-04","risk":"medium","gstin_status":"active"}]
```
`risk`: `high` if the supplier's GSTIN is not active, `medium` if there are open alerts for them, else `low`.
`gstin_status`: `active | cancelled | not_filing`.

### `GET /merchants/{id}/suppliers/{supplier_id}/ledger`
Timeline of bills, payments and credit notes with a running balance.
```json
{"supplier_id":1,"supplier_name":"Sharma Traders","balance_due":73800.0,
 "entries":[{"day":"2026-08-05","kind":"bill","ref":"ST-796","amount":26000.0,"balance":26000.0,"status":"paid"}],
 "open_issues":[ /* Alert objects, see 2.3 */ ]}
```
`kind`: `bill` (amount positive) | `payment` (negative) | `credit_note` (negative). `404` if the supplier is not this merchant's.

## 2.3 Alerts

### `GET /merchants/{id}/alerts?type=`
Open alerts, optionally filtered by `type`.
```json
[{"id":1,"type":"missing_credit_note","severity":"warn",
  "message_en":"Short payment of Rs 2,300: the credit note has not been issued. Ask the supplier.",
  "message_hi":"Rs 2,300 kam pay hua hai; credit note abhi tak nahi aaya. Supplier se maangein.",
  "invoice_id":61,"supplier_id":1,"payment_id":null,"status":"open"}]
```

| `type` | Raised when | Suggested action in the UI |
|---|---|---|
| `missing_credit_note` | A bill was short-paid and no credit note arrived | "Request credit note" → agent tool `request_credit_note` |
| `confirm_payee` | A payment went to an unfamiliar name that fuzzy-matches a supplier | Confirm via `confirm-payee` (below) |
| `possible_duplicate` | A scanned bill matches one already filed | Confirm / discard / ask supplier |
| `gstin_invalid` | Supplier GSTIN fails the checksum | Review the field; input tax credit is at risk |
| `hsn_rate_mismatch` | Line's GST rate differs from the usual rate for its HSN code | Review the line |
| `wrong_tax_type` | IGST charged within a state (or CGST/SGST across states) | Review |
| `total_mismatch`, `line_total_mismatch`, `tax_computed_wrong` | Bill maths does not add up | Review |
| `gstin_risk` | IMS: supplier GSTIN cancelled | Talk to the supplier |
| `missing_from_ims` | IMS: bill exists but the supplier has not filed it | Chase the supplier |

`severity`: `info | warn | high`.

### `POST /merchants/{id}/alerts/{alert_id}/resolve`
Marks an alert resolved; returns the alert. `404` if it is not this merchant's. (Resolved alerts stay resolved when
reconciliation re-runs.)

### `POST /merchants/{id}/payments/{payment_id}/confirm-payee`
Body `{"supplier_id": 1}`. Confirms who an unfamiliar payee was; the name is saved as an alias so it resolves next time and
the `confirm_payee` alert closes. Returns `{"ok": true}`.

### `POST /reconcile/run?merchant_id=*`
Re-runs matching of payments to bills (also happens automatically after every bill/payment change).
Returns `{"matches": 107, "unmatched_payments": 0, "unpaid_invoices": 9}`.

## 2.4 Bills (invoices)

### `POST /invoices/ingest`  (multipart/form-data)
Read a bill photo or PDF. Fields: `merchant_id` (int), `file` (jpg/png/pdf, ≤ 15 MB), `source` (`app | whatsapp`, default
`app`). The bill is stored **unconfirmed**: it is not in dues until confirmed.
```json
{"invoice_id": 268,
 "invoice": {"supplier_name":"Sharma Traders","supplier_gstin":"09TEKHF7133L1Z5","invoice_no":"ST-2291",
             "invoice_date":"2026-10-28","due_date":"2026-11-04","line_items":[{"description":"Biscuits Family Pack",
             "hsn":"1905","qty":1.0,"unit":"lot","rate":17752.38,"taxable_value":17752.38,"gst_rate":5.0,
             "cgst":443.81,"sgst":443.81,"igst":0.0}],
             "taxable_total":17752.38,"tax_total":887.62,"round_off":0.0,"grand_total":18640.0,"bill_type":"gst_invoice"},
 "issues": [{"code":"possible_duplicate","severity":"high","message_en":"Possible duplicate of invoice ST-2291 dated 2026-10-12.",
             "message_hi":"Yeh bill ST-2291 (2026-10-12) ka duplicate lag raha hai.","field":"invoice_no","line_index":null}],
 "field_confidence": {"supplier_name":0.95,"invoice_no":0.95,"grand_total":0.95,"supplier_gstin":0.95},
 "low_confidence_fields": [],
 "duplicate": {"invoice_id":60,"invoice_no":"ST-2291","invoice_date":"2026-10-12","paid_on":"2026-10-12"},
 "image_url": "http://localhost:8000/media/bills/….jpg"}
```
- `bill_type`: `gst_invoice | kachcha | credit_note | debit_note` (`kachcha` = handwritten / non-GST).
- **Review screen:** highlight every field named in `low_confidence_fields` (confidence below 0.8; handwritten bills score
  0.75 so they always ask). Highlight the line named by `issues[].line_index`.
- `duplicate` is non-null when the bill matches one already filed; `paid_on` says when that one was paid (`null` if unpaid).
  A duplicate is stored as `disputed` and never enters dues unless the user says "new bill".
- `image_url` is **private**: bill images are not served over HTTP. Keep the picture you captured on the device.
- `422 unreadable` if invoice number, date, total or supplier could not be found.

### `POST /invoices/{invoice_id}/confirm?merchant_id=*`
Body (optional): `{"corrections": {"grand_total": 18000, "invoice_date": "2026-10-28"}}`. Correctable fields:
`invoice_no`, `invoice_date`, `due_date`, `grand_total`, `taxable_total`, `tax_total` (anything else → `422`). Puts the bill
in the ledger and re-runs matching.
```json
{"id":268,"invoice_no":"ST-2291","status":"open","confirmed":true,"grand_total":18640.0,"amount_settled":0.0}
```
`status`: `open | part_paid | paid | disputed`.

### `POST /invoices/{invoice_id}/discard?merchant_id=*`
Marks the bill `disputed` and removes it from the ledger. Same response shape.

### `POST /invoices/{invoice_id}/ask-supplier?merchant_id=*`
Messages the supplier's account (WhatsApp) asking about the bill. Returns `{"id":1,"status":"open","invoice_id":268,"answer":null}`.

### `POST /queries/{query_id}/answer`
Body `{"answer": "duplicate" | "new_bill"}`. The supplier's answer flows back: `duplicate` discards the bill, `new_bill`
confirms it, and the retailer is notified. Answering twice → `422`.

### `GET /merchants/{id}/register.csv?month=2026-10`
Purchase register for the CA. Returns `text/csv` as an attachment. Columns:
`Date, Invoice No, Supplier, GSTIN, Taxable, CGST, SGST, IGST, Total, Status`.

## 2.5 Payments (two-step: draft, then confirm)

### `POST /payments/draft`
```json
{"merchant_id":1,"supplier_id":1,"amount":5000,"source":"bank"}
```
`source`: `bank` or `credit` (credit needs an accepted offer and enough remaining limit). `amount` must be > 0.
```json
{"id":1,"supplier_id":1,"amount":5000.0,"source":"bank","status":"drafted",
 "upi_link":"upi://pay?pa=sharmatraders%40paytm&pn=Sharma%20Traders&am=5000.00&cu=INR"}
```
Nothing has moved yet. On Android, open `upi_link` as an intent to pay.

### `POST /payments/{draft_id}/confirm`
Body `{"merchant_id": 1}`. Records the payment, debits the (mock) bank balance for `bank`, and re-runs matching.
```json
{"id":330,"amount":5000.0,"mode":"upi","paid_at":"2026-10-31T10:12:00","confirmed":true,"supplier_id":1}
```
`mode`: `upi | cash | credit_line`. Confirming twice → `422`.

### Cash entries
| Call | Body / query | Result |
|---|---|---|
| `POST /payments/cash` | `{"merchant_id":1,"supplier_id":1,"amount":3000}` | A **pending** entry (`confirmed:false`); ignored by matching until confirmed |
| `POST /payments/cash/{id}/confirm` | `{"merchant_id":1}` | `confirmed:true`; bills are re-matched |
| `DELETE /payments/cash/{id}?merchant_id=*` | – | `204`; only pending entries can be deleted |

## 2.6 IMS (GST Invoice Management System; regular-GST merchants only)

Composition-scheme merchants get `409 not_applicable`.

### `GET /merchants/{id}/ims?month=2026-10*`
```json
{"month":"2026-10","counts":{"accept":19,"reject":2,"pending":4},
 "entries":[{"id":1,"supplier_name":"Khatri Oil Traders","invoice_no":"KOT-632","invoice_date":"2026-10-01",
   "taxable":26476.18,"tax":1323.82,"action":"accept","reason_en":"Bill and GST portal match.",
   "reason_hi":"Bill aur GST portal match.","itc_risk":false,"approved":false}],
 "missing_from_ims":[{"invoice_id":108,"invoice_no":"TCC-578","reason_en":"Supplier has not filed this bill in GSTR-1; chase them.",
   "reason_hi":"Supplier ne GSTR-1 mein nahi daala; unse poochhein."}]}
```
`action`: `accept | reject | pending`. `itc_risk: true` means input tax credit is at risk (cancelled supplier GSTIN).

### `POST /merchants/{id}/ims/{entry_id}/override`
Body `{"action": "accept" | "reject" | "pending"}`. Your choice sticks across recomputation. Returns `{"id":1,"action":"reject"}`.

### `POST /merchants/{id}/ims/approve-all?month=2026-10*`
Records the current suggestions as the merchant's decisions **in Hisaab only**. Returns
`{"approved": 25, "note": "Saved in Hisaab only; filing on the GST portal needs a GSP integration."}`. Show that note.

## 2.7 Forecast, score, credit

### `GET /merchants/{id}/forecast?days=14`
`days` 1-60. Daily projected balance with a confidence band (±1 standard deviation of daily inflow).
```json
{"buffer":10000.0,"first_below_date":"2026-11-04","shortfall_date":"2026-11-05","shortfall_amount":38000.0,
 "days":[{"day":"2026-11-01","inflow":17119.11,"outflow":5168.98,"balance":30393.09,"low":27381.48,"high":33404.71}]}
```
`first_below_date` = first day under the ₹10,000 safety buffer; `shortfall_date` = the day of the lowest balance;
`shortfall_amount` = buffer minus that lowest balance (extra cash needed). Plot `balance` with `low`/`high` as a shaded band.

### `GET /merchants/{id}/score`
Hisaab Score, 300-900, explainable.
```json
{"score":819,"factors":{"stability":0.94,"discipline":0.97,"growth":0.58,"completeness":0.85,"concentration":0.79},
 "reasons":[{"factor":"discipline","positive":true,"text_en":"You pay 97% of bills on time","text_hi":"Aap 97% bills time par pay karte hain"}]}
```
`reasons` holds the top 3, measured against the median merchant. Factors are 0-1.

### Credit (consent, then offer, then accept)
1. `POST /merchants/{id}/consents` body `{"scope":["gst_data","bank_data"]}` (both scopes required) → `{"id":1,"scope":[...],"granted_at":"…","expires_at":"…"}` (valid 30 days).
2. `GET /merchants/{id}/credit-offer` → without consent: `403 consent_required`. With consent:
   ```json
   {"eligible":true,"reason":"Eligible","offer_id":1,"limit":50000.0,"rate_apr_min":14.0,"rate_apr_max":18.0,
    "tenure_days":60,"reasons":["Your weekly UPI collections are steady","You pay 97% of bills on time"],"illustrative":true}
   ```
   Not eligible: `{"eligible":false,"reason":"No cash shortfall to cover", ...}` (HTTP 200). Always label rates as *illustrative*.
3. `POST /merchants/{id}/credit-offer/{offer_id}/accept` → same shape with `"reason":"Accepted"`. Then pay from credit:
   `POST /payments/draft` with `"source":"credit"`. The money goes to the supplier, never to the merchant.

## 2.8 Agent

### `POST /agent/chat`
```json
{"merchant_id":1,"text":"Is hafte kitna dena hai?","channel":"app","language":"hi","history":null}
```
`channel`: `app | whatsapp | voice` (controls formatting). `language` defaults to the merchant's. `history` is only used to seed
a brand-new conversation; afterwards the server remembers the thread itself.
```json
{"text":"Is hafte 5 suppliers ko ₹1,12,400 dena hai:\n• Gupta Oil Mills ₹19,800 (03/11)\n…",
 "tool_calls":[{"name":"get_dues","arguments":{"period":"week"},"result":{"total":112400.0,"total_display":"₹1,12,400","count":5,"items":[…]}}],
 "source":"template",
 "trace":{"engine":"graph","source":"template","total_ms":657.5,"total_tokens":1853,"steps":[{"kind":"llm","name":"chat","ms":620.5,"input_tokens":1794,"output_tokens":59}]}}
```
- Use `tool_calls[].result` for rich cards (it is structured data); use `text` for the chat bubble.
- If a tool prepared something that needs a tap (`log_cash_payment` → `result.pending_payment_id`; `draft_payment` →
  `result.draft_id`), show Confirm/Cancel and call the payment endpoints in 2.5. The agent cannot confirm by itself.
- See the `source` table in the [setup guide](01-backend-setup.md#6-the-agent).

### `POST /agent/voice`  (multipart/form-data)
Fields: `merchant_id`, `file` (audio ≤ 5 MB). **Prefer 16 kHz mono WAV**: other formats need `ffmpeg` on the server.
```json
{"transcript":"इस हफ्ते कितना देना है?","language_code":"hi-IN",
 "text":"Is hafte aapko kul ₹1,12,400 ka payment karna hai. Yeh paanch suppliers ko dena hai.",
 "audio_url":"http://localhost:8000/media/audio/….wav","tool_calls":[…],"source":"llm"}
```
`text` is already trimmed to at most two sentences for speaking. `audio_url` is `null` if speech synthesis failed: show `text`
anyway. Typical latency 2-3 s.

### `GET /merchants/{id}/events?after_id=0`
Soundbox-style announcements, oldest first: `[{"id":4,"text":"Rs 2,500 prapt hue"}]`. Poll with the largest `id` you have seen.

## 2.9 Distributor

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/distributors/{id}/receivables` | – | `Receivable[]` (most overdue first) |
| GET | `/distributors/{id}/retailers/{retailer_id}` | – | One `Receivable`; `404` if that retailer has no bills from you |
| GET | `/distributors/{id}/settlements` | – | `Settlement[]`, newest first |
| POST | `/distributors/{id}/invoices` | `{"retailer_id":1,"lines":[{"description":"Tea 250g","hsn":"0902","qty":100,"rate":120,"gst_rate":5}],"credit_days":14}` | `{"invoice_id":268,"invoice_no":"ST-2310","grand_total":12600.0,"due_date":"2026-11-14"}` |
| POST | `/distributors/{id}/reminders` | `{"retailer_ids":[36],"language":"hi","send":false}` | `{"sent":false,"reminders":[{"retailer_id":36,"retailer_name":"…","amount":116000.0,"days_overdue":50,"tone":"final","text":"Namaste …"}]}` |

- Non-distributor ids return `404`. `qty`/`rate` must be > 0; `gst_rate` defaults to 5; CGST+SGST vs IGST is chosen automatically
  from the two GSTINs.
- `retailer_ids: null` drafts for every overdue retailer. With `send:true` the messages are delivered over WhatsApp when it is configured; otherwise they are only recorded in the conversation log.
- A `Receivable` is `{retailer_id, name, outstanding, overdue_amount, days_overdue, reliability, suggested_limit, reason_en, reason_hi}`.
  `reliability` is 0-100 from on-time rate and days-to-pay; `suggested_limit` = average monthly purchase × a 0.5-2.0 multiplier.

## 2.10 Demo controls

| Method | Path | Body | Effect |
|---|---|---|---|
| POST | `/demo/reset` | – | Restores the seed (~0.5 s). `{"ok":true}` |
| POST | `/demo/simulate-payment` | `{"payer_id":1,"supplier_name":"Sharma Traders","amount":31500}` | Ramesh pays the distributor over UPI: both ledgers reconcile and Vikas's soundbox announces it |
| POST | `/demo/simulate-customer-payment` | `{"merchant_id":1,"amount":2500}` | A customer pays the merchant's QR: the soundbox chimes (`{"collection_id":277,"amount":2500.0}`) |

`simulate-payment` returns
`{"gross":31500.0,"mdr":126.0,"net":31374.0,"matched":[{"invoice_no":"ST-2308","amount":18640.0},{"invoice_no":"ST-2309","amount":12860.0}],"reliability_before":80.7,"reliability_after":83.7}`.

## 2.11 Webhooks

`GET|POST /webhooks/whatsapp` is called by Meta, not by your client. See the [WhatsApp guide](04-whatsapp-integration.md).

---

## Endpoint index (43)

`/agent/chat` · `/agent/voice` · `/demo/reset` · `/demo/simulate-payment` · `/demo/simulate-customer-payment` ·
`/distributors/{id}/invoices` · `…/receivables` · `…/reminders` · `…/retailers/{rid}` · `…/settlements` · `/health` ·
`/invoices/ingest` · `/invoices/{id}/ask-supplier` · `…/confirm` · `…/discard` · `/merchants` · `/merchants/{id}` ·
`…/alerts` · `…/alerts/{aid}/resolve` · `…/consents` · `…/credit-offer` · `…/credit-offer/{oid}/accept` · `…/dues` ·
`…/events` · `…/forecast` · `…/home` · `…/ims` · `…/ims/approve-all` · `…/ims/{eid}/override` ·
`…/payments/{pid}/confirm-payee` · `…/register.csv` · `…/score` · `…/suppliers` · `…/suppliers/{sid}/ledger` ·
`/payments/cash` · `/payments/cash/{id}` (DELETE) · `/payments/cash/{id}/confirm` · `/payments/draft` ·
`/payments/{draft_id}/confirm` · `/queries/{id}/answer` · `/reconcile/run` · `/webhooks/whatsapp` (GET, POST)
