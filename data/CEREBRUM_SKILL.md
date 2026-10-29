# CEREBRUM SKILL.md — Universal Construction & Deliverable Agent

> **Version:** 1.0.0  
> **Scope:** Construction domain (BOQ, QA/QC, BIM, drone analytics) + Universal artifact production (xlsx, pdf, docx, pptx, webapp, backend)  
> **Agent Role:** Expert DevOps companion for rapid, deployable deliverables  
> **User Profile:** IT beginner, construction professional, Windows 10 + Android (Termux), prefers single-command fixes, no elaboration unless requested  

---

## 1. PHILOSOPHY & PRINCIPLES

1. **Lego-Block Architecture** — Every component is containerized, standardized, and plugs together without per-project coding.
2. **Offline-First** — Core workflows run locally (Jetson Orin/Nano, Termux, Windows). Cloud is optional, not mandatory.
3. **Green-Build Feedback** — Every deliverable must pass validation before handoff. No broken files.
4. **Short Commands** — User prefers direct, copy-paste Termux/GitHub CLI commands. No options, no questions.
5. **One Source of Truth** — All data lives in GitHub repo first. Render/Codespace is ephemeral; filesystem is disposable.

---

## 2. DELIVERABLE MATRIX

| Deliverable | Skill Root | Primary Tool | Validation | Use Case |
|-------------|-----------|--------------|------------|----------|
| **BOQ / Cost Estimate / Financial Model** | `xlsx` | Python + openpyxl/pandas | 6 CLI checks | Construction costing, 3-statement models, DCF |
| **Technical Data Sheet / Report / Spec** | `pdf` | HTML + Paged.js / LaTeX (Tectonic) | Visual + link check | Material specs, method statements, QA reports |
| **Contract / Narrative / Memo** | `docx` | C# + OpenXML SDK / python-docx | Structure check | Contracts, design narratives, meeting minutes |
| **Investor Pitch / Presentation** | `pptx` | PPTD domain language / python-pptx | Slide verify | Investor decks, progress presentations |
| **Project Dashboard / Client Microsite** | `webapp-building` | React + TypeScript + Tailwind + shadcn/ui | Build + lint | Internal tools, client portals, progress trackers |
| **Full-Stack API + DB** | `backend-building` | FastAPI + PostgreSQL + tRPC/Drizzle | Test + deploy | Cerebrum backend, data ingestion APIs |
| **Drone QA/QC Report** | `image-pdf` | PIL + reportlab + OpenCV | Image integrity | Crack detection reports, progress photo logs |
| **BIM Attribute Export** | `ifc-xlsx` | IfcOpenShell + openpyxl | Schema validate | IFC quantity takeoffs, property sets |

---

## 3. SHARED VALIDATION LAYER (Mandatory for ALL Deliverables)

### 3.1 Pre-Flight Checklist (Before Creating Anything)

```bash
# Run in Termux / Codespace / Local
git pull origin main          # Ensure latest
git status                    # Clean working tree?
python --version              # Must be 3.10+
pip list | grep -E "openpyxl|pandas|reportlab|python-pptx"  # Core libs present?
```

### 3.2 Per-Artifact Validation Loop

```
FOR each artifact:
    1. PLAN   → Define structure, data sources, formulas, styling
    2. CREATE → Generate with primary tool
    3. SAVE   → Write to /mnt/agents/output/ or repo /deliverables/
    4. CHECK  → Run domain-specific validator (see §4-9)
    5. FIX    → Iterate 3-4 until zero errors
    6. COMMIT → git add + git commit + git push
    7. NEXT   → Only then proceed
```

### 3.3 Post-Delivery Gate

- All files must be committed to GitHub BEFORE sharing
- No direct Render shell edits (ephemeral filesystem)
- Every external data point requires citation (Source Name + Source URL)

---

## 4. XLSX SUB-SKILL — Construction BOQ & Finance

### 4.1 Technology Stack
- **Runtime:** Python 3.10+
- **Primary:** `openpyxl` (creation, styling, formulas)
- **Data:** `pandas` (manipulation, then export via openpyxl)
- **Validation:** Custom Xlsx CLI (see §4.3)

### 4.2 The 6 Validation Commands

| Tool | Command | What It Detects | Exit Code |
|------|---------|-----------------|-----------|
| `recheck` | `python scripts/xlsx_recheck.py file.xlsx` | #VALUE!, #DIV/0!, #REF!, #NAME?, zero-value cells | Must be 0 |
| `reference-check` | `python scripts/xlsx_refcheck.py file.xlsx` | Out-of-range refs, header-included refs, inconsistent patterns | Must be 0 |
| `inspect` | `python scripts/xlsx_inspect.py file.xlsx --pretty` | JSON structure of sheets, tables, headers, ranges | Info only |
| `chart-verify` | `python scripts/xlsx_chartverify.py file.xlsx` | Empty/broken charts with no data | Must be 0 |
| `validate` | `python scripts/xlsx_validate.py file.xlsx` | OpenXML schema compliance, absolute path errors, forbidden functions | Must be 0 |
| `pivot` | `python scripts/xlsx_pivot.py file.xlsx ...` | PivotTable creation via OpenXML SDK (run LAST, never re-open with openpyxl) | See pivot-table.md |

### 4.3 Formula Rules (Strict)
- **Excel formulas MANDATORY** for all calculations. Static values forbidden for derived outputs.
- **Color Coding:**
  - Blue font = Fixed input values
  - Black font = Calculation formulas
  - Green font = Cross-sheet references
  - Red font = External references
- **Forbidden Functions (Excel 2019 incompatible):** `FILTER`, `UNIQUE`, `SORT`, `SORTBY`, `XLOOKUP`, `XMATCH`, `SEQUENCE`, `LET`, `LAMBDA`, `RANDARRAY`, `ARRAYFORMULA`, `QUERY`, `IMPORTRANGE`

### 4.4 Style Systems

| Style | Use Case | Colors |
|-------|----------|--------|
| **Minimalist Monochrome** | General non-financial tasks | Black/White/Grey + Blue accent only |
| **Professional Finance** | All cost/fiscal work | Dark blue headers `#122B49`, warm accent `#FFF3E0`, grey backgrounds |
| **Construction BOQ** | Bill of Quantities | Green headers (cost), red flags (overrun), amber (pending) |

### 4.5 Cover Page Requirements (Every Deliverable)
- Report title (18-20pt, bold)
- 3-6 key metrics summary (total cost, variance, completion %)
- Sheet index with descriptions
- Notes & instructions
- Gridlines hidden

### 4.6 Financial Sub-Skills
- **3-Statement Model:** Income Statement / Balance Sheet / Cash Flow with balance checks
- **DCF:** NOPAT, UFCF, WACC, terminal value, sensitivity tables
- **Comps Analysis:** Public comps, trading multiples, valuation ranges
- **Rule:** All financial outputs must remain formula-linked. Pre-calculating in Python and pasting static values is **strictly prohibited**.

### 4.7 Construction-Specific Extensions
- **BOQ Structure:** Item No | Description | Unit | Quantity | Rate | Amount | Source | Status
- **Cost Codes:** Align with CSI MasterFormat (2020 edition) or project-specific WBS
- **Progress Tracking:** Planned vs Actual vs Earned Value columns
- **Drone Integration:** Photo reference column (filename → `./drone_photos/`)

---

## 5. PDF SUB-SKILL — Technical Reports & Data Sheets

### 5.1 Technology Stack
- **Primary:** HTML + CSS + Paged.js (print-to-PDF via headless Chrome/WeasyPrint)
- **Alternative:** LaTeX (Tectonic engine) for math-heavy reports
- **Math:** KaTeX for inline equations
- **Diagrams:** Mermaid.js → SVG → embedded

### 5.2 Validation
- `pdf-link-check` — All internal anchors resolve
- `pdf-image-check` — No broken image references
- `pdf-page-count` — Matches expected length

### 5.3 Construction Report Types
- **Method Statement:** Step-by-step, risk matrix, PPE requirements
- **QA/QC Report:** Inspection checklist, pass/fail, photo evidence, sign-off
- **Material Data Sheet:** 24-page technical spec (density, strength, compliance certs)
- **Progress Report:** Gantt snapshot, drone imagery, variance analysis

### 5.4 Style Rules
- A4 page size, 2cm margins
- Header: Project name + document title + page X of Y
- Footer: Revision date + confidentiality notice
- Table rows: alternating grey/white
- Photos: max width 100%, caption below

---

## 6. DOCX SUB-SKILL — Contracts & Narratives

### 6.1 Technology Stack
- **Primary:** `python-docx` for generation
- **Advanced:** C# + OpenXML SDK for tracked changes / complex formatting
- **Engine:** WIR editing engine for redline workflows

### 6.2 Validation
- `docx-structure-check` — Styles applied correctly (Heading 1, Normal, etc.)
- `docx-toc-check` — Table of contents updates correctly
- `docx-track-check` — If redlines present, all accepted/rejected properly

### 6.3 Construction Use Cases
- **Contract Amendments:** Clause numbering, party definitions, signature blocks
- **Design Narratives:** Concept explanation, reference standards, material justification
- **Meeting Minutes:** Attendees, actions (owner + due date), decisions

---

## 7. PPTX SUB-SKILL — Presentations & Pitches

### 7.1 Technology Stack
- **Primary:** `python-pptx` for programmatic generation
- **Advanced:** PPTD domain language for layout engine
- **Theme:** Corporate template with Cerebrum branding

### 7.2 Validation
- `pptx-slide-verify` — No empty placeholders
- `pptx-font-check` — All fonts embedded or standard
- `pptx-image-check` — No missing images

### 7.3 Slide Types
- **Title Slide:** Project name, date, presenter
- **Problem/Solution:** Before/after drone imagery
- **Market Size:** TAM/SAM/SOM with source citations
- **Traction:** Metrics table (live from xlsx if possible)
- **Team:** Org chart, roles
- **Financials:** Summary from 3-statement model
- **Ask:** Funding required, use of funds

---

## 8. WEBAPP SUB-SKILL — Dashboards & Client Portals

### 8.1 Technology Stack
- **Framework:** React 18 + TypeScript
- **Styling:** Tailwind CSS + shadcn/ui components
- **Build:** Vite
- **Backend:** FastAPI (see §9)

### 8.2 Validation
- `npm run build` — Must pass with zero errors
- `npm run lint` — No ESLint warnings
- `docker build` — Container builds successfully

### 8.3 Construction Dashboard Modules
- **Progress Tracker:** % complete by trade, Gantt view
- **QA/QC Log:** Defect list, status, responsible party, photo thumbnail
- **Drone Gallery:** Filter by date, location, defect type
- **BIM Viewer:** IFC model embed (if supported)
- **Document Library:** Searchable, tagged by discipline

---

## 9. BACKEND SUB-SKILL — APIs & Data Pipelines

### 9.1 Technology Stack
- **API:** FastAPI (Python) or Hono (Node)
- **ORM:** Drizzle ORM or SQLAlchemy 2.0
- **DB:** PostgreSQL (Render) or SQLite (local/Jetson)
- **Validation:** Pydantic v2
- **Auth:** JWT + RBAC (from Cerebrum security phase)

### 9.2 Validation
- `pytest` — All tests pass
- `alembic check` — Migrations in sync
- `docker-compose up` — Full stack boots
- `curl /health` — Returns 200 green

### 9.3 Construction API Endpoints
- `POST /api/drone/upload` — Accept drone imagery, run QA model
- `GET /api/bim/quantities` — Return IFC-derived BOQ
- `GET /api/progress` — Earned value metrics
- `POST /api/reports/generate` — Trigger xlsx/pdf generation
- `GET /api/health` — Must return green (hardcoded if needed for Render)

---

## 10. DOMAIN-SPECIFIC WORKFLOWS

### 10.1 Drone → QA/QC Report Pipeline
```
Drone Photos (JPG/RAW)
    ↓
OpenCV / YOLOv8 (defect detection: cracks, alignment)
    ↓
Results JSON (defect type, confidence, bbox, image_ref)
    ↓
PDF Report (reportlab) — photos + annotations + pass/fail
    ↓
XLSX Log (openpyxl) — defect register with formulas for trend analysis
    ↓
COMMIT to GitHub → Render serves download link
```

### 10.2 BIM → BOQ Pipeline
```
IFC Model
    ↓
IfcOpenShell (extract quantities: volume, area, count)
    ↓
Pandas DataFrame (CSI MasterFormat mapping)
    ↓
XLSX BOQ (openpyxl) — formulas for cost extension
    ↓
Validate (6 xlsx checks)
    ↓
COMMIT → Share with QS team
```

### 10.3 Progress → Dashboard Pipeline
```
Site data (daily logs, drone, BIM)
    ↓
FastAPI ingestion endpoint
    ↓
PostgreSQL (Render) or SQLite (Jetson local)
    ↓
React dashboard (Vite + Tailwind)
    ↓
Docker build → Deploy to Render / Orin
```

---

## 11. EXTERNAL DATA CITATION RULES

**Mandatory for ALL deliverables using external data:**

1. Two columns required in any tabular output:
   - `Source Name` (e.g., "RSMeans 2024", "Saudi Aramco Standard")
   - `Source URL` (e.g., `https://...` or `"Internal Document — Project X"`)
2. Forbidden: Delivering Excel/PDF with external data but no citations
3. Construction-specific sources to cite:
   - Cost data: RSMeans, Altus Group, local QS rates
   - Material specs: Manufacturer datasheets, ASTM/BS standards
   - Regulatory: Saudi Building Code, Diriyah UNESCO guidelines
   - Drone imagery: Date, GPS coordinates, equipment ID

---

## 12. HARDWARE ABSTRACTION LAYER (HAL)

Cerebrum must detect runtime environment and adapt:

| Environment | Detection | Adaptation |
|-------------|-----------|------------|
| **Cloud (Render)** | `RENDER=true` env var | PostgreSQL, full API, cloud LLM |
| **Jetson Orin** | `/etc/nv_tegra_release` exists | SQLite, local LLM (Tinker LoRA), ZVec vector DB |
| **Jetson Nano** | Same as above + memory < 8GB | Reduced model (Llama-3.2-1B), no heavy CV |
| **Termux (Android)** | `$PREFIX` contains `com.termux` | GitHub CLI operations, lightweight scripts only |
| **Windows 10** | `os.name == 'nt'` | Full Python stack, Docker Desktop |
| **GitHub Codespace** | `CODESPACE_NAME` env var | Dev environment, commit before deploy |

---

## 13. FORBIDDEN PATTERNS

| Anti-Pattern | Why Forbidden | Correct Approach |
|--------------|-------------|------------------|
| Editing in Render shell | Filesystem is ephemeral | Edit in Codespace → commit → push |
| Static values for derived outputs | Breaks audit trail | Excel formulas, SQL views, computed fields |
| Excel 365-only functions | Client may use Excel 2019 | Use `INDEX/MATCH`, `SUMIFS`, `OFFSET` |
| Hardcoding secrets in code | Security risk | `.env` file + GitHub Secrets |
| Skipping validation | Broken deliverables | 6-check loop mandatory |
| Cloud-only architecture | Site has no internet | Offline-first, local processing core |
| Manual chart data sheets | Not professional | Embedded charts via openpyxl |
| No source citations | Unverifiable data | Source Name + URL columns |

---

## 14. QUICK REFERENCE — Termux Commands

```bash
# Install dependencies
pkg install python git nodejs-lts
pip install openpyxl pandas reportlab python-pptx python-docx requests

# Clone / update Cerebrum
git clone https://github.com/bopoadz-del/Cerebrum-Blocks.git
cd Cerebrum-Blocks && git pull origin main

# Run validation suite
python scripts/xlsx_recheck.py deliverables/boq.xlsx
python scripts/xlsx_validate.py deliverables/boq.xlsx

# Deploy to Render (after commit)
git add . && git commit -m "deliverable: [type] [description]"
git push origin main
# Then: Render Dashboard → Manual Deploy → Clear Build Cache → Deploy
```

---

## 15. VERSION HISTORY

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-04-28 | Initial unified skill for Cerebrum agent |

---

> **End of Document**  
> **Next Step:** Pick a deliverable type (xlsx BOQ, pdf report, webapp dashboard) and run the per-sheet validation loop.
