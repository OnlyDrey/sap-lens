<!-- LOGO -->
<h1>
<p align="center">
  <img src="assets/sap-lens.png" alt="Logo" width="200">
  <br>SAP Lens
</h1>
  <p align="center">
    <b>SAP S/4HANA</b> · Role analysis and comparison tool for Company's internal SAP authorisation landscape.
    <br />
  </p>
</p>

---

## Overview

SAP Lens is an internal web application that lets SAP administrators and auditors **explore, filter, and compare composite roles** from the Company SAP S/4HANA system. It provides instant visibility into role structure, T-code assignments, and single role overlap between composite roles — without needing direct SAP GUI access.

### Key capabilities

| Feature | Description |
|---|---|
| **Role browser** | 73 composite roles filterable by module, searchable by name/description, sortable by name or T-code count |
| **Role detail** | Full single role breakdown per composite, with T-code drill-down per single role |
| **Role comparison** | Side-by-side comparison of 2–5 roles: single role overlap matrix, shared/exclusive building blocks, T-code overlap |
| **Module icons** | All 10 confirmed SAP modules (FI, CO, MM, SD, PP, PM, CA, HR, WM, PS) with distinct icons and colours |
| **Dark / Light theme** | Full theme toggle |
| **Live data refresh** | Reload role data from the source CSV without restarting the server |

---

## Architecture

```
sap-role-checker/
├── backend/                  # FastAPI Python API
│   ├── main.py               # App entry point, startup cache load
│   ├── cache.py              # In-memory role cache built from CSV
│   ├── models.py             # Pydantic data models
│   └── routers/
│       ├── roles.py          # GET /api/roles, GET /api/roles/{agr_name}
│       ├── modules.py        # GET /api/modules
│       └── compare.py        # POST /api/compare
│
└── frontend/                 # React + TypeScript + Vite
    └── src/
        ├── api/              # Axios client + TypeScript types
        ├── hooks/            # TanStack Query hooks (useRoles, useRoleDetail, useComparison)
        ├── components/
        │   ├── RoleList/     # Home page: RoleList.tsx, RoleCard.tsx
        │   ├── RoleDetail/   # Sidebar panel: RoleDetailPanel.tsx
        │   └── RoleComparison/ # ComparisonView.tsx
        └── AppLayout.tsx     # Header (Company branding), footer, theme
```

**Data flow:**
1. On startup, `cache.py` loads `sap_roles.csv` from the network share into memory
2. FastAPI serves the role data via a REST API
3. React fetches all 73 roles **once** on page load; all filtering, searching, and sorting happen client-side (instant, no round-trips per filter click)
4. Role detail and comparison results are fetched on demand

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12 · FastAPI · Pydantic v2 · Uvicorn |
| Frontend | React 18 · TypeScript · Vite · Tailwind CSS |
| UI components | Radix UI (Checkbox, ScrollArea) · Lucide React icons |
| Data fetching | TanStack Query v5 (React Query) |
| HTTP client | Axios |

---

## Data Source

Roles are loaded from a CSV file on the Company network share:

```
//YOUR-SERVER/YOUR-SHARE/path/to/sap_roles.csv
```

The CSV is produced by Power Automate and contains SAP AGR_AGRS data (composite roles and their single role children, with T-code assignments). The path is configured in `backend/cache.py`.

---

## Running the Application

### Prerequisites

- Python 3.12+
- Node.js 18+
- Access to the Company network share (for live data)

### 1 — Backend

```powershell
cd sap-role-checker\backend
py -m pip install -r requirements.txt
py -m uvicorn main:app --reload --port 8000
```

API runs at `http://127.0.0.1:8000`. Swagger docs at `http://127.0.0.1:8000/docs`.

### 2 — Frontend

```powershell
cd sap-role-checker\frontend
npm install
npm run dev
```

App runs at `http://localhost:5173`.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/roles` | List all role summaries. Optional: `?function_key=CO&search=manager` |
| `GET` | `/api/roles/{agr_name}` | Full detail for one composite role (single roles + T-codes) |
| `GET` | `/api/modules` | List of SAP module codes and names |
| `POST` | `/api/compare` | Compare 2–5 roles. Body: `["ZC:CO:...", "ZC:FI:..."]` |
| `POST` | `/api/refresh` | Reload the CSV cache from the network share |
| `GET` | `/api/health` | Health check + cache status |

---

## Module Map

All 10 modules confirmed from live SAP data (SQL query against `AGR_AGRS`):

| Code | Module | Icon | Colour |
|---|---|---|---|
| FI | Finance | DollarSign | `#3d4d8a` |
| CO | Controlling | BarChart2 | `#5a0090` |
| MM | Materials Management | Package | `#c44d10` |
| SD | Sales & Distribution | TrendingUp | `#1d5a6e` |
| PP | Production Planning | Cog | `#1a4d28` |
| PM | Plant Maintenance | Wrench | `#9a6c00` |
| CA | Cross-Application | Layers | `#4a5568` |
| HR | Human Resources | Users | `#162340` |
| WM | Warehouse Management | Warehouse | `#0a3848` |
| PS | Project System | FolderKanban | `#1e2d78` |

---

## Features In Detail

### Role Browser (Home)
- Module filter pills (e.g. `FI – Finance (16)`) — instant client-side filter, no network call per click
- Full-text search across role name, description, and AGR_NAME
- Sort by: Name A–Z / Z–A, Most T-codes, Fewest T-codes, Most single roles
- Role cards show: module icon + name, role title, AGR_NAME, single role count, T-code count
- Circle `+` button adds role to comparison (up to 5); turns orange with checkmark when selected
- "Compare now" floating bar appears when 2+ roles are selected

### Role Detail Sidebar
- Opens on "View details" or card click; press Esc or click backdrop to close
- Summary stats: single role count (left) + T-code count (right)
- Lists all single roles with module icon, AGR_NAME, description, T-code count badge (⚡ N)
- Expand any single role row to see full T-CODE / DESCRIPTION table

### Role Comparison
- **Insight bar**: average single role overlap %, T-code overlap %, most similar pair, most distinct pair
- **Single role overlap matrix**: colour-coded heatmap (5 discrete bands). Click any cell to see which single roles are shared between that pair
- **Shared by all roles**: single roles present in every selected composite
- **Exclusive single roles per composite**: single roles unique to each composite, expandable to show T-codes
- All rows use sidebar-style design: module icon · chevron · AGR_NAME · description · ⚡ T-code count

---

## Maintenance Scripts

A set of numbered PowerShell scripts (`01_*.ps1` … `28_*.ps1`) in the project root serve as an audit trail of all incremental changes made to the application. To re-apply any change:

```powershell
powershell.exe -ExecutionPolicy Bypass -File ".\27_rolelist_clientside_filter.ps1"
```

All scripts use `[System.IO.File]::WriteAllText` with UTF-8 (no BOM) encoding to avoid PowerShell 5 character corruption issues with Unicode content.

---

## Known Constraints

- **Network dependency**: the CSV must be reachable at startup. If the share is unavailable the cache will be empty — use "Refresh Data" once the share is accessible.
- **Single user / no authentication**: intended for internal use on the Company network only.
- **Read-only**: the app reads SAP data but does not write back to any SAP system.

---

## Contact

Internal tool — Company  
SAP authorisation questions: refer to the SAP Role Owner matrix in SharePoint.
