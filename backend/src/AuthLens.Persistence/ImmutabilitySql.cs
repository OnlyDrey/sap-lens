namespace AuthLens.Persistence;

public static class ImmutabilitySql
{
    public const string Create = """
        CREATE TRIGGER ReviewDecisions_NoUpdate BEFORE UPDATE ON ReviewDecisions BEGIN SELECT RAISE(ABORT, 'review decisions are immutable'); END;
        CREATE TRIGGER ReviewDecisions_NoDelete BEFORE DELETE ON ReviewDecisions BEGIN SELECT RAISE(ABORT, 'review decisions are immutable'); END;
        CREATE TRIGGER ReviewInvalidations_NoUpdate BEFORE UPDATE ON ReviewInvalidations BEGIN SELECT RAISE(ABORT, 'review invalidations are immutable'); END;
        CREATE TRIGGER ReviewInvalidations_NoDelete BEFORE DELETE ON ReviewInvalidations BEGIN SELECT RAISE(ABORT, 'review invalidations are immutable'); END;
        CREATE TRIGGER DatasetRecords_NoUpdate BEFORE UPDATE ON DatasetRecords BEGIN SELECT RAISE(ABORT, 'dataset records are immutable'); END;
        CREATE TRIGGER Datasets_ActiveImmutableContent BEFORE UPDATE OF ContentHash, RecordCount, Source, Revision ON Datasets
            WHEN OLD.Status IN ('Active', 'Retired') BEGIN SELECT RAISE(ABORT, 'activated dataset content is immutable'); END;
        CREATE TRIGGER Datasets_NoDeleteActivated BEFORE DELETE ON Datasets
            WHEN OLD.Status IN ('Active', 'Retired') BEGIN SELECT RAISE(ABORT, 'activated datasets are kept as evidence'); END;
        """;

    public const string Drop = """
        DROP TRIGGER IF EXISTS ReviewDecisions_NoUpdate; DROP TRIGGER IF EXISTS ReviewDecisions_NoDelete;
        DROP TRIGGER IF EXISTS ReviewInvalidations_NoUpdate; DROP TRIGGER IF EXISTS ReviewInvalidations_NoDelete;
        DROP TRIGGER IF EXISTS DatasetRecords_NoUpdate; DROP TRIGGER IF EXISTS Datasets_ActiveImmutableContent; DROP TRIGGER IF EXISTS Datasets_NoDeleteActivated;
        """;
}
