# SAP Role Access Visualizer — Technical Architecture

## System Overview

Three-tier web application for SAP role browsing and comparison.

```
┌─────────────────────────────────────────────────────────────────┐
│                      WINDOWS WORKSTATION                         │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────┐        ┌────────────────────────────┐ │
│  │   sap_roles.csv      │        │   React Frontend           │ │
│  │   (UNC network path) │        │   Port 5173/5174           │ │
│  └──────────┬───────────┘        └────────────┬───────────────┘ │
│             │ pandas.read_csv()               │ HTTP/JSON REST  │
│             ▼                                 ▼                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         FastAPI Backend  ·  Port 8000                    │   │
│  │  config.py → cache.py → routers/ → models.py            │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow

```
CSV File → pandas.read_csv() → row-by-row assembly → RoleDetail objects
         → atomic _cache swap → API endpoints → React components
```

## Key Design Decisions

| Decision | Rationale |
|---|---|
| In-memory cache | Sub-millisecond responses; role data changes rarely |
| CSV over direct SQL | No Service Principal / Azure AD app registration needed |
| Atomic cache swap | Thread-safe — readers never see partial data |
| `asyncio.to_thread()` | pyodbc/pandas are sync; keeps FastAPI async |

## Module map

BC · CO · FI · HR · MM · PM · PP · PS · QM · SD · WM
