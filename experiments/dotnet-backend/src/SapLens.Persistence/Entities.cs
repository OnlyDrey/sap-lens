namespace SapLens.Persistence;

public static class DatasetStatus
{
    public const string Staged = "Staged", Held = "Held", Active = "Active", Retired = "Retired", Discarded = "Discarded", Failed = "Failed";
}

/// <summary>One revision of one source (roles, users, sod). At most one Active revision per source (unique filtered index).</summary>
public sealed class Dataset
{
    public long Id { get; set; }
    public required string Source { get; set; }
    public int Revision { get; set; }
    public required string Status { get; set; }
    public string ContentHash { get; set; } = "";
    public int RecordCount { get; set; }
    public string? FileName { get; set; }
    public string? ReportJson { get; set; }
    public string? EvaluationJson { get; set; }
    public string? Error { get; set; }
    public long? JobId { get; set; }
    public string? ConfirmedBy { get; set; }
    public DateTime? ConfirmedUtc { get; set; }
    public DateTime CreatedUtc { get; set; }
    public DateTime? ActivatedUtc { get; set; }
    public List<DatasetRecord> Records { get; set; } = [];
}

/// <summary>A canonical source record (the mapped CSV row) as JSON. Records of a dataset are immutable once staged.</summary>
public sealed class DatasetRecord
{
    public long Id { get; set; }
    public long DatasetId { get; set; }
    public int Ordinal { get; set; }
    public required string Payload { get; set; }
}

public static class JobStatus
{
    public const string Queued = "Queued", Running = "Running", Completed = "Completed", Failed = "Failed", Cancelled = "Cancelled";
}

/// <summary>A persistent background job. A worker owns it through a lease; completion is fenced by the lease owner so a stale worker cannot
/// complete or fail a job another worker re-claimed after a restart.</summary>
public sealed class Job
{
    public long Id { get; set; }
    public required string Kind { get; set; }
    public required string Status { get; set; }
    public string PayloadJson { get; set; } = "{}";
    public string? IdempotencyKey { get; set; }
    public int Attempts { get; set; }
    public int MaxAttempts { get; set; } = 3;
    public string? LeaseOwner { get; set; }
    public DateTime? LeaseExpiresUtc { get; set; }
    public DateTime NotBeforeUtc { get; set; }
    public double Progress { get; set; }
    public string? ProgressText { get; set; }
    public bool CancelRequested { get; set; }
    public string? Error { get; set; }
    public string? ResultJson { get; set; }
    public DateTime CreatedUtc { get; set; }
    public DateTime? StartedUtc { get; set; }
    public DateTime? FinishedUtc { get; set; }
}

/// <summary>Append-only review decision. UPDATE and DELETE are rejected by database triggers; each row carries a hash chained to the previous one.</summary>
public sealed class ReviewDecision
{
    public long Id { get; set; }
    public required string SubjectType { get; set; } // "assignment" or "sod_finding"
    public required string SubjectKey { get; set; }  // assignment key, or finding id
    public string? EvidenceVersion { get; set; }
    public required string Decision { get; set; }
    public required string Reviewer { get; set; }
    public string Comment { get; set; } = "";
    public long DatasetId { get; set; }
    public DateTime DecidedUtc { get; set; }
    public required string Hash { get; set; }
    public string? PreviousHash { get; set; }
}

/// <summary>Append-only: an assignment key disappeared when a users revision was activated. A decision older than the invalidation no longer applies.</summary>
public sealed class ReviewInvalidation
{
    public long Id { get; set; }
    public required string AssignmentKey { get; set; }
    public long DatasetId { get; set; }
    public DateTime CreatedUtc { get; set; }
}

public static class BackupKind
{
    public const string Automatic = "automatic", Manual = "manual", Migration = "migration";
}

public sealed class BackupRecord
{
    public long Id { get; set; }
    public required string Kind { get; set; }
    public required string FileName { get; set; }
    public required string Sha256 { get; set; }
    public long SizeBytes { get; set; }
    public string? Reason { get; set; }
    public DateTime CreatedUtc { get; set; }
    public DateTime? AdminConfirmedUtc { get; set; }
    public DateTime? DeletedUtc { get; set; }
}
