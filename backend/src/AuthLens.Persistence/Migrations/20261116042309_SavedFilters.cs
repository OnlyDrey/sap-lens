using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace AuthLens.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class SavedFilters : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "SavedFilters",
                columns: table => new
                {
                    Id = table.Column<string>(type: "TEXT", maxLength: 64, nullable: false),
                    Name = table.Column<string>(type: "TEXT", nullable: false),
                    NameKey = table.Column<string>(type: "TEXT", nullable: false),
                    View = table.Column<string>(type: "TEXT", maxLength: 32, nullable: false),
                    FiltersJson = table.Column<string>(type: "TEXT", nullable: false),
                    FilterSchema = table.Column<int>(type: "INTEGER", nullable: false),
                    Created = table.Column<string>(type: "TEXT", nullable: false),
                    Modified = table.Column<string>(type: "TEXT", nullable: false),
                    Sequence = table.Column<long>(type: "INTEGER", nullable: false),
                    CreatedBy = table.Column<string>(type: "TEXT", nullable: false),
                    ModifiedBy = table.Column<string>(type: "TEXT", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_SavedFilters", x => x.Id);
                });

            migrationBuilder.CreateIndex(
                name: "IX_SavedFilters_Sequence",
                table: "SavedFilters",
                column: "Sequence",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_SavedFilters_View_NameKey",
                table: "SavedFilters",
                columns: new[] { "View", "NameKey" },
                unique: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "SavedFilters");
        }
    }
}
