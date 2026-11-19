using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace AuthLens.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class SodDecisionEvents : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "SodDecisionEvents",
                columns: table => new
                {
                    Seq = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    EventId = table.Column<string>(type: "TEXT", maxLength: 32, nullable: false),
                    Context = table.Column<string>(type: "TEXT", maxLength: 64, nullable: false),
                    Kind = table.Column<string>(type: "TEXT", maxLength: 16, nullable: false),
                    Key = table.Column<string>(type: "TEXT", maxLength: 64, nullable: false),
                    Json = table.Column<string>(type: "TEXT", nullable: false),
                    PreviousHash = table.Column<string>(type: "TEXT", nullable: true),
                    Hash = table.Column<string>(type: "TEXT", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_SodDecisionEvents", x => x.Seq);
                });

            migrationBuilder.CreateTable(
                name: "SodEvidenceSnapshots",
                columns: table => new
                {
                    Sha256 = table.Column<string>(type: "TEXT", maxLength: 64, nullable: false),
                    Json = table.Column<string>(type: "TEXT", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_SodEvidenceSnapshots", x => x.Sha256);
                });

            migrationBuilder.CreateIndex(
                name: "IX_SodDecisionEvents_Context_Kind_Key_Seq",
                table: "SodDecisionEvents",
                columns: new[] { "Context", "Kind", "Key", "Seq" });

            migrationBuilder.CreateIndex(
                name: "IX_SodDecisionEvents_EventId",
                table: "SodDecisionEvents",
                column: "EventId",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_SodDecisionEvents_Hash",
                table: "SodDecisionEvents",
                column: "Hash",
                unique: true);
            // SoD decision events and their evidence are append-only, like Account Review decisions.
            migrationBuilder.Sql("""
                CREATE TRIGGER SodDecisionEvents_NoUpdate BEFORE UPDATE ON SodDecisionEvents BEGIN SELECT RAISE(ABORT, 'SoD decision events are immutable'); END;
                CREATE TRIGGER SodDecisionEvents_NoDelete BEFORE DELETE ON SodDecisionEvents BEGIN SELECT RAISE(ABORT, 'SoD decision events are immutable'); END;
                CREATE TRIGGER SodEvidenceSnapshots_NoUpdate BEFORE UPDATE ON SodEvidenceSnapshots BEGIN SELECT RAISE(ABORT, 'SoD decision evidence is immutable'); END;
                CREATE TRIGGER SodEvidenceSnapshots_NoDelete BEFORE DELETE ON SodEvidenceSnapshots BEGIN SELECT RAISE(ABORT, 'SoD decision evidence is immutable'); END;
                """);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql("DROP TRIGGER IF EXISTS SodDecisionEvents_NoUpdate; DROP TRIGGER IF EXISTS SodDecisionEvents_NoDelete; DROP TRIGGER IF EXISTS SodEvidenceSnapshots_NoUpdate; DROP TRIGGER IF EXISTS SodEvidenceSnapshots_NoDelete;");
            migrationBuilder.DropTable(
                name: "SodDecisionEvents");

            migrationBuilder.DropTable(
                name: "SodEvidenceSnapshots");
        }
    }
}
