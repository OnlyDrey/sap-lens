# Reporting architecture: PDF, DOCX and image processing (decision 2026-11-17)

Decision record for MIG-001 (branding), MIG-018 (SoD reports) and the blockers BLK-IMAGE and BLK-REPORTS of the
[migration matrix](MIGRATION_MATRIX.md). Evidence: the proof of concept in `src/SapLens.Documents`, `tests/SapLens.Tests/ReportingTests.cs`
and `tools/reporting_reference.py` (Python v1 reference on the same synthetic models and images).

## Decision

| Capability | Decision | Library (licence) |
| --- | --- | --- |
| PDF | Native .NET | SkiaSharp 3.119.1 PDF backend (MIT) with a small flow layout (`PdfReportRenderer`) and the bundled Bitstream Vera fonts v1 already ships through ReportLab |
| DOCX | Native .NET | DocumentFormat.OpenXml 3.3.0 (MIT) (`DocxReportRenderer`) |
| Images | Native .NET | SkiaSharp 3.119.1 (MIT) plus SkiaSharp.NativeAssets.Linux.NoDependencies (MIT) (`ImageSanitizer`) |

No Python worker. The renderers sit behind `IReportRenderer` in their own project (`SapLens.Documents`): no data access, no SoD logic, no HTTP; the
API passes a frozen report model and an already validated logo and receives bytes.

## What v1 actually contains

| v1 code | Size | Dependency (version, licence) | Reusable as-is? |
| --- | --- | --- | --- |
| `sod_reports.render_pdf` | ~45 lines | ReportLab 5.1.0 (BSD) | Only through a Python runtime |
| `sod_reports.render_docx` | ~40 lines | python-docx 1.2.0 (MIT) with lxml 6.1.3 (BSD) | Only through a Python runtime |
| `branding.sanitize_image`, `report_branding` | ~70 lines | Pillow 13.0.0 (MIT-CMU) | Only through a Python runtime |
| `sod_reports.model`, `remediation_model` (frozen report models, checksums, statuses, sections) | ~300 lines | SoD scope, periods, decisions | No: SoD business logic, belongs in .NET (BLK-SOD-SCOPE) |

The reusable part is about 155 lines of rendering and sanitizing; everything that decides what a report says is SoD logic that must live in .NET
whatever the renderer.

## Options compared

| Criterion | A: native .NET (chosen) | B: Python worker (ReportLab, python-docx, Pillow) | C: selective hybrid |
| --- | --- | --- | --- |
| Functional compatibility with v1 | Same content, page count, metadata, header/footer, table header repetition, font and coverage rule on every PoC model; layout drawn by our code (minor typographic differences) | Byte-for-byte v1 output | PDF by Python only: same trade-off as B for one capability |
| Development effort | ~550 lines C# (done, with tests) | Worker protocol, packaging per OS, sandboxing, update process; plus the same .NET model code | Both efforts |
| Runtime complexity | In-process library calls | Second process per request or a pool: start-up, timeouts, cancellation, memory limits, crash isolation | Both |
| Packaging | One native library beside the executable (`libSkiaSharp.so` 9.0 MB, `libSkiaSharp.dll` 11.4 MB), the same pattern as `e_sqlite3` | Frozen CPython plus Pillow, ReportLab, python-docx and lxml (about 46 MB of packages, roughly 60-80 MB frozen per OS), separate signing on Windows | Both |
| Deployment and upgrade | Unchanged: one release folder, Windows service and systemd units as today | Worker files and versions must match the server; extra files to protect from tampering | Both |
| Performance | PoC renders the 400-row, 13-page report in well under a second in-process | Process start-up per report (or a pool to manage) | - |
| Security | Untrusted images decoded by Skia (widely deployed, fuzzed); no extra process, no IPC surface | Pillow and lxml are native parsers with a frequent CVE cadence that SAP Lens 2 would have to patch itself | - |
| Dependency maintenance | Two NuGet packages (+ native assets), NuGet audit on every build | A second ecosystem (pip, CPython) with its own audit and update cadence | Both ecosystems |
| Licensing | MIT throughout; Bitstream Vera font licence allows bundling | BSD/MIT; acceptable, but CPython redistribution adds the PSF licence | - |
| Long-term maintainability | One language, one test suite | Two languages for one feature | Worst of both |

Rejected libraries and why:

- **QuestPDF**: free (Community MIT) only for organisations below the vendor's revenue threshold; otherwise a paid licence. A licensing decision we
  avoid.
- **PDFsharp/MigraDoc**: 6.2.4 is MIT but depends on `System.Security.Cryptography.Pkcs` 8.0.1 with known moderate and high vulnerabilities
  (NuGet audit fails the build); 6.5.0 and later are AGPL-3.0. No maintained permissive version.
- **ImageSharp**: Six Labors Split Licence; Apache 2.0 only as a transitive dependency or under the vendor's conditions, a commercial licence
  otherwise.
- **System.Drawing**: Windows-only.

## Proof-of-concept results

Run on Linux (`ReportingTests`, 10 tests; reference written by `tools/reporting_reference.py` from v1 on the same inputs):

| Check | Result |
| --- | --- |
| PDF page count vs v1 (standard, 400-row table, empty, Unicode) | 2/2, 13/13, 2/2, 2/2 |
| PDF words vs v1 (poppler `pdftotext`, independent parser) | Identical word multisets (footer and page numbers excluded) |
| PDF metadata (title, author via `pdfinfo`) | Equal to v1 |
| PDF fonts (`pdffonts`) | Bitstream Vera Roman/Bold, embedded subsets (v1: same family, embedded) |
| Characters outside the font (emoji, CJK) | 422 with v1's message (DOCX accepts them, as v1) |
| PDF and DOCX reproducibility | Identical bytes for an identical frozen model (fixed dates, ordered DOCX entries, fixed relationship ids, explicit `docProps/core.xml`) |
| DOCX structure vs v1 (python-docx on v1 output; Open XML SDK on ours; python-docx also opened every .NET file) | Same paragraphs, tables, header, title, author, image count; header rows repeat; PAGE field in the footer |
| Images: 26 cases (PNG, JPEG with EXIF, WebP, animated GIF and WebP, corrupt, truncated, oversized file, oversized and tiny dimensions, SVG) for the logo and report profiles | Same accept/refuse verdicts and messages as v1; same output dimensions (Pillow thumbnail arithmetic ported); output is an RGBA PNG with only IHDR/IDAT/IEND (and `sBIT`, written by the encoder) chunks; reproducible |
| Visual comparison (rendered with `pdftoppm`) | Same page structure, table styling, header shading, wrapping and footer; typographic details (exact line breaks) differ slightly |

Packaging (Linux run; native Windows acceptance not run, no Windows machine):

| Check | Result |
| --- | --- |
| `dotnet publish` linux-x64 and win-x64 single-file | Builds; `libSkiaSharp.so` / `libSkiaSharp.dll` beside the executable like `e_sqlite3` |
| Linux native dependencies of `libSkiaSharp.so` | libc, libm, libpthread, libdl only (no fontconfig: the NoDependencies variant) |
| Published Linux server without Python | Report logo upload decoded and re-encoded through the release binary |
| Release scripts and verifier | Expected file lists updated (`build-release.sh`, `build-release.ps1`, `PublishTests`) |
| Windows | Cross-published only; loading `libSkiaSharp.dll` in the Windows service and Desktop is part of the pending Windows acceptance |

Differences that need a person to look at once a real report model exists: line-break positions in long paragraphs and table cells, the cover
title size, and Word's rendering of the generated table style (python-docx used the template style "Light Shading Accent 1"; ours defines an
equivalent table style with header shading and rules).

## Security and operation

- Images: content-type detection from the bytes, size limit before decoding, dimension and frame checks from the header before pixel decoding,
  full decode into a fresh RGBA buffer, re-encode without metadata; truncated or corrupt streams are refused, never padded.
- Logos are content-addressed (`<data>/branding/<sha256>.png`) and re-validated on every read; a Server never reads a path a browser names;
  logos travel only in private configuration exports.
- Reports render from the frozen model only; rendering is serialized (as v1's lock), bounded to 32 MiB, and failures map to v1's 422/413 messages.
- No temporary files, no network service, no user-supplied code; fonts are embedded resources.

## Updating the dependencies

SkiaSharp and DocumentFormat.OpenXml are pinned in `src/SapLens.Documents/SapLens.Documents.csproj`. NuGet audit runs on every build and fails it
on known vulnerabilities (`TreatWarningsAsErrors`). After an update: `ReportingTests`, `BrandingTests`, `PublishTests` and a release build.

## What remains

The SoD report models (`sod_reports.model`, `remediation_model`) and the report routes depend on review periods and scope (BLK-SOD-SCOPE); the
renderers are ready for them. Native Windows acceptance of the native library in the service and Desktop is pending.
