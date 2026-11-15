# Dependency mapping: Python v1 runtime dependencies to .NET

Classification: **1** straightforward replacement, **2** needs a .NET alternative or redesign, **3** worth keeping as an isolated Python
component. Source: `backend/requirements.txt`, `backend/requirements-desktop.txt` and their use in code. "Prototype" says what this branch
actually implemented.

| Python dependency | Used for in v1 | Class | .NET replacement | Prototype |
| --- | --- | --- | --- | --- |
| fastapi, starlette | HTTP API, routing, dependencies | 1 | ASP.NET Core minimal APIs (in-box) | Implemented |
| uvicorn | ASGI server | 1 | Kestrel (in-box) | Implemented |
| pydantic, pydantic-settings | Request/settings validation, JSON stores | 1 | System.Text.Json + explicit validation; Options pattern | Implemented for the API surface ported |
| python-multipart | Browser CSV upload | 1 | Request body streaming (in-box) | Implemented (raw body upload, 128 MiB cap) |
| charset-normalizer | Encoding fallback support | 1 | `System.Text.Encoding` + `CodePagesEncodingProvider` (cp1252) | Implemented (same BOM/UTF-8/cp1252 order as v1) |
| csv (stdlib) incl. `csv.Sniffer` | CSV parsing, delimiter detection | 2 | Own RFC 4180 reader + verbatim port of CPython `Sniffer` | Implemented, equivalence-tested |
| sqlite3 (stdlib) | Rebuildable cache, revisions | 1 | Microsoft.Data.Sqlite + EF Core SQLite | Implemented (now system of record) |
| hashlib, json (canonical) | Finding identities, evidence versions | 2 | SHA-256 in-box; custom canonical JSON writer reproducing Python `json.dumps` | Implemented, byte-identical |
| argon2-cffi | Server password hashing (Argon2id) | 2 | No in-box Argon2. Options: Konscious.Security.Cryptography.Argon2 or libsodium binding (third-party, native or managed); or PBKDF2 (in-box) for new hashes with Argon2 verification during migration | Not implemented |
| cryptography | AES-256-GCM portable backups | 1 | `System.Security.Cryptography.AesGcm` (in-box) | Not implemented (SQLite online backup only) |
| tzdata | IANA zones for schedules on Windows | 1 | .NET uses ICU / Windows zone data; `TimeZoneInfo.FindSystemTimeZoneById` accepts IANA ids on Windows with ICU | Not needed by the prototype |
| python-docx, lxml | SoD DOCX reports | 2/3 | DocumentFormat.OpenXml (Microsoft, MIT) for DOCX; or keep Python as an isolated report renderer fed by the frozen JSON model | Not implemented |
| reportlab | SoD PDF reports | 2/3 | QuestPDF (community licence terms apply) or PdfSharp/MigraDoc (MIT); or isolated Python renderer | Not implemented |
| Pillow | Logo/branding image validation | 2 | SixLabors.ImageSharp (licence terms) or format sniffing + size limits only | Not implemented |
| pywebview | Desktop window | 1 | WebView2 WinForms control (Microsoft.Web.WebView2) | Implemented (Windows-only, built not run) |
| opentelemetry-api | Transitive pin only | 1 | Not required; ASP.NET Core exposes OpenTelemetry natively if wanted | n/a |
| PyInstaller (build) | Desktop one-file, Server one-dir | 1 | `dotnet publish --self-contained` (single-file for Desktop) | Implemented |

## Remaining Python

- **Core (import, analysis, API, storage, jobs): no Python runtime required.** The .NET server and desktop builds contain no Python. [M]
- **Reports are the only defensible candidate for class 3.** If DOCX/PDF output must stay pixel-identical to v1 for audit continuity, an
  isolated renderer that receives the frozen report model as JSON and returns a file keeps the proven code. That reintroduces a Python
  runtime and a second signed component on Windows, so it should be a deliberate, temporary choice. Recommended default: re-implement
  with OpenXML and a PDF library and accept that report layout changes once, with the frozen data model (not the rendering) as the
  audit artifact.
- **Developer tooling** (equivalence harness, synthetic data generation, benchmarks) stays Python while v1 is the reference. That is a
  test-time dependency only.

## Licensing notes to settle before adoption

QuestPDF and ImageSharp have commercial-use terms; OpenXML SDK, PdfSharp and Konscious Argon2 are MIT. No third-party package beyond
Microsoft's EF Core, ASP.NET Core, Data.Sqlite, WebView2 and xUnit was added to the prototype.
