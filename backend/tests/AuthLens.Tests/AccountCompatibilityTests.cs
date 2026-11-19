using System.Security.Cryptography;
using Microsoft.Data.Sqlite;
using AuthLens.Application.Accounts;

namespace AuthLens.Tests;

/// <summary>Sign-in compatibility across AuthLens builds. Fixtures/accounts/build-970d219/accounts.sqlite3 was written by build 970d219 (the first
/// .NET build with accounts): a fresh store activated through its API with one synthetic administrator, then one successful sign-in (credential_version
/// 0, revision 0, a 97-character Argon2id verifier, seven tables, user_version 1). The current build must accept that store unchanged, and the
/// read-only diagnostic must explain refusals without writing anything.</summary>
public sealed class AccountCompatibilityTests : IDisposable
{
    private const string Username = "admin.synthetic", Password = "Synthetic-Admin-Passphrase-2026";
    private static readonly string Fixture = Path.Combine(AppContext.BaseDirectory, "Fixtures", "accounts", "build-970d219", "accounts.sqlite3");
    private readonly string _root = Directory.CreateTempSubdirectory("saplens-accounts-compat-").FullName;

    public void Dispose()
    {
        SqliteConnection.ClearAllPools();
        try { Directory.Delete(_root, true); } catch (IOException) { }
    }

    private string Copy()
    {
        var path = Path.Combine(_root, "security", "accounts.sqlite3");
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.Copy(Fixture, path, overwrite: true);
        return path;
    }

    private static (long Version, long Revision, string Verifier, int Limits) Row(string path)
    {
        using var db = new SqliteConnection($"Data Source={path};Mode=ReadOnly;Pooling=False");
        db.Open();
        using var command = db.CreateCommand();
        command.CommandText = "SELECT credential_version, revision, verifier, (SELECT COUNT(*) FROM login_limits) FROM users WHERE username=$u";
        command.Parameters.AddWithValue("$u", Username);
        using var reader = command.ExecuteReader();
        Assert.True(reader.Read());
        return (reader.GetInt64(0), reader.GetInt64(1), reader.GetString(2), reader.GetInt32(3));
    }

    [Fact]
    public void The_fixture_is_the_reported_shape()
    {
        var (version, revision, verifier, limits) = Row(Fixture);
        Assert.Equal((0L, 0L, 97, 0), (version, revision, verifier.Length, limits));
        Assert.StartsWith("$argon2id$v=19$m=65536,t=3,p=2$", verifier);
        Assert.False(Passwords.NeedsRehash(verifier));
    }

    [Fact]
    public async Task A_store_written_by_an_earlier_build_signs_in_without_changing_credentials()
    {
        var path = Copy();
        var before = Row(path);
        var store = new AccountStore(path, TimeProvider.System);
        store.Prepare();                                   // the server's startup validation of an existing store; it never recreates one
        var (principal, token, csrf) = await store.LoginAsync(Username, Password, "127.0.0.1");
        Assert.Equal(("administrator", Username), (principal.Role, principal.Username));
        Assert.False(string.IsNullOrEmpty(token) || string.IsNullOrEmpty(csrf));
        var after = Row(path);
        Assert.Equal(before.Verifier, after.Verifier);     // current parameters: no rehash
        Assert.Equal((before.Version, before.Revision), (after.Version, after.Revision));
    }

    [Theory]
    [InlineData("Admin.Synthetic", Password)]             // usernames are case-sensitive in v1 and every AuthLens build
    [InlineData(" admin.synthetic", Password)]
    [InlineData(Username, "Synthetic-Admin-Passphrase-2025")]
    public async Task Refusals_stay_generic_and_are_counted(string username, string password)
    {
        var path = Copy();
        var store = new AccountStore(path, TimeProvider.System);
        var error = await Assert.ThrowsAsync<AuthException>(() => store.LoginAsync(username, password, "127.0.0.1"));
        Assert.Equal(("invalid_credentials", 401), (error.Code, error.Status));
        Assert.Equal(1, Row(path).Limits);
    }

    [Fact]
    public void The_diagnostic_explains_each_case_and_writes_nothing()
    {
        var path = Copy();
        var hash = SHA256.HashData(File.ReadAllBytes(path));
        var ok = AccountDiagnostics.Check(path, Username, Password);
        Assert.True(ok.ExactUser && ok.PasswordMatches == true && ok.Enabled == true && !ok.PendingResetOrRecovery);
        Assert.StartsWith("argon2id v=19 m=65536,t=3,p=2, 97 characters", ok.VerifierFormat);
        var wrongCase = AccountDiagnostics.Check(path, "Admin.Synthetic", Password);
        Assert.False(wrongCase.ExactUser);
        Assert.Equal(["'admin.synthetic'"], wrongCase.SimilarUsernames);
        var wrongPassword = AccountDiagnostics.Check(path, Username, "Synthetic-Admin-Passphrase-2025");
        Assert.False(wrongPassword.PasswordMatches);
        Assert.Contains("UTF-8", wrongPassword.Outcome);
        var missing = AccountDiagnostics.Check(Path.Combine(_root, "elsewhere", "accounts.sqlite3"), Username, Password);
        Assert.False(missing.StoreExists);
        Assert.False(File.Exists(Path.Combine(_root, "elsewhere", "accounts.sqlite3")));      // never creates a store
        Assert.Equal(hash, SHA256.HashData(File.ReadAllBytes(path)));                         // read-only
        var report = AccountDiagnostics.Report(ok);
        Assert.DoesNotContain(Password, report);
        Assert.DoesNotContain("$argon2id$", report);
    }

    [Fact]
    public async Task A_pending_administrator_recovery_refuses_sign_in_and_the_diagnostic_says_so()
    {
        var path = Copy();
        var store = new AccountStore(path, TimeProvider.System);
        await store.IssueAsync(Username);                                                     // local CLI recovery code: sign-in stays refused until completed
        Assert.Equal("invalid_credentials", (await Assert.ThrowsAsync<AuthException>(() => store.LoginAsync(Username, Password, "127.0.0.1"))).Code);
        var result = AccountDiagnostics.Check(path, Username, Password);
        Assert.True(result.PendingResetOrRecovery);
        Assert.Contains("recovery is pending", result.Outcome);
    }
}
