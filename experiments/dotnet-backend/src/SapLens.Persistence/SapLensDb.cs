using Microsoft.EntityFrameworkCore;

namespace SapLens.Persistence;

public sealed class SapLensDb(DbContextOptions<SapLensDb> options) : DbContext(options)
{
    public DbSet<Dataset> Datasets => Set<Dataset>();
    public DbSet<DatasetRecord> DatasetRecords => Set<DatasetRecord>();
    public DbSet<Job> Jobs => Set<Job>();
    public DbSet<ReviewDecision> ReviewDecisions => Set<ReviewDecision>();
    public DbSet<ReviewInvalidation> ReviewInvalidations => Set<ReviewInvalidation>();
    public DbSet<BackupRecord> Backups => Set<BackupRecord>();

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
    }
}
