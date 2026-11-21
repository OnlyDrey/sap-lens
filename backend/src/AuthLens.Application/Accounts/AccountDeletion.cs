using System.Text.Json;
using System.Text.Json.Nodes;

namespace AuthLens.Application.Accounts;

public sealed partial class AccountStore
{
    /// <summary>Permanent live-store removal. Security audit keeps opaque identities; immutable business evidence and retained backups are untouched.</summary>
    public Task DeleteUserAsync(Principal actor, string identity, long revision, string confirmedUsername)
    {
        Require(actor, "accounts");
        return Use(true, db =>
        {
            Authorize(db, actor, "accounts");
            var row = Row(db, "SELECT * FROM users WHERE id=$1", identity) ?? throw new AuthException("user_not_found", 404);
            if (L(row, "revision") != revision) throw new AuthException("stale_user", 409);
            if (!string.Equals(S(row, "username"), confirmedUsername, StringComparison.Ordinal)) throw new AuthException("username_mismatch", 409);
            if (S(row, "role") == "administrator" && L(row, "enabled") != 0
                && Convert.ToInt64(Scalar(db, "SELECT COUNT(*) FROM users WHERE role='administrator' AND enabled=1")) <= 1)
                throw new AuthException("last_administrator", 409);
            if (identity == actor.Id) throw new AuthException("cannot_delete_self", 409);

            // Only the security audit is minimized. Event IDs/order/operations and opaque actor/target links stay accountable.
            foreach (var entry in Rows(db, """
                SELECT id,actor,target,before_value,after_value FROM audit
                WHERE target=$1 OR CASE WHEN json_valid(actor) THEN json_extract(actor,'$.id') END=$1
                """, identity))
            {
                var recorded = S(entry, "actor");
                JsonObject? parsed = null;
                try { parsed = JsonNode.Parse(recorded) as JsonObject; } catch (JsonException) { }
                var auditActor = (string?)parsed?["id"] == identity
                    ? JsonSerializer.Serialize(new { id = identity, provenance = "deleted-account" }) : recorded;
                string? Minimize(object? raw)
                {
                    if (raw is not string json || S(entry, "target") != identity) return raw as string;
                    var value = JsonNode.Parse(json)!.AsObject();
                    return new JsonObject(value.Where(p => p.Key is "id" or "role" or "enabled" or "revision")
                        .Select(p => new KeyValuePair<string, JsonNode?>(p.Key, p.Value?.DeepClone()))).ToJsonString();
                }
                Execute(db, "UPDATE audit SET actor=$1,before_value=$2,after_value=$3 WHERE id=$4", auditActor,
                    Minimize(entry["before_value"]), Minimize(entry["after_value"]), entry["id"]);
            }
            // Clear deleted cells where SQLite supports it; this is not erasure of retained backups or prior WAL/storage blocks.
            Execute(db, "PRAGMA secure_delete=ON;");
            Execute(db, "DELETE FROM one_time WHERE user_id=$1", identity);
            Execute(db, "DELETE FROM sessions WHERE user_id=$1", identity);
            Execute(db, "DELETE FROM users WHERE id=$1", identity);
            Audit(db, actor, "user.delete", identity, new()
            {
                ["id"] = identity, ["role"] = row["role"], ["enabled"] = row["enabled"], ["revision"] = row["revision"],
            });
            return true;
        });
    }
}
