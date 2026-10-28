# Segregation of Duties (SoD)

SoD turns an externally supplied risk matrix into **potential conflict evidence**
and a documented review trail. It is investigation support: a transaction mapping
does not prove effective SAP authorization, a confirmed violation or license use.
Methodology, schema and limits are defined once in the
[SoD matrix reference](../data/SOD_MATRIX.md); this page is the workflow.

## Workflow

1. **Import sources.** Load Role Catalogue and User–Role Mapping, then the SoD
   Matrix under Settings → Data Sources ([import](../data/IMPORT_AND_REFRESH.md),
   [synthetic example](../../examples/sod-matrix.example.csv)). The matrix is
   Static by default and restores from its snapshot after restart.
2. **Configure risks.** Settings → SoD Risk Configuration holds local enablement,
   business explanations and controls. Imported values stay separate from local text.
3. **Investigate.** SoD → Risk Catalogue (overview, export), User Conflicts and Role
   Conflicts. Filters and Saved Filters work as elsewhere; CSV exports use the same
   filters across all pages.
4. **Review.** SoD → Access Review records justified decisions with controls and
   actions. Each save appends history against an immutable evidence snapshot.
5. **Freeze a period.** SoD → Review Periods captures a named range and evaluation
   date, moves Draft → In review → Ready for approval → Approved/closed, and
   compares periods. Pending or outdated findings block approval; closed
   snapshots cannot change; refresh never alters a snapshot.
6. **Report.** SoD → Reports previews and exports DOCX (editable) or PDF from one
   frozen model. Approved status requires a closed period.

## Evidence rules

- Reviewer and approver names are self-reported, not verified identities or
  signatures. Use an external signing process for formal approval.
- Missing sources or coverage show as unavailable or "Not observed", never as
  resolved or zero.
- Source criticality labels (for example C/H) are shown literally; no severity
  dictionary is inferred.
- Private backups must include the review, period and snapshot stores. Portable
  configuration exports exclude them. Never commit real exports; use synthetic data.

API routes: [SoD API](../architecture/API.md#sod-api). Validation evidence and
open native acceptance items: [SoD validation](../archive/validation/SOD_VALIDATION.md).
