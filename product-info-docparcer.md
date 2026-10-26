# DocParser — Product Info for Landing Page

> Source: analysis of the `docparser/` codebase (README, `docs/ui-redesign-brief.md`,
> `package.json` / `pyproject.toml` descriptions, service-layer docstrings, CI config).
> Note: the repo/product is referred to internally as both **DocParser** and **UVIRA**.
> The brief you asked for uses "DocParcer" — spelling normalised to **DocParser** here to
> match the code. Confirm the public product name before publishing.

---

## 1. Product Name & Tagline

**DocParser**

Tagline options (pick one):
- "From vendor invoice to posted in SAP — untouched by human hands."
- "Reads your documents, files them in SAP, and knows when to ask for help."
- "Straight-through document processing for SAP finance teams."

---

## 2. What it does

DocParser takes the business documents that flood a finance back-office —
vendor invoices, purchase-order and non-PO invoices, goods receipts, sales
orders, payment advices, credit notes and freight invoices — and turns each
one into a completed transaction in SAP. It reads the document (including
scanned images and photos), works out where it belongs in SAP by checking the
purchase order directly, validates it against seven business rules, and either
posts it automatically or hands it to a person with a plain-English reason why.
The result: documents that used to take minutes of manual keying and checking
are captured, matched and posted in seconds, with a full audit trail of every
decision.

---

## 3. Target users

- **Accounts-payable and finance shared-service teams** running SAP who process
  high volumes of vendor invoices and want straight-through posting.
- **Enterprises and mid-market companies on SAP** (S/4HANA or ECC) with
  multi-entity / multi-tenant operations — each business unit's SAP endpoints
  and pricing are configured separately.
- **Procurement and logistics operations** handling goods receipts, freight
  invoices and PO matching at scale.
- **Finance transformation / automation owners** looking to cut manual keying
  and reduce posting errors without removing human control over financial
  postings.
- **BPO / outsourced finance providers** who need per-company isolation,
  per-document billing and an activity audit log.

---

## 4. Core features (as user benefits)

- **Drop in a document, get a posted SAP transaction** — one upload flow for
  every document type; no need to tell the system what kind of document it is.
- **Knows the destination in about a second** — while the document is still
  being read, DocParser has already checked the PO in SAP and shown you where
  it will land (which SAP transaction, whether a goods receipt is still needed).
- **Reads scans and photos, not just clean PDFs** — AI extraction pulls 45+
  fields (header, vendor, ship-to, financials, bank, transport, line items)
  even when there's no text layer.
- **Catches problems before they hit SAP** — seven automatic checks: extraction
  confidence, vendor/GSTIN match, invoice value vs PO, goods-receipt confirmed,
  duplicate detection, routing resolved, trusted email sender.
- **Posts unattended only when every check passes** — anything short of that is
  parked for review with the specific reason, so reviewers know exactly what to
  look at instead of re-checking the whole invoice.
- **Invoices by email, handled automatically** — a monitored mailbox ingests
  vendor invoices, replies to the sender with what happened, and enforces a
  sender allowlist.
- **Live processing view** — a pipeline rail shows each stage, the time it took,
  and the evidence behind the routing decision.
- **Full history and reporting** — searchable document history, filters by
  status / type / SAP transaction code, CSV export, dashboard KPIs, and
  per-document billing by transaction type.
- **Handles the hard cases without looking broken** — held documents get an
  inline "correct the PO number" fix that re-runs routing; partial postings
  (goods receipt succeeded, invoice failed) stay visible so nothing is
  double-posted; SAP outages resolve themselves.
- **Multi-company by design** — every customer's SAP endpoints, payload shapes,
  mailboxes and pricing are configured independently; users only ever see their
  own company's documents.

---

## 5. Key differentiators

- **Routing from SAP fact, not human guesswork.** Staff used to tell the system
  whether an invoice was a material-PO, service-PO or non-PO invoice — read off
  the paper, and sometimes wrong, which sent documents down the wrong workflow
  with nothing to catch it. DocParser asks SAP directly (read-only), so the
  route is derived from fact and carries no guesswork.
- **The speed gap is the point.** Routing resolves in under a second; full
  extraction takes ~17 seconds. DocParser shows you the destination immediately
  and fills in the contents as they're read — you're not staring at a spinner.
- **Auto-posting with the burden of proof reversed.** Because posting to SAP is
  irreversible, every gate must pass and any gate that *can't* be evaluated
  counts as a failure, never a skip. Auto-post is off by default — turning off
  human approval on a financial posting is treated as a control decision, not a
  toggle.
- **Automation you can audit.** Every routing decision shows its evidence
  (e.g. service PO, service entry sheet number); every check carries a sentence
  explaining itself; a held document shows SAP's own words. Teams trust
  automation they can inspect.
- **Accuracy through matching, not just OCR.** Extracted data is scored with
  weighted fuzzy matching against the PO — vendor GSTIN, amounts within
  tolerance, line-item and goods-receipt coverage — producing an overall
  validity score rather than a raw OCR confidence number.
- **De-duplication built in** — the same document bytes can't be ingested twice
  for the same company, and invoices already posted are flagged.

---

## 6. Tech highlights (credibility-relevant)

- **AI/ML document extraction** powered by Google Gemini vision models.
- **Reads scanned and photographed documents**, not only digital PDFs —
  accepts PDF, JPEG, PNG and HEIC up to 20 MB.
- **OCR-independent fast path** — a sub-30ms read of the PDF text layer
  extracts the routing fields before the AI pass even starts.
- **Direct SAP integration** via RFC / OData for both reading POs and posting
  transactions (goods receipts, invoices, sales orders, payment advices,
  credit notes).
- **Multi-tenant architecture** — per-customer SAP endpoints, payload
  templates, mailboxes and pricing.
- **Email ingestion** from Microsoft 365, Gmail and IMAP mailboxes.
- **Real-time UI updates** over WebSocket, with polling fallback.
- **Resilient by design** — automatic retries with back-off, circuit breakers,
  error tracking, structured audit logging.
- **Modern stack** — React front end, Python/FastAPI back end, background
  worker queue, containerised deployment.
- **Security** — JWT auth, role-based access, brute-force lockout, write-only
  storage of mailbox and SAP credentials.

---

## 7. Integration points with the other UVIRA products

DocParser currently integrates directly with **SAP**. There is **no code today**
that connects it to the Asset Management System, Customer Portal or Vendor
Portal — the following are plausible integration stories, not existing features.
Flag them as "roadmap" / "possible" on the site.

- **Vendor Portal** — the strongest fit. Instead of vendors emailing invoices to
  a monitored mailbox, they submit through the Vendor Portal; the portal passes
  the file straight into DocParser's ingestion pipeline (which already accepts
  non-web sources), and the vendor sees live status — received, routed, posted,
  or needs correction — in the portal instead of waiting on an email reply. The
  sender-allowlist concept maps naturally to authenticated portal vendors.
- **Customer Portal** — customer-originated documents (sales orders, payment
  advices) uploaded by customers through the portal flow into DocParser, which
  already routes and posts those types to SAP (VA01, F-28). Customers get
  confirmation and document numbers back.
- **Asset Management System** — goods receipts and asset-related invoices
  processed by DocParser could notify the Asset Management System when an asset
  acquisition posts to SAP, so the asset register stays in step with what was
  actually received and booked.
- **Shared account / billing layer** — DocParser already meters usage per
  document and per SAP transaction type and keeps a per-company activity log,
  so it could feed a unified UVIRA billing / admin console covering all four
  products.

---

## 8. Screenshots / UI references

**No polished screenshots, demo GIFs or design mockups exist in the repo.**
What's there:

- `docparser/apps/web/src/assets/uvira-logo.png` — product logo
- `docparser/apps/web/src/assets/uvira-logo-transparent.png` — logo, transparent
- `docparser/apps/api/src/uploads/sales_order/2026/07/DOC-2026-920209_va01_sales_order_flow.png`
  — a single uploaded sample document image (not a UI screenshot)
- `docparser/docs/ui-redesign-brief.md` — contains ASCII wireframes of every
  screen (nav shell, upload wizard, document detail, mail inbox, dashboard) that
  a designer could work from
- `UVIRA_DocParser_Project_Report.docx` (repo root, ~1.5 MB) — a project report
  that likely contains screenshots/diagrams; not inspected here, worth opening
  manually.

**Recommendation:** you'll need to run the app and capture fresh screenshots,
or pull images out of the .docx report. The redesign brief also notes the
current UI is considered "unconsidered" and is slated for a redesign — factor
that into whether you show real screenshots or commissioned mockups.

---

## 9. Existing marketing copy (verbatim, for your review)

From `docparser/README.md`:
> **Intelligent SAP Document Processing** — extract, validate, and post
> structured data from invoices, purchase orders, goods receipts, and more.

From `docparser/package.json` (`description`):
> DocParser — Intelligent SAP Document Processing monorepo

From `docparser/apps/api/pyproject.toml` (`description`):
> DocParser FastAPI backend — SAP Document Processing Service

From `docparser/docs/ui-redesign-brief.md`, "What the product does":
> A vendor sends an invoice. UVIRA reads it, works out where it belongs in SAP,
> checks it, and posts it — ideally without anyone touching it.

> The pivotal fact for design: the route is known at one second, the contents at
> seventeen. The interface should show the destination while the document is
> still being read. That gap is the product's whole claim.

> People trust automation they can audit.

From `docparser/apps/api/src/services/routing_service.py`:
> The user used to tell us whether an invoice was Material PO, Service PO or
> Non-PO. They were reading it off the paper and could be wrong, which sent
> documents down the wrong workflow with nothing to catch it. SAP already knows
> for certain.

From `docparser/apps/api/src/services/autopost_service.py`:
> Posting to SAP is irreversible from this application's side, so the burden of
> proof sits with auto-posting: every gate must pass... When a gate fails the
> document is not rejected — it is handed to a human with the specific reason,
> so the reviewer knows what to look at instead of re-checking the whole invoice.

---

## 10. Gaps / thin spots (don't guess on these)

- **No CHANGELOG** in the repo — no version history or release-notes copy.
- **No customer names, case studies, metrics or testimonials** anywhere in code
  or docs. The "~29 ms" and "~17 s" timings are engineering measurements from
  docstrings, not published benchmarks — treat as internal.
- **No pricing information** beyond the mechanism (per-document, per-SAP-
  transaction-code).
- **Product name is inconsistent** (DocParser vs UVIRA vs your "DocParcer").
- **Accuracy claims**: the code has confidence thresholds (85% minimum
  extraction confidence, 0.70 validity score) but there is **no measured
  accuracy rate** to quote publicly.
- **Cross-product integrations do not exist yet** — see section 7.
- **UI is pre-redesign** — screenshots would show a UI the team already wants to
  replace.
