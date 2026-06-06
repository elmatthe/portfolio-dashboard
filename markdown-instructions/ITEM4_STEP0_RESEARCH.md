# Item 4 — Step 0 Research Summary & Proposed Architecture
**Status: RESEARCH ONLY (no product code written). Awaiting approval before Step 1.**
Date: 2026-06-06 · Branch: `main` (Item A parked on `fix/item-a-clean-machine-hardening`)

> This is the Step 0 deliverable required by
> `ITEM_A_STARTUP_AND_ITEM_4_UNIVERSAL_IMPORT.md` §6. It confirms/adjusts the §2–§5
> architecture against the **actual codebase** and the reference repos, finalizes the
> skill set, and lists the decisions that need your nod. **No Step 1+ code until you approve.**

---

## 1. Skills — inventory, pulls, and the one gap

**Already present in `.claude/skills/` (will use, not re-pull):**
| Skill | Role in Item 4 |
|---|---|
| **defensive-pdf-csv-parser** | *Core.* PDF/CSV extraction, `chardet` encoding detection, SHA-256 dedup, decimal-safe arithmetic. Covers §7's top-priority "data-import reliability" + "PDF table extraction." |
| **finance-analysis** | CSV/Excel financial ingestion patterns (pandas/openpyxl). |
| **xlsx** | Spreadsheet read incl. messy/misplaced-header cleanup — directly relevant to Step 2 Excel handling. |
| **fullstack-bridge-sync** | Python↔TS contract for the import route + the mapping-editor response shape + `types.ts`. |
| **acb-chronological-integrity** | Confirm generic rows feed the ACB walk in chronological order (Step 8). |
| *(xlsm-vba)* | Not relevant — we read .xlsm *data*, never inject VBA. Ignored. |

**Pulled from `claude-skills-main` into `.claude/skills/` this session:**
| Pulled | Why | Size |
|---|---|---|
| **data-quality-auditor** | Dataset profiling (completeness/consistency/validity, anomaly detection, remediation plan) — maps onto the §5 four-state diagnostics + "what's missing / what it blocks." | 60 KB / 5 files |
| **api-test-suite-builder** | Integration/contract-test patterns for the extended import route (Steps 5, 8). | 28 KB / 2 files |

**Deliberately NOT pulled (AI-WORKSPACE: "only take what is needed"):**
- **playwright-pro** (710 KB / 99 files, MCP+hooks+agents) — too heavy, and the repo **already has Playwright E2E scaffolding** (shipped 0.6.0, `frontend/tests/e2e/`). Reuse the existing infra.
- **senior-frontend** (188 KB) — the repo has strong, specific conventions (Bloomberg-derived dark/light tokens, `ModalPortal`, `.input`/`.filter-input` classes). A generic React skill would conflict with "match the surrounding code." Follow existing patterns instead.
- **observability-designer** — about production SLI/SLO/metrics/traces; our app is **local-first, zero-telemetry**. Wrong fit; diagnostics stay local-only.

**Gap — fuzzy matching / string similarity:** no skill exists locally or in the clone. Step 3 will use **`rapidfuzz`** directly (MIT, prebuilt wheels, no native build). If the pattern proves reusable I'll author a small `fuzzy-header-match` skill during Step 3 (per AI-WORKSPACE's "create a skill when a capability recurs").

---

## 2. Reference repos studied (patterns to borrow; provenance noted, no wholesale copy)

- **`afadil/wealthfolio`** *(primary, Steps 3 & 7).* CSV import is a **user-driven column-mapping UI**: map each file column → activity field, with a **separate activity-type sub-step** (raw type string → canonical BUY/SELL/DIVIDEND/…), saved as a **reusable per-account import profile**, and a **preview before commit**. → Models our editable mapping editor + the *two-layer* mapping (columns **and** action values) + mapping persistence.
- **`ghostfolio/ghostfolio`.** Flexible CSV → internal `Order` schema; header normalization, date-format detection, dividend/fee handling. → Header-normalization and date-format inference cues.
- **`actualbudget/actual`.** Field mapping with **inflow/outflow (debit/credit) split**, user-chosen date format, dedup by imported-id or date+amount+payee. → The debit/credit → signed `net_amount` handling (§4) and dedup-UX sanity check (our SHA-256 already covers the mechanism).
- **`pdfplumber`** *(already bundled; Step 6).* `page.extract_tables(table_settings)` + `page.extract_text()`. Prefer over camelot/tabula (Java/Ghostscript — bad for a portable `.exe`). Already used by the RBC/TD/CIBC named PDF parsers; the generic PDF lane reuses the same library.
- **`rapidfuzz`** *(Step 3, new dep).* `fuzz.token_set_ratio`, `process.extractOne` for header↔alias scoring. Deterministic, fast, MIT.

---

## 3. Codebase grounding — what the generic lane actually plugs into

I read the real interfaces. The plan's §2 "fork from auto-detection" **already exists**; Item 4 is mostly *upgrading the existing generic fallback*, not adding a parallel pipeline.

- **Registry (`backend/parsers/registry.py`)** — `detect_broker()` runs every parser's `detect()`, picks max; **if < 0.50 it already returns `"generic"`**. `GenericParser` is **already registered LAST** (`_PARSER_MODULES[-1]`). `parse_with_registry()` then runs the parser and FX-populates every row. → Item 4 upgrades `generic.py` in place; the safety boundary already holds. Add a registry-order regression test to lock it.
- **`BaseParser` (`base.py`)** — `BROKER_KEY`, `SUPPORTED_FORMATS`, classmethod `detect()→float`, `parse()→list[Transaction]`. The generic orchestrator conforms to this exactly.
- **Existing `generic.py`** — thin: `sniff_csv_delimiter` → `pd.read_csv` → `_rows_to_transactions` (RBC's converter, CSV/TSV only). Item 4 replaces the body with the layered pipeline; keep the thin path as an internal last-ditch fallback.
- **`_common.py` already provides most of the normalizer** — `safe_float` ($/commas/brackets/ccy tokens), `parse_date` (14 formats + `prefer_dmy` + pandas fallback), `guess_currency` (ISO+symbols), `guess_exchange` (ticker suffix), **`normalize_action` (vocab + shape-based inference)**, `guess_account_type`, `read_text_sample` (BOM/encoding), `sniff_csv_delimiter`. → `normalize.py`/`classify_tx.py` **reuse these**; new code is only header-row finding, value-profiling, derivations, and the four-state outcome.
- **`_COL_ALIASES` (`rbc.py`)** — already a partly-bilingual alias dict consumed via exact `_pick_col`. → Seed for `aliases.py`; Item 4 adds fuzzy + value-profiling on top of exact-alias.
- **Back half is shared & reused as-is** — `FXService.populate_transaction()` (idempotent), `validate_transactions()` (Item 0 gate: parseable date + finite qty/price/net), SHA-256 dedup in `store.upsert_transactions`. Generic rows go through all three unchanged.
- **Import endpoint (`POST /api/import`)** — currently one-shot: `parse_file` → validate → resolve tickers → upsert → return counts. No preview/diagnostics round-trip yet. The named/high-confidence flow stays one-shot; the generic/low-confidence flow needs a **preview→confirm** round-trip (see Decision B).

---

## 4. ⚑ Key architectural decisions (need your nod before Step 1)

**A. Rich action taxonomy maps DOWN to the existing 11-value `Action`.**
`Transaction.action` is a fixed `Literal[BUY, SELL, DIVIDEND, DEPOSIT, WITHDRAWAL, CONTRIBUTION, FEE, SPLIT, INTEREST, TRANSFER, OTHER]` — the ACB engine, store, dashboard, reports, and `types.ts` all key off it. The plan's §4 lists a richer 16-label canonical set (reinvest_drip, corporate_action, journal, return_of_capital, tax_withholding, cash_adjustment, transfer_in/out, …).
**Proposal:** keep the rich label internally for **diagnostics/traceability** (in `raw_row` + the diagnostics report), but **emit only the existing 11** on the `Transaction` (e.g. `transfer_in→DEPOSIT`, `transfer_out→WITHDRAWAL`, `reinvest_drip→BUY`, `return_of_capital/corporate_action/journal/tax_withholding/cash_adjustment→OTHER`). **Do NOT expand `Action` app-wide for 0.7.0** — that ripples into ACB/reports/frontend and risks regressions. (If you want true new action types surfaced, that's a separate, larger change.)

**B. Editable mapping = a preview→confirm round-trip, extending (not forking) `/api/import`.**
Named/high-confidence imports keep today's **one-shot** behavior. Generic/low-confidence imports return a **preview** (proposed `{canonical→column}` map + per-column confidence + 5–10 sample rows + four-state badges + `ImportDiagnostics`) **without inserting**; the user corrects columns in the editor and **confirms**, which inserts. Concretely: `POST /api/import` gains a generic preview response (no insert) + a `POST /api/import/confirm` that takes the user-corrected mapping. The uploaded temp file is held between the two calls via a short-lived token; the confirmed mapping is persisted per **institution-fingerprint** (header signature) so re-importing the same layout reuses it (§5 "auditable & repeatable"). This honors §9 "one ingestion contract, not a second importer."

**C. New dependency: `rapidfuzz` (pinned).** Add to `backend/requirements.txt` and `backend.spec` hiddenimports. `pdfplumber` is already bundled.

**D. Module layout** (per §2, adjusted to reuse `_common.py`):
```
backend/import_engine/
  canonical.py        # rich action taxonomy + §4 min-schema ruleset + DOWN-map to the 11 Actions
  aliases.py          # bilingual alias dict (seeded from rbc._COL_ALIASES + §4)
  readers.py          # csv/tsv/xls/xlsx/xlsm adapters (+pdf in Step 6) — wraps _common sniffers
  table_extract.py    # find-the-table (Excel sheet pick) + find-the-header-row scoring
  classify_columns.py # alias → rapidfuzz → value-profiling → {canonical: col} + confidence
  normalize.py        # thin: delegates to _common helpers; adds derivations (amount=qty×price, …)
  classify_tx.py      # action map/infer (wraps _common.normalize_action) + four-state outcome
  diagnostics.py      # ImportDiagnostics dataclass + summary builder (§5)
backend/parsers/generic.py   # orchestrates import_engine; stays registered LAST
```

---

## 5. Confirmed vs. adjusted (relative to plan §2–§5)

**Confirmed as-written:** layered pipeline, generic-registered-last safety boundary, value-profiling as the tie-breaker, find-the-header-row scoring, four-state per-row outcome, `ImportDiagnostics` answering the four questions, deterministic/repeatable mapping, mandatory editable preview (Step 7), CSV/XLSX-first with PDF as lower-priority Step 6, QIF/OFX out of scope.

**Adjusted (grounded in the codebase):**
1. **Reuse `_common.py`** for normalization/action-inference — don't reinvent (plan implied fresh `normalize.py`).
2. **Action down-mapping** to the existing 11 (Decision A) — the plan's 16-label set is internal-only.
3. **Seed `aliases.py` from `rbc._COL_ALIASES`** (already bilingual-ish), not from scratch.
4. **`generic.py` upgraded in place** — the parallel "generic lane" already exists via the registry; no new routing.
5. **Preview→confirm endpoints** (Decision B) make the §9 "additional state of the existing preview" concrete.

---

## 6. Step plan (one commit each, after approval) — unchanged order
S1 canonical+aliases · S2 readers+table/header extract · S3 column classifier (alias+rapidfuzz+profiling) · S4 normalize+action/four-state (reusing `_common`) · S5 GenericParser orchestrator + diagnostics (registered LAST; FX→validate→dedup→store) · S6 PDF via pdfplumber into the same path · S7 editable mapping preview UI (preview→confirm) · S8 integration/regression + Master-Debug §6b + bump **0.7.0**. `pytest` + `tsc` green and visually verified in the running app after each.

---

## 7. What I did NOT do (gate discipline)
- **No product code.** Only: pulled 2 skills, wrote this note.
- Did **not** touch Item A or the `fix/item-a-clean-machine-hardening` branch.
- Did **not** expand the `Action` type or any shared model.
- Did **not** add `rapidfuzz` yet (Step 3, on approval).

## 8. STOP — awaiting your approval
Please confirm (or redirect) **Decision A** (action down-mapping vs. expanding `Action`), **Decision B** (preview→confirm endpoints), and **Decision C** (`rapidfuzz`). On approval I'll create a Step-1 branch and begin `canonical.py` + `aliases.py`.
