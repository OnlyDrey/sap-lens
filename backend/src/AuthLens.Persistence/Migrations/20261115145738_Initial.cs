using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace AuthLens.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class Initial : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "Backups",
                columns: table => new
                {
                    Id = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    Kind = table.Column<string>(type: "TEXT", nullable: false),
                    FileName = table.Column<string>(type: "TEXT", nullable: false),
                    Sha256 = table.Column<string>(type: "TEXT", nullable: false),
                    SizeBytes = table.Column<long>(type: "INTEGER", nullable: false),
                    Reason = table.Column<string>(type: "TEXT", nullable: true),
                    CreatedUtc = table.Column<DateTime>(type: "TEXT", nullable: false),
                    AdminConfirmedUtc = table.Column<DateTime>(type: "TEXT", nullable: true),
                    DeletedUtc = table.Column<DateTime>(type: "TEXT", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Backups", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "Datasets",
                columns: table => new
                {
                    Id = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    Source = table.Column<string>(type: "TEXT", maxLength: 16, nullable: false),
                    Revision = table.Column<int>(type: "INTEGER", nullable: false),
                    Status = table.Column<string>(type: "TEXT", maxLength: 16, nullable: false),
                    ContentHash = table.Column<string>(type: "TEXT", nullable: false),
                    RecordCount = table.Column<int>(type: "INTEGER", nullable: false),
                    FileName = table.Column<string>(type: "TEXT", nullable: true),
                    ReportJson = table.Column<string>(type: "TEXT", nullable: true),
                    EvaluationJson = table.Column<string>(type: "TEXT", nullable: true),
                    Error = table.Column<string>(type: "TEXT", nullable: true),
                    JobId = table.Column<long>(type: "INTEGER", nullable: true),
                    ConfirmedBy = table.Column<string>(type: "TEXT", nullable: true),
                    ConfirmedUtc = table.Column<DateTime>(type: "TEXT", nullable: true),
                    CreatedUtc = table.Column<DateTime>(type: "TEXT", nullable: false),
                    ActivatedUtc = table.Column<DateTime>(type: "TEXT", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Datasets", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "Jobs",
                columns: table => new
                {
                    Id = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    Kind = table.Column<string>(type: "TEXT", maxLength: 32, nullable: false),
                    Status = table.Column<string>(type: "TEXT", maxLength: 16, nullable: false),
                    PayloadJson = table.Column<string>(type: "TEXT", nullable: false),
                    IdempotencyKey = table.Column<string>(type: "TEXT", nullable: true),
                    Attempts = table.Column<int>(type: "INTEGER", nullable: false),
                    MaxAttempts = table.Column<int>(type: "INTEGER", nullable: false),
                    LeaseOwner = table.Column<string>(type: "TEXT", nullable: true),
                    LeaseExpiresUtc = table.Column<DateTime>(type: "TEXT", nullable: true),
                    NotBeforeUtc = table.Column<DateTime>(type: "TEXT", nullable: false),
                    Progress = table.Column<double>(type: "REAL", nullable: false),
                    ProgressText = table.Column<string>(type: "TEXT", nullable: true),
                    CancelRequested = table.Column<bool>(type: "INTEGER", nullable: false),
                    Error = table.Column<string>(type: "TEXT", nullable: true),
                    ResultJson = table.Column<string>(type: "TEXT", nullable: true),
                    CreatedUtc = table.Column<DateTime>(type: "TEXT", nullable: false),
                    StartedUtc = table.Column<DateTime>(type: "TEXT", nullable: true),
                    FinishedUtc = table.Column<DateTime>(type: "TEXT", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Jobs", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "DatasetRecords",
                columns: table => new
                {
                    Id = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    DatasetId = table.Column<long>(type: "INTEGER", nullable: false),
                    Ordinal = table.Column<int>(type: "INTEGER", nullable: false),
                    Payload = table.Column<string>(type: "TEXT", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_DatasetRecords", x => x.Id);
                    table.ForeignKey(
                        name: "FK_DatasetRecords_Datasets_DatasetId",
                        column: x => x.DatasetId,
                        principalTable: "Datasets",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "ReviewDecisions",
                columns: table => new
                {
                    Id = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    SubjectType = table.Column<string>(type: "TEXT", nullable: false),
                    SubjectKey = table.Column<string>(type: "TEXT", nullable: false),
                    EvidenceVersion = table.Column<string>(type: "TEXT", nullable: true),
                    Decision = table.Column<string>(type: "TEXT", nullable: false),
                    Reviewer = table.Column<string>(type: "TEXT", nullable: false),
                    Comment = table.Column<string>(type: "TEXT", nullable: false),
                    DatasetId = table.Column<long>(type: "INTEGER", nullable: false),
                    DecidedUtc = table.Column<DateTime>(type: "TEXT", nullable: false),
                    Hash = table.Column<string>(type: "TEXT", nullable: false),
                    PreviousHash = table.Column<string>(type: "TEXT", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_ReviewDecisions", x => x.Id);
                    table.ForeignKey(
                        name: "FK_ReviewDecisions_Datasets_DatasetId",
                        column: x => x.DatasetId,
                        principalTable: "Datasets",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "ReviewInvalidations",
                columns: table => new
                {
                    Id = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    AssignmentKey = table.Column<string>(type: "TEXT", nullable: false),
                    DatasetId = table.Column<long>(type: "INTEGER", nullable: false),
                    CreatedUtc = table.Column<DateTime>(type: "TEXT", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_ReviewInvalidations", x => x.Id);
                    table.ForeignKey(
                        name: "FK_ReviewInvalidations_Datasets_DatasetId",
                        column: x => x.DatasetId,
                        principalTable: "Datasets",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateIndex(
                name: "IX_Backups_Kind_CreatedUtc",
                table: "Backups",
                columns: new[] { "Kind", "CreatedUtc" });

            migrationBuilder.CreateIndex(
                name: "IX_DatasetRecords_DatasetId_Ordinal",
                table: "DatasetRecords",
                columns: new[] { "DatasetId", "Ordinal" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_Datasets_OneActivePerSource",
                table: "Datasets",
                column: "Source",
                unique: true,
                filter: "\"Status\" = 'Active'");

            migrationBuilder.CreateIndex(
                name: "IX_Datasets_Source_Revision",
                table: "Datasets",
                columns: new[] { "Source", "Revision" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_Datasets_Source_Status",
                table: "Datasets",
                columns: new[] { "Source", "Status" });

            migrationBuilder.CreateIndex(
                name: "IX_Jobs_IdempotencyKey",
                table: "Jobs",
                column: "IdempotencyKey",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_Jobs_Status_NotBeforeUtc",
                table: "Jobs",
                columns: new[] { "Status", "NotBeforeUtc" });

            migrationBuilder.CreateIndex(
                name: "IX_ReviewDecisions_DatasetId",
                table: "ReviewDecisions",
                column: "DatasetId");

            migrationBuilder.CreateIndex(
                name: "IX_ReviewDecisions_Hash",
                table: "ReviewDecisions",
                column: "Hash",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_ReviewDecisions_SubjectType_SubjectKey_DecidedUtc",
                table: "ReviewDecisions",
                columns: new[] { "SubjectType", "SubjectKey", "DecidedUtc" });

            migrationBuilder.CreateIndex(
                name: "IX_ReviewInvalidations_AssignmentKey_CreatedUtc",
                table: "ReviewInvalidations",
                columns: new[] { "AssignmentKey", "CreatedUtc" });

            migrationBuilder.CreateIndex(
                name: "IX_ReviewInvalidations_DatasetId",
                table: "ReviewInvalidations",
                column: "DatasetId");

            // Audit immutability enforced by SQLite itself, independent of application code: decisions and invalidations are append-only,
            // and staged dataset records never change.
            migrationBuilder.Sql(ImmutabilitySql.Create);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql(ImmutabilitySql.Drop);
            migrationBuilder.DropTable(
                name: "Backups");

            migrationBuilder.DropTable(
                name: "DatasetRecords");

            migrationBuilder.DropTable(
                name: "Jobs");

            migrationBuilder.DropTable(
                name: "ReviewDecisions");

            migrationBuilder.DropTable(
                name: "ReviewInvalidations");

            migrationBuilder.DropTable(
                name: "Datasets");
        }
    }
}
