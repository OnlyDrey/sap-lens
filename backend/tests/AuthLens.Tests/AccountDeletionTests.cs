using System.Text.Json;
using Microsoft.Data.Sqlite;
using AuthLens.Application.Accounts;

namespace AuthLens.Tests;

public sealed class AccountDeletionTests : IDisposable
{
    private const string Password = "Synthetic deletion password 123!";
    private readonly string _root = Directory.CreateTempSubdirectory("authlens-account-delete-").FullName;
    private AccountStore NewStore() { var store = new AccountStore(AccountStore.For(_root), TimeProvider.System); store.Prepare(); return store; }
    private static async Task<Principal> Bootstrap(AccountStore store)
    {
        var (code, _, _) = await store.IssueAsync();
        await store.CompleteAsync(code, "keeper", "Keeper", Password, false);
        return (await store.LoginAsync("keeper", Password, "fixture")).Principal;
    }
    private long Count(AccountStore store, string table, string field, string identity)
    {
        using var db = new SqliteConnection($"Data Source={store.StorePath};Mode=ReadOnly;Pooling=False"); db.Open();
        using var command = db.CreateCommand(); command.CommandText = $"SELECT COUNT(*) FROM {table} WHERE {field}=$id"; command.Parameters.AddWithValue("$id", identity);
        return (long)command.ExecuteScalar()!;
    }

    [Fact]
    public async Task Deletion_removes_credentials_sessions_codes_and_minimizes_only_linked_security_audit()
    {
        var store = NewStore(); var keeper = await Bootstrap(store);
        var deleted = await store.CreateUserAsync(keeper, "temporary", "Temporary Personal Name", "administrator", Password);
        var id = (string)deleted["id"]!;
        var login = await store.LoginAsync("temporary", Password, "fixture");
        var other = await store.LoginAsync("temporary", Password, "second");
        // A session-bound one-time proof must disappear too, without revoking sessions before the deletion under test.
        var proof = await store.IssueBackupVerificationAsync(login.Principal, Password);
        var unrelated = await store.CreateUserAsync(login.Principal, "untouched", "Untouched Name", "viewer", Password);
        var originalAudit = await store.AuditAsync(keeper, 200);
        var keeperBefore = JsonSerializer.Serialize((await store.UsersAsync(keeper)).Single(u => (string)u["id"]! == keeper.Id));
        await store.DeleteUserAsync(keeper, id, 0, "temporary");
        Assert.Equal(0, Count(store, "users", "id", id)); Assert.Equal(0, Count(store, "sessions", "user_id", id)); Assert.Equal(0, Count(store, "one_time", "user_id", id));
        await Assert.ThrowsAsync<AuthException>(() => store.LoginAsync("temporary", Password, "fixture"));
        await Assert.ThrowsAsync<AuthException>(() => store.SessionAsync(login.Token));
        await Assert.ThrowsAsync<AuthException>(() => store.SessionAsync(other.Token));
        await Assert.ThrowsAsync<AuthException>(() => store.ConsumeBackupVerificationAsync(login.Principal, proof));
        await Assert.ThrowsAsync<AuthException>(() => store.UsersAsync(login.Principal));
        Assert.Equal(keeperBefore, JsonSerializer.Serialize((await store.UsersAsync(keeper)).Single(u => (string)u["id"]! == keeper.Id)));
        Assert.Contains(await store.UsersAsync(keeper), u => (string)u["id"]! == (string)unrelated["id"]!);
        var audit = await store.AuditAsync(keeper, 200); var text = JsonSerializer.Serialize(audit);
        Assert.DoesNotContain("temporary", text); Assert.DoesNotContain("Temporary Personal Name", text);
        Assert.DoesNotContain(Password, text); Assert.DoesNotContain("argon2", text); Assert.DoesNotContain(proof, text);
        Assert.Contains("deleted-account", text); Assert.Contains("Untouched Name", text);
        Assert.Contains(audit, e => (string)e["operation"]! == "user.delete" && (string)e["target"]! == id);
        foreach (var entry in originalAudit)
        {
            var retained = audit.Single(e => Equals(e["id"], entry["id"]));
            Assert.Equal(entry["at"], retained["at"]); Assert.Equal(entry["operation"], retained["operation"]); Assert.Equal(entry["target"], retained["target"]);
        }
        Assert.Equal("keeper", (await store.LoginAsync("keeper", Password, "fixture")).Principal.Username);
    }

    [Fact]
    public async Task Authorization_self_last_admin_stale_and_wrong_username_refuse_without_removal()
    {
        var store = NewStore(); var keeper = await Bootstrap(store);
        Assert.Equal("last_administrator", (await Assert.ThrowsAsync<AuthException>(() => store.DeleteUserAsync(keeper, keeper.Id, 0, "keeper"))).Code);
        var second = await store.CreateUserAsync(keeper, "second", "Second", "administrator", Password);
        Assert.Equal("cannot_delete_self", (await Assert.ThrowsAsync<AuthException>(() => store.DeleteUserAsync(keeper, keeper.Id, 0, "keeper"))).Code);
        var viewer = await store.CreateUserAsync(keeper, "viewer", "Viewer", "viewer", Password);
        var actor = (await store.LoginAsync("viewer", Password, "fixture")).Principal;
        Assert.Equal("permission_denied", (await Assert.ThrowsAsync<AuthException>(() => store.DeleteUserAsync(actor, (string)second["id"]!, 0, "second"))).Code);
        Assert.Equal("stale_user", (await Assert.ThrowsAsync<AuthException>(() => store.DeleteUserAsync(keeper, (string)second["id"]!, 1, "second"))).Code);
        Assert.Equal("username_mismatch", (await Assert.ThrowsAsync<AuthException>(() => store.DeleteUserAsync(keeper, (string)second["id"]!, 0, "SECOND"))).Code);
        Assert.Equal(3, (await store.UsersAsync(keeper)).Count);
        Assert.DoesNotContain(await store.AuditAsync(keeper, 200), e => (string)e["operation"]! == "user.delete");
        // An inactive former administrator is deletable; it is not counted as the last active administrator.
        var updated = await store.UpdateUserAsync(keeper, (string)second["id"]!, 0, "administrator", false, "Second");
        await store.DeleteUserAsync(keeper, (string)second["id"]!, (long)updated["revision"]!, "second");
        Assert.Single(await store.UsersAsync(keeper), u => (string)u["role"]! == "administrator" && (bool)u["enabled"]!);
    }

    [Fact]
    public async Task Concurrent_deletes_are_serialized_and_do_not_delete_the_surviving_administrator()
    {
        var store = NewStore(); var keeper = await Bootstrap(store);
        var second = await store.CreateUserAsync(keeper, "second", "Second", "administrator", Password);
        var actor = (await store.LoginAsync("second", Password, "fixture")).Principal;
        var results = await Task.WhenAll(Task.Run(() => Delete(keeper, (string)second["id"]!, "second")), Task.Run(() => Delete(actor, keeper.Id, "keeper")));
        Assert.Single(results, ok => ok);
        async Task<bool> Delete(Principal who, string id, string username) { try { await store.DeleteUserAsync(who, id, 0, username); return true; } catch (AuthException) { return false; } }
    }

    [Fact]
    public async Task Audit_failure_rolls_back_credentials_sessions_and_audit_minimization()
    {
        var store = NewStore(); var keeper = await Bootstrap(store);
        var target = await store.CreateUserAsync(keeper, "temporary", "Temporary Name", "viewer", Password);
        var login = await store.LoginAsync("temporary", Password, "fixture");
        var audit = JsonSerializer.Serialize(await store.AuditAsync(keeper, 200));
        using (var db = new SqliteConnection($"Data Source={store.StorePath};Mode=ReadWrite;Pooling=False"))
        {
            db.Open(); using var command = db.CreateCommand();
            command.CommandText = "CREATE TRIGGER refuse_deletion_audit BEFORE INSERT ON audit WHEN NEW.operation='user.delete' BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END;";
            command.ExecuteNonQuery();
        }
        Assert.Equal("security_store_unavailable", (await Assert.ThrowsAsync<AuthException>(() => store.DeleteUserAsync(keeper, (string)target["id"]!, 0, "temporary"))).Code);
        Assert.Equal(1, Count(store, "users", "id", (string)target["id"]!));
        Assert.Equal(audit, JsonSerializer.Serialize(await store.AuditAsync(keeper, 200)));
        Assert.Equal("temporary", (await store.SessionAsync(login.Token)).Username);
    }

    public void Dispose() { SqliteConnection.ClearAllPools(); try { Directory.Delete(_root, true); } catch (IOException) { } }
}
