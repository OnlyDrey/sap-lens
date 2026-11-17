using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Data.Sqlite;

namespace SapLens.Application.Accounts;

/// <summary>An authenticated account in one session (v1 auth_store.Principal). Provenance tells reviewers how the identity was established.</summary>
public sealed record Principal(string Id, string Username, string DisplayName, string Role, string SessionId = "", string Provenance = "server-session")
{
    public Dictionary<string, object?> Snapshot() => new() { ["id"] = Id, ["username"] = Username, ["display_name"] = DisplayName, ["provenance"] = Provenance };
}

/// <summary>Port of SAP Lens v1 auth_store.py and auth_provisioning.py on the same SQLite schema (<c>security/accounts.sqlite3</c>, user_version 1),
/// so a v1 account store can be adopted as is. Roles: administrator, reviewer, viewer. Server-side sessions keyed by the SHA-256 of a random token,
/// a per-session CSRF secret, idle and absolute lifetimes from the stored policy, credential versions that end every session on a password, role or
/// status change, exponential sign-in throttling per client digest, single-use activation, recovery and reset codes stored only as digests, and an
/// audit table that never receives verifiers or tokens. Nothing is created implicitly except an empty store for a fresh installation.</summary>
public sealed partial class AccountStore
{
    public static readonly string[] Roles = ["administrator", "reviewer", "viewer"];
    private static readonly HashSet<string> All = [.. Roles], Reviewers = ["administrator", "reviewer"], Administrators = ["administrator"];
    public static readonly IReadOnlyDictionary<string, HashSet<string>> Permissions = new Dictionary<string, HashSet<string>>
    {
        ["read"] = All, ["export"] = All, ["profile"] = All, ["review"] = Reviewers, ["approve"] = Reviewers, ["admin"] = Administrators, ["accounts"] = Administrators,
    };
    public const int Schema = 1;
    public const int LockAfter = 5, Lock = 30, LockMax = 900, LockIdle = 1800, LimitRows = 4096, DenialRows = 10_000, CodeLifetime = 900;
    private static readonly string[] Denials = ["session.login_denied", "bootstrap.rejected", "recovery.rejected"];
    private static readonly string[] PublicFields = ["id", "username", "display_name", "role", "enabled", "revision", "created", "last_login"];
    private static readonly HashSet<string> AuditFields = ["id", "username", "display_name", "role", "enabled", "revision", "idle", "absolute"];

    private readonly TimeProvider _clock;
    private readonly SemaphoreSlim _writes = new(1, 1);
    private string? _dummy;

    public AccountStore(string path, TimeProvider clock)
    {
        if (!Path.IsPathFullyQualified(path)) throw new AuthException("absolute_security_path_required");
        StorePath = path;
        _clock = clock;
    }

    public string StorePath { get; }
    public static string For(string dataDirectory) => Path.Combine(Path.GetFullPath(dataDirectory), "security", "accounts.sqlite3");
    private double Now => _clock.GetUtcNow().ToUnixTimeMilliseconds() / 1000.0;

    public static void Require(Principal? actor, string permission)
    {
        if (actor is null || !Permissions.TryGetValue(permission, out var roles) || !roles.Contains(actor.Role)) throw new AuthException("permission_denied", 403);
    }

    public static string Digest(string value) => SapLens.Domain.Json.Digests.Text(value);
    public static string NewSecret() => Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    private void Safe()
    {
        for (var item = new FileInfo(StorePath) as FileSystemInfo; item is not null; item = item is FileInfo f ? f.Directory : ((DirectoryInfo)item).Parent)
            if (item.Exists && item.LinkTarget is not null) throw new AuthException("linked_security_path", 503);
    }

    /// <summary>auth_provisioning.prepare for the .NET data directory: an absent store is created empty (setup required); an existing one is
    /// validated and never recreated, whatever its state.</summary>
    public void Prepare()
    {
        Safe();
        if (!File.Exists(StorePath)) Initialize();
        State();
    }

    public void Initialize()
    {
        Safe();
        if (File.Exists(StorePath)) throw new IOException("Security store already exists.");
        var directory = Path.GetDirectoryName(StorePath)!;
        if (Directory.Exists(directory) && Directory.EnumerateFileSystemEntries(directory).Any()) throw new AuthException("unrecognized_security_directory", 503);
        if (OperatingSystem.IsWindows()) Directory.CreateDirectory(directory);
        else
        {
            Directory.CreateDirectory(directory, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
            File.SetUnixFileMode(directory, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        }
        var options = new FileStreamOptions { Mode = FileMode.CreateNew, Access = FileAccess.Write };
        if (!OperatingSystem.IsWindows()) options.UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite;
        using (new FileStream(StorePath, options)) { }
        using var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = StorePath, Mode = SqliteOpenMode.ReadWrite, Pooling = false }.ToString());
        db.Open();
        Execute(db, """
            CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta VALUES('initialized','0');
            CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
              role TEXT NOT NULL CHECK(role IN ('administrator','reviewer','viewer')), enabled INTEGER NOT NULL,
              verifier TEXT NOT NULL, credential_version INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0,
              created REAL NOT NULL, last_login REAL);
            CREATE TABLE sessions(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),credential_version INTEGER NOT NULL,
              csrf TEXT NOT NULL,created REAL NOT NULL,seen REAL NOT NULL,expires REAL NOT NULL);
            CREATE INDEX session_user ON sessions(user_id);
            CREATE TABLE policy(id INTEGER PRIMARY KEY CHECK(id=1), idle INTEGER NOT NULL, absolute INTEGER NOT NULL,revision INTEGER NOT NULL);
            INSERT INTO policy VALUES(1,1800,43200,0);
            CREATE TABLE audit(id TEXT PRIMARY KEY,at REAL NOT NULL,actor TEXT NOT NULL,operation TEXT NOT NULL,
              target TEXT NOT NULL,before_value TEXT,after_value TEXT);
            CREATE TABLE login_limits(client TEXT PRIMARY KEY, failures INTEGER NOT NULL,until_time REAL NOT NULL);
            CREATE TABLE one_time(id TEXT PRIMARY KEY,purpose TEXT NOT NULL,user_id TEXT,verifier TEXT NOT NULL,
              created REAL NOT NULL,expires REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,consumed INTEGER NOT NULL DEFAULT 0);
            PRAGMA user_version=1;
            """);
    }

    /// <summary>One connection with v1's pragmas; writes are serialized in process and take the SQLite write lock up front (BEGIN IMMEDIATE).</summary>
    private async Task<T> Use<T>(bool write, Func<SqliteConnection, T> work)
    {
        Safe();
        if (!File.Exists(StorePath)) throw new AuthException("security_store_unavailable", 503);
        if (write) await _writes.WaitAsync();
        try
        {
            using var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = StorePath, Mode = SqliteOpenMode.ReadWrite, Pooling = false, DefaultTimeout = 5 }.ToString());
            try
            {
                db.Open();
                Execute(db, "PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;");
                if (Convert.ToInt64(Scalar(db, "PRAGMA user_version")) != Schema) throw new AuthException("security_schema_unsupported", 503);
                if (!write) return work(db);
                using var transaction = db.BeginTransaction(deferred: false);
                var result = work(db);
                transaction.Commit();
                return result;
            }
            catch (SqliteException) { throw new AuthException("security_store_unavailable", 503); }
        }
        finally { if (write) _writes.Release(); }
    }

    private static void Execute(SqliteConnection db, string sql, params object?[] values)
    {
        using var command = Command(db, sql, values);
        command.ExecuteNonQuery();
    }

    private static int Update(SqliteConnection db, string sql, params object?[] values)
    {
        using var command = Command(db, sql, values);
        return command.ExecuteNonQuery();
    }

    private static object? Scalar(SqliteConnection db, string sql, params object?[] values)
    {
        using var command = Command(db, sql, values);
        return command.ExecuteScalar();
    }

    private static Dictionary<string, object?>? Row(SqliteConnection db, string sql, params object?[] values) => Rows(db, sql, values).FirstOrDefault();

    private static List<Dictionary<string, object?>> Rows(SqliteConnection db, string sql, params object?[] values)
    {
        using var command = Command(db, sql, values);
        using var reader = command.ExecuteReader();
        var rows = new List<Dictionary<string, object?>>();
        while (reader.Read())
        {
            var row = new Dictionary<string, object?>(StringComparer.Ordinal);
            for (var i = 0; i < reader.FieldCount; i++) row[reader.GetName(i)] = reader.IsDBNull(i) ? null : reader.GetValue(i);
            rows.Add(row);
        }
        return rows;
    }

    private static SqliteCommand Command(SqliteConnection db, string sql, object?[] values)
    {
        var command = db.CreateCommand();
        command.CommandText = sql;
        for (var i = 0; i < values.Length; i++) command.Parameters.AddWithValue("$" + (i + 1), values[i] ?? DBNull.Value);
        return command;
    }

    private static long L(Dictionary<string, object?> row, string key) => Convert.ToInt64(row[key]);
    private static double D(Dictionary<string, object?> row, string key) => Convert.ToDouble(row[key]);
    private static string S(Dictionary<string, object?> row, string key) => Convert.ToString(row[key])!;

    public static Dictionary<string, object?> Public(Dictionary<string, object?> row)
    {
        var result = PublicFields.ToDictionary(k => k, k => row[k]);
        result["enabled"] = L(row, "enabled") != 0;
        return result;
    }

    // ---- provisioning (auth_provisioning.py)

    public Task<Dictionary<string, object?>> StateAsync() => Use(false, db => StateOf(db));

    public Dictionary<string, object?> State() => StateAsync().GetAwaiter().GetResult();

    private static Dictionary<string, object?> StateOf(SqliteConnection db)
    {
        var marker = Scalar(db, "SELECT value FROM meta WHERE key='initialized'") as string;
        var count = Convert.ToInt64(Scalar(db, "SELECT COUNT(*) FROM users"));
        if (marker is not ("0" or "1") || (marker == "0" && count > 0)) throw new AuthException("security_state_invalid", 503);
        return new() { ["provider"] = "local-sessions", ["setup_required"] = marker == "0" };
    }

    /// <summary>LOCAL administrative operation (CLI only, never an API): a single-use bootstrap code for a fresh store, or a recovery code for an
    /// existing administrator. The secret is returned exactly once and stored only as a digest.</summary>
    public Task<(string Code, double Expires, string Purpose)> IssueAsync(string? username = null) => Use(true, db =>
    {
        var code = NewSecret();
        var now = Now;
        var initialized = (string)Scalar(db, "SELECT value FROM meta WHERE key='initialized'")!;
        string purpose;
        string? identity;
        if (username is null)
        {
            if (initialized != "0" || Convert.ToInt64(Scalar(db, "SELECT COUNT(*) FROM users")) > 0) throw new AuthException("bootstrap_closed", 409);
            (purpose, identity) = ("bootstrap", null);
        }
        else
        {
            if (initialized != "1") throw new AuthException("bootstrap_not_complete", 409);
            var row = Row(db, "SELECT * FROM users WHERE username=$1 AND role='administrator'", username) ?? throw new AuthException("administrator_recovery_unavailable", 409);
            (purpose, identity) = ("recovery", S(row, "id"));
            Execute(db, "UPDATE one_time SET consumed=1 WHERE purpose IN ('reset','recovery') AND user_id=$1", identity);
            Execute(db, "DELETE FROM sessions WHERE user_id=$1", identity);
            Execute(db, "UPDATE users SET credential_version=credential_version+1,revision=revision+1 WHERE id=$1", identity);
        }
        Execute(db, "UPDATE one_time SET consumed=1 WHERE purpose=$1", purpose);
        Execute(db, "INSERT INTO one_time(id,purpose,user_id,verifier,created,expires) VALUES($1,$2,$3,$4,$5,$6)", Guid.NewGuid().ToString("N"), purpose, identity, Digest(code), now, now + CodeLifetime);
        Audit(db, null, purpose + ".issued", identity ?? "");
        return (code, now + CodeLifetime, purpose);
    });

    public async Task<Dictionary<string, object?>> CompleteAsync(string code, string username, string displayName, string password, bool recovery)
    {
        if (code.Length is < 20 or > 128) throw new AuthException("invalid_activation", 401);
        if (!recovery) ValidateProfile(username, displayName, "administrator");
        var purpose = recovery ? "recovery" : "bootstrap";
        await Use(false, db =>
        {
            var pending = Row(db, "SELECT * FROM one_time WHERE purpose=$1 AND consumed=0 ORDER BY created DESC LIMIT 1", purpose);
            if (pending is null || L(pending, "attempts") >= 5 || D(pending, "expires") <= Now) throw new AuthException("invalid_activation", 401);
            return true;
        });
        var verifier = Passwords.Hash(password);
        AuthException? error = null;
        var result = await Use(true, db =>
        {
            var marker = (string)Scalar(db, "SELECT value FROM meta WHERE key='initialized'")!;
            if (!recovery && (marker != "0" || Convert.ToInt64(Scalar(db, "SELECT COUNT(*) FROM users")) > 0)) throw new AuthException("bootstrap_closed", 409);
            var row = Row(db, "SELECT * FROM one_time WHERE purpose=$1 AND consumed=0 ORDER BY created DESC LIMIT 1", purpose);
            var now = Now;
            var valid = row is not null && D(row, "expires") > now && L(row, "attempts") < 5
                && CryptographicOperations.FixedTimeEquals(Encoding.ASCII.GetBytes(S(row, "verifier")), Encoding.ASCII.GetBytes(Digest(code)));
            if (!valid)
            {
                if (row is not null) Execute(db, "UPDATE one_time SET attempts=attempts+1 WHERE id=$1", row["id"]);
                Audit(db, null, purpose + ".rejected");
                error = new AuthException("invalid_activation", 401);
                return null;
            }
            string identity;
            if (recovery)
            {
                var user = Row(db, "SELECT * FROM users WHERE id=$1 AND role='administrator'", row!["user_id"]);
                if (marker != "1" || user is null) throw new AuthException("administrator_recovery_unavailable", 409);
                identity = S(user, "id");
                Execute(db, "UPDATE users SET verifier=$1,enabled=1,revision=revision+1,credential_version=credential_version+1 WHERE id=$2", verifier, identity);
                Execute(db, "DELETE FROM sessions WHERE user_id=$1", identity);
            }
            else
            {
                identity = Guid.NewGuid().ToString("N");
                Execute(db, "INSERT INTO users(id,username,display_name,role,enabled,verifier,created) VALUES($1,$2,$3,'administrator',1,$4,$5)", identity, username, displayName.Trim(), verifier, now);
                Execute(db, "UPDATE meta SET value='1' WHERE key='initialized'");
            }
            Execute(db, "UPDATE one_time SET consumed=1 WHERE id=$1", row!["id"]);
            var created = Public(Row(db, "SELECT * FROM users WHERE id=$1", identity)!);
            Audit(db, null, purpose + ".completed", identity, after: created);
            return created;
        });
        if (error is not null) throw error;
        return result!;
    }

    // ---- accounts (auth_store.py)

    private void Failed(SqliteConnection db, string client, double now)
    {
        var row = Row(db, "SELECT * FROM login_limits WHERE client=$1", client);
        var failures = row is null ? 0 : L(row, "failures");
        if (row is not null && failures >= LockAfter && now - D(row, "until_time") > LockIdle) failures = 0;
        failures++;
        var until = failures >= LockAfter ? now + Math.Min(Lock * Math.Pow(2, failures - LockAfter), LockMax) : 0;
        Execute(db, "INSERT INTO login_limits VALUES($1,$2,$3) ON CONFLICT(client) DO UPDATE SET failures=excluded.failures,until_time=excluded.until_time", client, Math.Min(failures, 64), until);
        if (Convert.ToInt64(Scalar(db, "SELECT COUNT(*) FROM login_limits")) > LimitRows) Execute(db, "DELETE FROM login_limits WHERE until_time<=$1 AND client<>$2", now, client);
    }

    private void Audit(SqliteConnection db, Principal? actor, string operation, string target = "", Dictionary<string, object?>? before = null, Dictionary<string, object?>? after = null)
    {
        // Only public metadata is accepted; never verifier or token fields.
        static string? Clean(Dictionary<string, object?>? value) => value is null ? null : JsonSerializer.Serialize(value.Where(p => AuditFields.Contains(p.Key)).ToDictionary(p => p.Key, p => p.Value));
        Execute(db, "INSERT INTO audit VALUES($1,$2,$3,$4,$5,$6,$7)", Guid.NewGuid().ToString("N"), Now, actor is null ? "local-bootstrap" : JsonSerializer.Serialize(actor.Snapshot()),
            operation, target, Clean(before), Clean(after));
        if (Denials.Contains(operation))
        {
            const string marks = "'session.login_denied','bootstrap.rejected','recovery.rejected'";
            if (Convert.ToInt64(Scalar(db, $"SELECT COUNT(*) FROM audit WHERE operation IN ({marks})")) > DenialRows + 256)
                Execute(db, $"DELETE FROM audit WHERE operation IN ({marks}) AND id NOT IN (SELECT id FROM audit WHERE operation IN ({marks}) ORDER BY at DESC LIMIT $1)", DenialRows);
        }
    }

    private void Authorize(SqliteConnection db, Principal actor, string permission)
    {
        Require(actor, permission);
        var row = Row(db, "SELECT u.*,s.expires,s.seen,s.created AS session_created,p.idle,p.absolute,s.credential_version AS session_version FROM users u JOIN sessions s ON s.user_id=u.id JOIN policy p ON p.id=1 WHERE u.id=$1 AND s.id=$2", actor.Id, actor.SessionId);
        var now = Now;
        if (row is null || L(row, "enabled") == 0 || L(row, "credential_version") != L(row, "session_version")
            || Math.Min(D(row, "expires"), D(row, "session_created") + L(row, "absolute")) <= now || D(row, "seen") + L(row, "idle") <= now)
            throw new AuthException("authentication_required", 401);
        if (!Permissions[permission].Contains(S(row, "role"))) throw new AuthException("permission_denied", 403);
    }

    [GeneratedRegex("^[A-Za-z0-9_.@-]{1,100}$")]
    private static partial Regex UsernamePattern();

    public static void ValidateProfile(string? username, string? displayName, string? role)
    {
        if (username is null || !UsernamePattern().IsMatch(username) || username.EndsWith('\n')) throw new AuthException("invalid_username");
        if (role is null || !All.Contains(role) || displayName is null || Passwords.Length(displayName.Trim()) is < 1 or > 120) throw new AuthException("invalid_profile");
    }

    public Task<List<Dictionary<string, object?>>> UsersAsync(Principal actor)
    {
        Require(actor, "accounts");
        return Use(false, db => { Authorize(db, actor, "accounts"); return Rows(db, "SELECT * FROM users ORDER BY username").Select(Public).ToList(); });
    }

    public Task<Dictionary<string, object?>> CreateUserAsync(Principal actor, string username, string displayName, string role, string password)
    {
        Require(actor, "accounts");
        ValidateProfile(username, displayName, role);
        var verifier = Passwords.Hash(password);
        return Use(true, db =>
        {
            Authorize(db, actor, "accounts");
            if (Row(db, "SELECT 1 AS found FROM users WHERE username=$1", username) is not null) throw new AuthException("username_exists", 409);
            var identity = Guid.NewGuid().ToString("N");
            Execute(db, "INSERT INTO users(id,username,display_name,role,enabled,verifier,created) VALUES($1,$2,$3,$4,1,$5,$6)", identity, username, displayName.Trim(), role, verifier, Now);
            var result = Public(Row(db, "SELECT * FROM users WHERE id=$1", identity)!);
            Audit(db, actor, "user.create", identity, after: result);
            return result;
        });
    }

    public Task<Dictionary<string, object?>> UpdateUserAsync(Principal actor, string identity, long revision, string role, bool enabled, string displayName)
    {
        Require(actor, "accounts");
        if (!All.Contains(role) || Passwords.Length(displayName.Trim()) is < 1 or > 120) throw new AuthException("invalid_profile");
        return Use(true, db =>
        {
            Authorize(db, actor, "accounts");
            var row = Row(db, "SELECT * FROM users WHERE id=$1", identity) ?? throw new AuthException("user_not_found", 404);
            if (L(row, "revision") != revision) throw new AuthException("stale_user", 409);
            if (S(row, "role") == "administrator" && L(row, "enabled") != 0 && (role != "administrator" || !enabled)
                && Convert.ToInt64(Scalar(db, "SELECT COUNT(*) FROM users WHERE role='administrator' AND enabled=1")) <= 1)
                throw new AuthException("last_administrator", 409);
            var before = Public(row);
            Execute(db, "UPDATE users SET role=$1,enabled=$2,display_name=$3,revision=revision+1,credential_version=credential_version+1 WHERE id=$4", role, enabled ? 1 : 0, displayName.Trim(), identity);
            Execute(db, "DELETE FROM sessions WHERE user_id=$1", identity);
            var result = Public(Row(db, "SELECT * FROM users WHERE id=$1", identity)!);
            Audit(db, actor, "user.update", identity, before, result);
            return result;
        });
    }

    public async Task<(Principal Principal, string Token, string Csrf)> LoginAsync(string username, string password, string client)
    {
        var now = Now;
        var clientKey = Digest(client.Length > 256 ? client[..256] : client);
        var row = await Use(false, db =>
        {
            if (Row(db, "SELECT * FROM login_limits WHERE client=$1", clientKey) is { } blocked && D(blocked, "until_time") > now) throw new AuthException("temporarily_throttled", 429);
            return Row(db, "SELECT * FROM users WHERE username=$1", username);
        });
        _dummy ??= Passwords.Hash("Dummy local authentication verifier 123!");
        var valid = Passwords.Verify(row is null ? _dummy : S(row, "verifier"), password);
        var replacement = valid && row is not null && (!S(row, "verifier").StartsWith("$argon2id$", StringComparison.Ordinal) || Passwords.NeedsRehash(S(row, "verifier"))) ? Passwords.Hash(password) : null;
        AuthException? error = null;
        var result = await Use(true, db =>
        {
            if (Row(db, "SELECT * FROM login_limits WHERE client=$1", clientKey) is { } blocked && D(blocked, "until_time") > Now) throw new AuthException("temporarily_throttled", 429);
            var current = row is null ? null : Row(db, "SELECT * FROM users WHERE id=$1", row["id"]);
            var pendingReset = current is not null && Row(db, "SELECT 1 AS found FROM one_time WHERE purpose IN ('reset','recovery') AND user_id=$1 AND consumed=0", current["id"]) is not null;
            if (!valid || pendingReset || current is null || L(current, "enabled") == 0 || L(current, "credential_version") != L(row!, "credential_version"))
            {
                Failed(db, clientKey, now);
                Audit(db, null, "session.login_denied");
                error = new AuthException("invalid_credentials", 401);
                return default;
            }
            Execute(db, "DELETE FROM login_limits WHERE client=$1", clientKey);
            if (replacement is not null) Execute(db, "UPDATE users SET verifier=$1 WHERE id=$2", replacement, current["id"]);
            Execute(db, "UPDATE users SET last_login=$1 WHERE id=$2", now, current["id"]);
            var policy = Row(db, "SELECT * FROM policy")!;
            var (token, csrf) = (NewSecret(), NewSecret());
            var key = Digest(token);
            Execute(db, "INSERT INTO sessions VALUES($1,$2,$3,$4,$5,$6,$7)", key, current["id"], current["credential_version"], Digest(csrf), now, now, now + L(policy, "absolute"));
            var principal = new Principal(S(current, "id"), S(current, "username"), S(current, "display_name"), S(current, "role"), key);
            Audit(db, principal, "session.login", S(current, "id"));
            return (principal, token, csrf);
        });
        if (error is not null) throw error;
        return result;
    }

    public async Task<Principal> SessionAsync(string? token)
    {
        if (token is null || token.Length is < 20 or > 128) throw new AuthException("authentication_required", 401);
        var (key, now) = (Digest(token), Now);
        var row = await Use(false, db => Row(db, "SELECT s.*,u.username,u.display_name,u.role,u.enabled,u.credential_version AS actual_version,p.idle,p.absolute FROM sessions s JOIN users u ON s.user_id=u.id JOIN policy p ON p.id=1 WHERE s.id=$1", key));
        if (row is null || L(row, "enabled") == 0 || L(row, "credential_version") != L(row, "actual_version")
            || Math.Min(D(row, "expires"), D(row, "created") + L(row, "absolute")) <= now || D(row, "seen") + L(row, "idle") <= now)
            throw new AuthException("authentication_required", 401);
        if (now - D(row, "seen") >= 60) await Use(true, db => Update(db, "UPDATE sessions SET seen=$1 WHERE id=$2 AND seen<$3", now, key, now - 60));
        return new Principal(S(row, "user_id"), S(row, "username"), S(row, "display_name"), S(row, "role"), key);
    }

    public async Task CsrfAsync(Principal principal, string? offered)
    {
        if (offered is null || offered.Length > 128) throw new AuthException("csrf_required", 403);
        var stored = await Use(false, db => Scalar(db, "SELECT csrf FROM sessions WHERE id=$1 AND user_id=$2", principal.SessionId, principal.Id) as string);
        if (stored is null || !CryptographicOperations.FixedTimeEquals(Encoding.ASCII.GetBytes(stored), Encoding.ASCII.GetBytes(Digest(offered)))) throw new AuthException("csrf_required", 403);
    }

    public Task LogoutAsync(Principal principal, bool allSessions = false) => Use(true, db =>
    {
        if (allSessions) Execute(db, "DELETE FROM sessions WHERE user_id=$1", principal.Id);
        else Execute(db, "DELETE FROM sessions WHERE id=$1 AND user_id=$2", principal.SessionId, principal.Id);
        Audit(db, principal, allSessions ? "session.logout_all" : "session.logout", principal.Id);
        return true;
    });

    public Task RevokeAsync(Principal actor, string identity)
    {
        Require(actor, "accounts");
        return Use(true, db =>
        {
            Authorize(db, actor, "accounts");
            Execute(db, "DELETE FROM sessions WHERE user_id=$1", identity);
            Audit(db, actor, "session.revoke", identity);
            return true;
        });
    }

    public async Task ChangePasswordAsync(Principal principal, string currentPassword, string newPassword)
    {
        var row = await Use(false, db => Row(db, "SELECT * FROM users WHERE id=$1", principal.Id));
        if (row is null || !Passwords.Verify(S(row, "verifier"), currentPassword)) throw new AuthException("invalid_credentials", 401);
        var verifier = Passwords.Hash(newPassword);
        await Use(true, db =>
        {
            Authorize(db, principal, "profile");
            if (Update(db, "UPDATE users SET verifier=$1,credential_version=credential_version+1,revision=revision+1 WHERE id=$2 AND credential_version=$3", verifier, principal.Id, row["credential_version"]) != 1)
                throw new AuthException("stale_user", 409);
            Execute(db, "DELETE FROM sessions WHERE user_id=$1", principal.Id);
            Audit(db, principal, "password.change", principal.Id);
            return true;
        });
    }

    public Task<List<Dictionary<string, object?>>> SessionsAsync(Principal principal) => Use(false, db =>
        Rows(db, "SELECT * FROM sessions WHERE user_id=$1 ORDER BY created", principal.Id).Select(r => new Dictionary<string, object?>
        {
            ["id"] = r["id"], ["created"] = r["created"], ["seen"] = r["seen"], ["expires"] = r["expires"], ["current"] = S(r, "id") == principal.SessionId,
        }).ToList());

    public Task<Dictionary<string, object?>> MeAsync(Principal principal) => Use(false, db =>
    {
        Authorize(db, principal, "profile");
        var result = Public(Row(db, "SELECT * FROM users WHERE id=$1", principal.Id)!);
        foreach (var (key, value) in principal.Snapshot()) result[key] = value;
        return result;
    });

    public Task<Dictionary<string, object?>> PolicyAsync(Principal actor)
    {
        Require(actor, "accounts");
        return Use(false, db => { Authorize(db, actor, "accounts"); return Row(db, "SELECT idle,absolute,revision FROM policy WHERE id=1")!; });
    }

    public Task<Dictionary<string, object?>> UpdatePolicyAsync(Principal actor, long revision, long idle, long absolute)
    {
        Require(actor, "accounts");
        if (idle is < 300 or > 28800 || absolute is < 3600 or > 86400 || idle > absolute) throw new AuthException("invalid_session_policy");
        return Use(true, db =>
        {
            Authorize(db, actor, "accounts");
            var before = Row(db, "SELECT * FROM policy WHERE id=1")!;
            if (L(before, "revision") != revision) throw new AuthException("stale_policy", 409);
            Execute(db, "UPDATE policy SET idle=$1,absolute=$2,revision=revision+1 WHERE id=1", idle, absolute);
            var result = Row(db, "SELECT idle,absolute,revision FROM policy WHERE id=1")!;
            Audit(db, actor, "policy.update", before: before, after: result);
            return result;
        });
    }

    public Task LogoutOthersAsync(Principal principal) => Use(true, db =>
    {
        Authorize(db, principal, "profile");
        Execute(db, "DELETE FROM sessions WHERE user_id=$1 AND id<>$2", principal.Id, principal.SessionId);
        Audit(db, principal, "session.logout_others", principal.Id);
        return true;
    });

    public Task<Dictionary<string, object?>> ProfileAsync(Principal principal, string displayName, long revision)
    {
        if (Passwords.Length(displayName.Trim()) is < 1 or > 120) throw new AuthException("invalid_profile");
        return Use(true, db =>
        {
            Authorize(db, principal, "profile");
            var row = Row(db, "SELECT * FROM users WHERE id=$1", principal.Id)!;
            if (L(row, "revision") != revision) throw new AuthException("stale_user", 409);
            Execute(db, "UPDATE users SET display_name=$1,revision=revision+1 WHERE id=$2", displayName.Trim(), principal.Id);
            var result = Public(Row(db, "SELECT * FROM users WHERE id=$1", principal.Id)!);
            Audit(db, principal, "profile.update", principal.Id, Public(row), result);
            return result;
        });
    }

    public Task<(string Code, double Expires)> IssueResetAsync(Principal actor, string identity, long revision)
    {
        Require(actor, "accounts");
        if (identity == actor.Id) throw new AuthException("use_own_password_change");
        var code = NewSecret();
        var now = Now;
        return Use(true, db =>
        {
            Authorize(db, actor, "accounts");
            var row = Row(db, "SELECT * FROM users WHERE id=$1", identity) ?? throw new AuthException("user_not_found", 404);
            if (L(row, "revision") != revision) throw new AuthException("stale_user", 409);
            Execute(db, "UPDATE one_time SET consumed=1 WHERE purpose IN ('reset','recovery') AND user_id=$1", identity);
            Execute(db, "INSERT INTO one_time(id,purpose,user_id,verifier,created,expires) VALUES($1,'reset',$2,$3,$4,$5)", Guid.NewGuid().ToString("N"), identity, Digest(code), now, now + CodeLifetime);
            Execute(db, "DELETE FROM sessions WHERE user_id=$1", identity);
            Execute(db, "UPDATE users SET credential_version=credential_version+1,revision=revision+1 WHERE id=$1", identity);
            Audit(db, actor, "password.reset_requested", identity);
            return (code, now + CodeLifetime);
        });
    }

    public async Task CompleteResetAsync(string code, string password, string client)
    {
        if (code.Length is < 20 or > 128) throw new AuthException("invalid_reset", 401);
        var clientKey = Digest("reset:" + (client.Length > 256 ? client[..256] : client));
        var now = Now;
        await Use(false, db =>
        {
            if (Row(db, "SELECT * FROM login_limits WHERE client=$1", clientKey) is { } blocked && D(blocked, "until_time") > now) throw new AuthException("temporarily_throttled", 429);
            return true;
        });
        var verifier = Passwords.Hash(password);
        AuthException? error = null;
        await Use(true, db =>
        {
            if (Row(db, "SELECT * FROM login_limits WHERE client=$1", clientKey) is { } blocked && D(blocked, "until_time") > now) throw new AuthException("temporarily_throttled", 429);
            var row = Row(db, "SELECT * FROM one_time WHERE purpose='reset' AND verifier=$1", Digest(code));
            if (row is null || L(row, "consumed") != 0 || D(row, "expires") <= now)
            {
                Failed(db, clientKey, now);
                error = new AuthException("invalid_reset", 401);
                return false;
            }
            Execute(db, "UPDATE one_time SET consumed=1 WHERE purpose IN ('reset','recovery') AND user_id=$1", row["user_id"]);
            Execute(db, "UPDATE users SET verifier=$1,credential_version=credential_version+1,revision=revision+1 WHERE id=$2", verifier, row["user_id"]);
            Execute(db, "DELETE FROM sessions WHERE user_id=$1", row["user_id"]);
            Execute(db, "DELETE FROM login_limits WHERE client=$1", clientKey);
            Audit(db, null, "password.reset_completed", S(row, "user_id"));
            return true;
        });
        if (error is not null) throw error;
    }

    /// <summary>The store-level authorization v1 performs before account administration that touches no account row.</summary>
    public Task AuthorizeAsync(Principal actor, string permission)
    {
        Require(actor, permission);
        return Use(false, db => { Authorize(db, actor, permission); return true; });
    }

    public Task<List<Dictionary<string, object?>>> AuditAsync(Principal actor, int limit)
    {
        Require(actor, "accounts");
        return Use(false, db => { Authorize(db, actor, "accounts"); return Rows(db, "SELECT * FROM audit ORDER BY at DESC LIMIT $1", Math.Clamp(limit, 1, 200)); });
    }
}
