using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace AuthLens.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class ReviewDecisionDetails : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "DetailsJson",
                table: "ReviewDecisions",
                type: "TEXT",
                nullable: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "DetailsJson",
                table: "ReviewDecisions");
        }
    }
}
