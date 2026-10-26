# SAP API Reference — UVIRA DocParser Integration

All requests go to `{SAP_BASE_URL}/{path}?sap-client={client}` (client is typically `800`).
Base URL and path are configurable per company in the admin panel; defaults shown below.

---

## 1. Get PO Detail

**Purpose:** Pulls PO header, line items, and prior goods receipts/SES against a PO.

- **Method:** `GET` with a JSON body (not query params)
- **Path:** `zpo_grn/Detail`

**Request:**
```json
{
  "PO": "4500022851"
}
```

**Response (example shape):**
```json
{
  "PO_NUMBER": "4500022851",
  "PO_DATE": "01.10.2026",
  "VENDOR_ID": "1120250000",
  "VENDOR_NAME": "Example Vendor Pvt Ltd",
  "VENDOR_GSTIN": "27AAACX1234F1Z5",
  "SHIP_TO_NAME": "SSDN Plant",
  "COM_CODE": "SSDN",
  "CURRENCY": "INR",
  "GROSS_AMOUNT": "50000.00",
  "NET_AMOUNT": "42372.88",
  "PO_LINE_ITEMS": [
    {
      "ITEM_NUMBER": "00010",
      "MATERIAL_CODE": "ZSRO202500000001",
      "DESCRIPTION": "Example Material",
      "ORDERED_QUANTITY": "50.000",
      "RECEIVED_QUANTITY": "0.000",
      "UOM": "EA",
      "UNIT_PRICE": "847.46",
      "TAX_CODE": "R2",
      "GRN": []
    }
  ]
}
```
On an invalid PO, SAP returns `{"MESSAGE": "Invalid PO / Vendor"}` instead.

---

## 2. GRN / MIGO Posting (standard, movement 101 → unrestricted stock)

- **Method:** `POST`
- **Path:** `ZMIGO/GRN`

**Request:**
```json
{
  "po": "4500022851",
  "vendor": "1120250000",
  "reference_doc_no": "4500022851",
  "posting_date": "07.10.2026",
  "document_date": "07.10.2026",
  "po_items": [
    { "po_item": "00010", "material": "ZSRO202500000001", "quantity": "50" }
  ]
}
```

---

## 3. GRN 103 Posting — quality hold (movement 103 → blocked stock)

**Purpose:** Goods receipt into blocked/quality stock, pending inspection, instead of straight to unrestricted. Used for Sangam's workflow.

- **Method:** `POST`
- **Path:** `zmigo_103/GRN_103`

**Request:**
```json
{
  "PSTNG_DATE": "20261007",
  "DOC_DATE": "20261007",
  "REF_DOC_NO": "4500022737",
  "items": [
    {
      "PO_NUMBER": "4500022737",
      "PO_ITEM": "00010",
      "MATERIAL": "ZSRO202500000001",
      "PLANT": "SSDN",
      "STGE_LOC": "SSDN",
      "VENDOR": "1120250000",
      "ENTRY_QNT": "50.000",
      "ENTRY_UOM": "EA",
      "PO_PR_QNT": "50.000",
      "ORDERPR_UN": "EA"
    }
  ]
}
```
Note the date format here is `YYYYMMDD`, different from the standard GRN's `DD.MM.YYYY`.

---

## 4. MIRO Posting (Material PO)

- **Method:** `POST`
- **Path:** `ZMIRO/MIRO`

**Request:**
```json
{
  "data": [
    {
      "document_date": "07.10.2026",
      "posting_date": "07.10.2026",
      "reference_document_no": "4500022851",
      "company_code": "SSDN",
      "currency": "INR",
      "gross_amount": 50000.00,
      "calc_tax_ind": "X",
      "payment_terms": "",
      "baseline_date": "07.10.2026",
      "business_place": "",
      "item_data": [
        {
          "invoice_document_no": "4500022851",
          "po_number": "4500022851",
          "po_item": "00010",
          "reference_no": "",
          "reference_document_year": "",
          "reference_doc_it": "",
          "tax_code": "R2",
          "item_amount": 42372.88,
          "quantity": 50,
          "po_unit": "EA",
          "tax_amount": 7627
        }
      ]
    }
  ]
}
```
`reference_no` / `reference_document_year` / `reference_doc_it` are the goods receipt reference — all three come from the same GR entry, or all three are left blank; never a mix.

---

## 5. MIRO Posting (Service PO)

- **Method:** `POST`
- **Path:** `zmiro_post/MIRO`

Same shape as above, with two differences: `reference_no` carries the **SES entry number** (not a GR number), and each line also carries `sheet_no` (the SES sheet number).

---

## 6. Service PO Detail

- **Method:** `GET` with a JSON body
- **Path:** `zspodetail/Detail`

**Request:**
```json
{
  "PO": "4500022798"
}
```
Response shape mirrors "Get PO Detail" above, except each line item's `GRN[]` entries carry `SES_NUMBER`/`ENTRY_NO`/`YEAR`/`ITEM` instead of a goods-receipt number, since service POs are confirmed by a Service Entry Sheet, not a goods receipt.

---

## 7. Customer Master Lookup

- **Method:** `GET`
- **Path:** `ZCUSTOMER/CUSTOMER`

Returns customer fields (`CUSTOMER`, `CUSTOMER_NAME`, `CITY`, `REGION`, `COMPANY_CODE`, `SALES_ORGANIZATION`, `EMAIL_ADDRESS`, etc.) — used for the Sales Order flow, not relevant to AP invoicing.

---

## 8. Sales Order Create

- **Method:** `POST`
- **Path:** `ZCREATE_SALESOR/SALESORDER_CREATE`

**Request:**
```json
{
  "doc_type": "TA",
  "sales_org": "",
  "distr_chan": "",
  "division": "",
  "purch_no_c": "",
  "purch_date": "",
  "items": [
    { "itm_number": "10", "material": "MAT-001", "plant": "SSDN", "target_qty": 10, "target_qu": "ST" }
  ],
  "schedules": [
    { "itm_number": "10", "req_date": "07.10.2026", "req_qty": 10 }
  ],
  "partners": [
    { "partn_role": "AG", "partn_numb": "CUST001" }
  ]
}
```

---

## 9. Sales Order Simulate

- **Method:** `POST`
- **Path:** `ZDATA_HOLD/DATA_SIMULATE`

Same payload shape as Sales Order Create — simulate first, create once confirmed.

---

## 10. F-26 Customer Payment

- **Method:** `POST`
- **Path:** `ZINV_PAY/INV_PAYMENT`

**Request:**
```json
{
  "company_code": "SSDN",
  "customer": "CUST001",
  "invoice": "1900000123",
  "fiscal_year": "2026",
  "document_date": "07.10.2026",
  "posting_date": "07.10.2026",
  "currency": "INR",
  "amount": "50000.00",
  "bank_gl": "",
  "value_date": "07.10.2026",
  "reference": "",
  "header_text": "",
  "item_text": "",
  "indicator": "X"
}
```
`indicator: "X"` simulates the payment; `indicator: ""` actually posts it. Always simulate first.

---

## 11. FB60 — Non-PO Invoice Posting

- **Method:** `POST`
- **Path:** `zfb60/fb60post`

**Request:**
```json
{
  "data": [
    {
      "CounterItem_No": 1,
      "Invoice_Doc_Date": "07.10.2026",
      "Document_type": "KR",
      "Company_Code": "SSDN",
      "Posting_Date": "07.10.2026",
      "Currency": "INR",
      "Reference": "",
      "Header_Document_Text": "",
      "Vendor": "1120250000",
      "Invoice_Items": [
        {
          "Invoice_Line_item_no": 1,
          "GL": "",
          "Amount": -10000.00,
          "Tax_Code": "R2",
          "Business_Place": "",
          "Value_Date": "",
          "Assignment_No": "",
          "Text": "",
          "Cost_Center": "",
          "Profit_Center": "",
          "Special_Gl": "",
          "Baseline_Date": "",
          "WHT_Tax": ""
        }
      ]
    }
  ]
}
```

---

## Notes for the SAP team

- All amounts: plain numbers, no currency symbols or commas.
- Dates: `DD.MM.YYYY` everywhere **except** GRN-103, which uses `YYYYMMDD` — please confirm this is correct on your side, since every other endpoint uses the dotted format.
- Authentication: Basic Auth if required — currently none configured in our test environment.
- **GRN-103 is the one endpoint in this list not yet confirmed working against your system** — everything else has been tested against live/sandbox SAP already.
