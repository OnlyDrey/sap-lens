using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace AuthLens.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class SettingsAndRefreshReports : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "RefreshReports",
                columns: table => new
                {
                    Id = table.Column<string>(type: "TEXT", maxLength: 32, nullable: false),
                    TimestampUtc = table.Column<DateTime>(type: "TEXT", nullable: false),
                    Operation = table.Column<string>(type: "TEXT", nullable: false),
                    Status = table.Column<string>(type: "TEXT", nullable: false),
                    Json = table.Column<string>(type: "TEXT", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_RefreshReports", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "Settings",
                columns: table => new
                {
                    Id = table.Column<int>(type: "INTEGER", nullable: false),
                    Revision = table.Column<int>(type: "INTEGER", nullable: false),
                    Json = table.Column<string>(type: "TEXT", nullable: false),
                    UpdatedUtc = table.Column<DateTime>(type: "TEXT", nullable: false),
                    UpdatedBy = table.Column<string>(type: "TEXT", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Settings", x => x.Id);
                });

            // Import evidence is append-only, like review decisions.
            migrationBuilder.Sql("CREATE TRIGGER RefreshReports_NoUpdate BEFORE UPDATE ON RefreshReports BEGIN SELECT RAISE(ABORT, 'refresh reports are immutable'); END;");

            migrationBuilder.CreateIndex(
                name: "IX_RefreshReports_TimestampUtc",
                table: "RefreshReports",
                column: "TimestampUtc");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql("DROP TRIGGER IF EXISTS RefreshReports_NoUpdate;");
            migrationBuilder.DropTable(
                name: "RefreshReports");

            migrationBuilder.DropTable(
                name: "Settings");
        }
    }
}
