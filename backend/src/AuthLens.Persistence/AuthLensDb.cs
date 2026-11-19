using Microsoft.EntityFrameworkCore;

namespace AuthLens.Persistence;

public sealed class AuthLensDb(DbContextOptions<AuthLensDb> options) : DbContext(options)
{
    public DbSet<Dataset> Datasets => Set<Dataset>();
    public DbSet<DatasetRecord> DatasetRecords => Set<DatasetRecord>();
    public DbSet<Job> Jobs => Set<Job>();
    public DbSet<ReviewDecision> ReviewDecisions => Set<ReviewDecision>();
    public DbSet<ReviewInvalidation> ReviewInvalidations => Set<ReviewInvalidation>();
    public DbSet<BackupRecord> Backups => Set<BackupRecord>();
    public DbSet<SettingsDocument> Settings => Set<SettingsDocument>();
    public DbSet<RefreshReport> RefreshReports => Set<RefreshReport>();
    public DbSet<SavedFilter> SavedFilters => Set<SavedFilter>();
    public DbSet<SodDocument> SodDocuments => Set<SodDocument>();
    public DbSet<SodDecisionRecord> SodDecisionEvents => Set<SodDecisionRecord>();
    public DbSet<SodEvidenceSnapshot> SodEvidenceSnapshots => Set<SodEvidenceSnapshot>();

    protected override void OnModelCreating(ModelBuilder model)
    {
        model.Entity<Dataset>(e =>
        {
            e.Property(x => x.Source).HasMaxLength(16);
            e.Property(x => x.Status).HasMaxLength(16);
            e.HasIndex(x => new { x.Source, x.Status });
            e.HasIndex(x => new { x.Source, x.Revision }).IsUnique();
            // The single-writer invariant in data: one active revision per source, enforced by SQLite itself.
            e.HasIndex(x => x.Source).IsUnique().HasFilter("\"Status\" = 'Active'").HasDatabaseName("IX_Datasets_OneActivePerSource");
            e.HasMany(x => x.Records).WithOne().HasForeignKey(r => r.DatasetId).OnDelete(DeleteBehavior.Cascade);
        });
        model.Entity<DatasetRecord>(e => e.HasIndex(x => new { x.DatasetId, x.Ordinal }).IsUnique());
        model.Entity<Job>(e =>
        {
            e.Property(x => x.Kind).HasMaxLength(32);
            e.Property(x => x.Status).HasMaxLength(16);
            e.HasIndex(x => new { x.Status, x.NotBeforeUtc });
            e.HasIndex(x => x.IdempotencyKey).IsUnique();
        });
        model.Entity<ReviewDecision>(e =>
        {
            e.HasIndex(x => new { x.SubjectType, x.SubjectKey, x.DecidedUtc });
            e.HasIndex(x => x.Hash).IsUnique();
            e.HasOne<Dataset>().WithMany().HasForeignKey(x => x.DatasetId).OnDelete(DeleteBehavior.Restrict);
        });
        model.Entity<ReviewInvalidation>(e =>
        {
            e.HasIndex(x => new { x.AssignmentKey, x.CreatedUtc });
            e.HasOne<Dataset>().WithMany().HasForeignKey(x => x.DatasetId).OnDelete(DeleteBehavior.Restrict);
        });
        model.Entity<BackupRecord>(e => e.HasIndex(x => new { x.Kind, x.CreatedUtc }));
        model.Entity<SettingsDocument>(e => { e.Property(x => x.Id).ValueGeneratedNever(); e.Property(x => x.Revision).IsConcurrencyToken(); });
        model.Entity<RefreshReport>(e => { e.Property(x => x.Id).HasMaxLength(32); e.HasIndex(x => x.TimestampUtc); });
        model.Entity<SodDecisionRecord>(e =>
        {
            e.ToTable("SodDecisionEvents");
            e.HasKey(x => x.Seq);
            e.HasIndex(x => x.EventId).IsUnique();
            e.HasIndex(x => x.Hash).IsUnique();
            e.HasIndex(x => new { x.Context, x.Kind, x.Key, x.Seq });
            e.Property(x => x.EventId).HasMaxLength(32);
            e.Property(x => x.Context).HasMaxLength(64);
            e.Property(x => x.Kind).HasMaxLength(16);
            e.Property(x => x.Key).HasMaxLength(64);
        });
        model.Entity<SodEvidenceSnapshot>(e => { e.HasKey(x => x.Sha256); e.Property(x => x.Sha256).HasMaxLength(64); });
        model.Entity<SodDocument>(e => { e.HasKey(x => x.Name); e.Property(x => x.Name).HasMaxLength(32); e.Property(x => x.Revision).IsConcurrencyToken(); });
        model.Entity<SavedFilter>(e =>
        {
            e.Property(x => x.Id).HasMaxLength(64);
            e.Property(x => x.View).HasMaxLength(32);
            e.HasIndex(x => new { x.View, x.NameKey }).IsUnique();
            e.HasIndex(x => x.Sequence).IsUnique();
        });
    }
}
