# UVIRA — Interface Specification for Redesign

Paste this whole file into a design prompt. It describes every screen in the
portal: what it is for, what it shows, and the states it must survive.

---

## 1. What the product does

A vendor sends an invoice. UVIRA reads it, works out where it belongs in SAP,
checks it, and posts it — ideally without anyone touching it.

The pipeline runs in two tracks the moment a document arrives:

```
t=0        file arrives (web upload or mailbox)
t=0.03s    identity scrape   PO number + invoice number from page 1
t=0.9s     SAP routing       material PO? service PO? GR done? -> the route
           |  ...meanwhile...
t=17s      OCR extraction    45+ fields via Gemini
t=17s      seven checks      confidence, vendor, value, receipt, duplicate...
t=18s      posted to SAP     or held for a person, with the reason
```

**The pivotal fact for design: the route is known at one second, the contents at
seventeen.** The interface should show the destination while the document is
still being read. That gap is the product's whole claim and the current UI
barely expresses it.

### Document journeys

| Type | SAP T-code | Path |
|---|---|---|
| Vendor invoice, material PO | MIGO → MIRO | Post goods receipt if missing, then the invoice |
| Vendor invoice, service PO | MIRO | Service entry sheet must exist; validate and post in one call |
| Vendor invoice, no PO | FB60 | Human supplies G/L account and cost centre |
| Goods receipt | MIGO | Stock movement only |
| Sales order | VA01 | Simulate, then create |
| Payment advice | F-28 | Simulate, then post |
| Credit note | MR8M | Compare against the posted invoice first |

---

## 2. Current design system (what you are replacing)

**Colour** — a single indigo ramp plus Tailwind neutrals. Semantic colour is
applied ad hoc at call sites rather than tokenised, which is why status
treatment drifts between screens.

| Role | Value | Used for |
|---|---|---|
| primary-600 | `#4F46E5` | Primary buttons, active nav, focus rings |
| primary-500 | `#6366F1` | Spinners, accents |
| violet-600 | `#7C3AED` | Admin area only — a second accent with no system behind it |
| green-600 | Tailwind green | Posted, passing checks |
| amber-500/600 | Tailwind amber | Awaiting review, warnings |
| red-600 | Tailwind red | Failed, blocking errors |

**Type** — system stack throughout. No display face, no type scale; sizes are
chosen per component (`text-xs` … `text-2xl`). This is the main reason the
portal reads as unconsidered. Data columns do not use tabular figures, so
numbers fail to align.

**Surface language**
- Cards: `rounded-xl`, 1px neutral border, white on `neutral-50`; dark mode `neutral-900` on `neutral-950`
- Density: generous padding, ~14px body. Tables are comfortable rather than dense, which hurts the list screens
- Radius: `rounded-lg` on controls, `rounded-xl` on cards, `rounded-full` on pills — applied uniformly, so nothing is emphasised
- Dark mode: implemented on every screen via Tailwind `dark:` variants, and genuinely used

**Stack** — React 18, Vite, Tailwind, TanStack Query, Zustand, lucide-react icons.

---

## 3. Navigation shell

Collapsible left sidebar + top bar. Two shells: the main app and a separate
admin layout.

```
+-----------------+---------------------------------------------+
| UVIRA           |  Page title              [actions]          |
|                 +---------------------------------------------+
| MAIN            |                                             |
|  Dashboard   12 |                                             |
|  Upload         |            page content                     |
|  History        |                                             |
|  Mail Inbox     |                                             |
|  Pending      3 |                                             |
|                 |                                             |
| UPLOAD BY TYPE  |                                             |
|  Vendor Invoice |                                             |
|  Sales Order    |                                             |
|  ... 4 more     |                                             |
|                 |                                             |
| ACCOUNT         |                                             |
|  Team / Billing |                                             |
|  Reports        |                                             |
|  Settings       |                                             |
| [<] collapse    |                                             |
+-----------------+---------------------------------------------+
```

- **Groups**: Main · Upload by type · Account
- **Badges**: Dashboard and Pending Review carry live counts
- **Collapse**: rail collapses to icons; labels fade rather than unmount
- **Role gating**: operators lose Dashboard and Pending Review; managers keep Billing; only admins see the admin shell
- **Topbar**: title, subtitle, and a slot for page actions — where Validate / Post buttons live

> The "Upload by type" group is six sidebar entries for one destination. Since
> routing now determines the document type from SAP automatically, that group is
> largely obsolete.

---

## 4. Screens

### 4.1 Upload & Process — `/upload` — all roles

The primary working screen. Five-step wizard shown as a step indicator:
**Upload → Extracting → Review → Validation → Complete**. For goods receipts the
middle steps become **Post GR → Post Invoice**.

- **Step 1 Upload** — document-type picker (6 tiles), then a drag-and-drop zone
  with progress. Vendor invoices show a note that the type is detected
  automatically; the old PO/Non-PO and Material/Service pickers were removed.
- **Step 2 Extracting** — a skeleton of the form on the left, and the *pipeline
  rail* on the right filling in live: Uploaded → Identified (30 ms) → Routed by
  SAP (800 ms) → Extracting → Checks. This is the moment the product is most
  impressive and the design should exploit it.
- **Step 3 Review** — every extracted field in an editable form, grouped:
  invoice header, vendor, ship-to, financials, bank, transport, and a
  collapsible line-item table. ~45 fields; the densest surface in the product.
- **Step 4 Validation** — confidence ring, three sub-scores, mismatch list,
  GR/SES status per line, and for service POs a gate panel with per-line
  availability.
- **Step 5 Complete** — success panel with the SAP document number and T-code.
- **Variants** — non-PO invoices swap step 3 for an FB60 form (G/L, cost centre,
  WHT per line). Sales orders, payment advices and credit notes each have their
  own form component.

### 4.2 Document Detail — `/documents/:id` — all roles

Everything known about one document. Two columns.

```
+--------------------------------------+  +------------------+
| Summary strip: status, vendor, value |  | Processing       |
+--------------------------------------+  | pipeline         |
| > File Information                   |  |  * Uploaded      |
| > Extracted Data        (45 fields)  |  |  * Identified 30ms
| > SAP Validation                     |  |  * Routed   800ms
|     confidence, mismatches, gates    |  |  o Extracting... |
| > GRN Posting                        |  |  o Checks        |
| > MIRO Posting                       |  +------------------+
| > Error Log                          |  | Status timeline  |
+--------------------------------------+  +------------------+
```

- **Actions** in the topbar, driven by the route: one *Post Invoice* or *Post GR
  + Invoice* button. Retry OCR appears on failure.
- **Pipeline rail** shows elapsed time per stage and the evidence behind the
  routing decision (`TYPE=ZSER`, `SES 0100000683`) — not just the verdict.
- **Held documents** offer an inline "Correct the PO number" field that re-runs routing.
- **Live updates** via WebSocket when available, otherwise 2-second polling.

### 4.3 History — `/documents` — all roles

Paginated table of everything processed, with search and filters by status, type
and T-code. Operators see only their own uploads; every user is scoped to their
company.

- **Columns**: Document ID, type, T-code chip, vendor, amount, status pill,
  GRN / MIRO / FB60 number, uploaded at
- **Actions**: row click opens the detail; CSV export
- **Deep link**: `?status=validated` powers the sidebar's Pending Review entry

### 4.4 Mail Inbox — `/mail-inbox` — all roles

Invoices that arrived by email rather than upload. Answers the question people
actually ask: a vendor says they emailed an invoice — did it arrive, and did it
land?

```
[All] [Posted] [Awaiting approval] [Needs attention] [Failed]     14 by email

+-------------------------------------------------------------------+
| (mail) Invoice for PO 4500022705            [ Awaiting approval ] |
| from ap@asianpaints.com  * allowlisted  . 01 Sep 2026, 11:00      |
|-------------------------------------------------------------------|
| EXTRACTED        AMOUNT       ROUTED           SAP DOCUMENT        |
| INV-4500022705   Rs 8,260.00  4500022705       --                  |
| Asian Paints                  MIRO . service                       |
| 94% . 1 line                                                       |
|-------------------------------------------------------------------|
| Waiting on: email_sender_trusted, not_duplicate                    |
+-------------------------------------------------------------------+
```

- **Per row**: subject and sender, whether the sender is allowlisted, what OCR
  read, the amount, where SAP routed it with its T-code, and the resulting
  GRN/MIRO number
- **Outcomes**: Posted / Awaiting approval / Needs attention / Failed / Processing
- **Reasons** shown only for rows someone must act on — a posted document offers
  no explanation because there is nothing to do
- **Refreshes** every 10 seconds

### 4.5 Dashboard — `/dashboard` — manager, admin

Four KPI tiles with animated count-up: Total Processed, Posted to SAP, Pending
Review, Total Value INR. Below: recent documents table on the left; By T-Code and
By Status breakdowns on the right as horizontal bars. Quick Actions grid of six
document types at the bottom.

*Weakness*: the tiles show volume but never **time** — the product's actual
claim. No automation rate, no time-to-post, no held-document trend.

### 4.6 Reports — `/reports` — manager, admin

By Document Type and By T-Code breakdowns, a filterable document history, CSV
export. Overlaps the Dashboard substantially; a redesign should merge them or
clearly differentiate them.

### 4.7 Team, Billing, Settings — manager, admin

- **`/team`** — users in the manager's own company: add, edit role, reset
  password, deactivate
- **`/billing`** — per-document charges by T-code, running total, billing history
- **`/settings`** — appearance (light/dark/system), locale and display, default
  landing page, change password

### 4.8 Super Admin — `/admin` — admin only

Separate shell with a violet accent. Lists all companies with status, document
counts and revenue; links to Billing & Revenue and an Activity Monitor (audit log
with search).

*Note*: the violet accent is the only place a second brand colour appears and
nothing else supports it. Either commit to a distinct admin identity or drop it.

### 4.9 Company Detail — `/admin/companies/:id` — admin only

The densest configuration screen, organised as six tabs.

| Tab | Contents |
|---|---|
| Users | Company users, roles, password resets |
| **APIs** | Ten SAP endpoints grouped by workflow. Per row: method, full URL, a sample-JSON editor and a Test button. This is what makes the product multi-tenant — every customer's SAP differs |
| **Mailboxes** | Invoice mailboxes: provider (Microsoft 365 / Gmail / IMAP), credentials (write-only), sender allowlist, auto-post switch, health, Test Connection |
| Pricing | Per-T-code price per document |
| Documents | That company's documents |
| Billing | Their billing records |

### 4.10 Login — `/login`

Email and password, with brute-force lockout after 5 failed attempts.

---

## 5. Component inventory

**Primitives (13)** — Badge, Button, Card, Divider, Input, Modal, Select,
Skeleton, Spinner, **StatusPill**, **TCodeChip**, Table, Tooltip

**Feature components (11)** — **PipelineRail**, **ValidationPanel**,
ExtractedDataForm, FileDropzone, StepIndicator, DocTypePicker, SuccessPanel,
NonPOInvoiceForm, SalesOrderForm, PaymentAdviceForm, CreditComparisonPanel,
MailboxesTab

The two carrying the most meaning are **StatusPill** (13 document states) and
**TCodeChip** (7 SAP transaction codes). Both appear on every list screen and
deserve a proper visual system rather than colour-by-convention.

---

## 6. States and empty cases

Design these, not just the happy path — most are reachable in normal use.

**Document status — 13 values**
`uploaded` `extracting` `extracted` `validating` `validated` `gr_posting`
`gr_posted` `simulating` `simulated` `posting` `posted` `parked` `failed`

**The seven checks** — shown as a pass/fail list wherever a document is waiting.
Each carries a sentence explaining itself; only failures are actionable.

| Check | Reads |
|---|---|
| `route_resolved` | Routed to miro_direct. |
| `extraction_confidence` | Extraction confidence 94% (minimum 85%). |
| `vendor_match` | Invoice GSTIN 06AAA… vs PO vendor 06AAA… |
| `within_po_value` | Invoice 8,260.00 vs PO 8,260.00. |
| `receipt_confirmed` | GR/SES confirmed on all lines. |
| `not_duplicate` | Invoice already processed as DOC-2026-316316. |
| `email_sender_trusted` | Emailed by an unrecognised sender — needs review. |

**Cases that must not look broken**
- Held document — SAP does not recognise the PO number; needs an inline correction field
- SAP unreachable — transient, resolves itself, asks the user for nothing
- Scanned PDF — no text layer, so routing waits for OCR; say so rather than appearing stuck
- Extraction failed — the AI service was overloaded; offer a retry
- Partial posting — goods receipt succeeded, invoice failed; the GR must stay visible so nobody reposts it
- Empty states — no documents, no mail, no mailbox configured, no team members
- Loading — the 17-second extraction needs the pipeline rail to carry the wait

---

## 7. What to fix — priority order

**1. No type system.** The system font stack with per-component sizes is the
single biggest reason it looks unconsidered. A display face for headings, a
readable body face, and one shared scale would change the impression more than
any other single move.

**2. The product's claim is invisible.** Routing resolves in under a second while
extraction takes seventeen. Nothing dramatises that gap — the pipeline rail is
the only place it appears, tucked in a sidebar. It should be the centre of the
working screen.

**3. Uniform emphasis.** Every card has the same radius, border and padding, so
nothing recedes and nothing leads. A document awaiting approval should not look
identical to one already posted.

**4. Numbers are not designed.** Amounts, confidence percentages and SAP document
numbers are the substance of every screen, yet they use proportional figures and
inconsistent alignment. Tabular numerals and right-aligned currency would sharpen
every table.

**5. Two accents, one system.** Indigo in the app, violet in admin, with no rule
connecting them. Semantic colour is applied per call site rather than tokenised.

**6. Dead navigation.** Six sidebar entries for document types the system now
detects on its own.

---

## 8. The one thing to preserve

Where the interface currently shows its reasoning — the pipeline rail's evidence,
the seven checks with their sentences, SAP's own words on a held document — it is
genuinely good. People trust automation they can audit. Whatever the new visual
direction, keep the explanations.
