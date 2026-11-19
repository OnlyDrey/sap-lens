using System.Globalization;
using System.Text;
using Microsoft.Data.Sqlite;

namespace AuthLens.Application.Accounts;

/// <summary>Read-only explanation of why a sign-in is refused, for a LOCAL administrator with file access to the data directory. It opens the account
/// store read-only (nothing is written: no login limit, no audit entry, no rehash, no session), never creates a store and never prints a verifier,
/// code or password. It checks the same conditions as <see cref="AccountStore.LoginAsync"/>, in the same order.</summary>
public static class AccountDiagnostics
{
    public sealed record Result(string StorePath, bool StoreExists, int Users, bool ExactUser, IReadOnlyList<string> SimilarUsernames, bool? Enabled, string? Role,
        bool PendingResetOrRecovery, int ActiveLoginLimits, string VerifierFormat, bool? PasswordMatches, int PasswordCharacters, bool PasswordHasNonAscii, string Outcome);

    public static Result Check(string storePath, string username, string password, double? now = null)
    {
        var stamp = now ?? DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
        var characters = Passwords.Length(password);
        var nonAscii = password.Any(c => c > 0x7f);
        if (!File.Exists(storePath))
            return new Result(storePath, false, 0, false, [], null, null, false, 0, "none", null, characters, nonAscii,
                "No account store exists at this path. The server would create an empty store here and ask for setup: check --data-dir and AUTHLENS_DATA_DIR.");
        using var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = storePath, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
        db.Open();
        long Count(string sql, params object[] values)
        {
            using var command = db.CreateCommand();
            command.CommandText = sql;
            for (var i = 0; i < values.Length; i++) command.Parameters.AddWithValue("$" + (i + 1), values[i]);
            return Convert.ToInt64(command.ExecuteScalar(), CultureInfo.InvariantCulture);
        }
        var users = (int)Count("SELECT COUNT(*) FROM users");
        var limits = (int)Count("SELECT COUNT(*) FROM login_limits WHERE until_time>$1", stamp);
        var names = new List<string>();
        using (var command = db.CreateCommand())
        {
            command.CommandText = "SELECT username FROM users";
            using var reader = command.ExecuteReader();
            while (reader.Read()) names.Add(reader.GetString(0));
        }
        // Usernames are compared exactly (v1 and every AuthLens build). Report near misses: case, surrounding whitespace, or invisible characters.
        static string Fold(string value) => new(value.Trim().ToLowerInvariant().Where(c => !char.IsControl(c) && !char.IsWhiteSpace(c) && c != '​' && c != '﻿').ToArray());
        var similar = names.Where(n => n != username && Fold(n) == Fold(username)).Select(Describe).ToList();
        using var row = db.CreateCommand();
        row.CommandText = "SELECT id,role,enabled,verifier FROM users WHERE username=$1";
        row.Parameters.AddWithValue("$1", username);
        using var found = row.ExecuteReader();
        if (!found.Read())
            return new Result(storePath, true, users, false, similar, null, null, false, limits, "none", null, characters, nonAscii,
                similar.Count > 0 ? "No account has exactly this username; usernames are case-sensitive. A similar username exists (see above)."
                : users == 0 ? "The store has no accounts: the server shows setup, not sign-in. This is probably not the store the copied data directory contains."
                : "No account has this username.");
        var (id, role, enabled, verifier) = (found.GetString(0), found.GetString(1), found.GetInt64(2) != 0, found.GetString(3));
        var pending = Count("SELECT COUNT(*) FROM one_time WHERE purpose IN ('reset','recovery') AND user_id=$1 AND consumed=0", id) > 0;
        var format = Format(verifier);
        var matches = Passwords.Verify(verifier, password);
        var outcome = limits > 0 ? $"{limits} client(s) are temporarily throttled; a throttled client sees 'Too many attempts', not this result. " : "";
        outcome += !matches ? "The password does not match the stored verifier. The verifier itself is valid; check the password, keyboard layout and, for scripted requests, that the body is sent as UTF-8."
            : pending ? "The password matches, but a password reset or administrator recovery is pending for this account: sign-in stays refused until it is completed."
            : !enabled ? "The password matches, but the account is disabled."
            : "The password matches and the account can sign in. If the browser still refuses it, the request reaches a different server or data directory, or a proxy alters it.";
        return new Result(storePath, true, users, true, similar, enabled, role, pending, limits, format, matches, characters, nonAscii, outcome);
    }

    private static string Describe(string username) =>
        username.Any(c => char.IsControl(c) || char.IsWhiteSpace(c) || c is '​' or '﻿') ? $"'{username}' (contains whitespace or invisible characters)" : $"'{username}'";

    private static string Format(string verifier)
    {
        if (verifier.StartsWith("pbkdf2:", StringComparison.Ordinal)) return "pbkdf2 (SAP Lens v1 legacy; replaced by Argon2id at the next sign-in)";
        var parts = verifier.Split('$');
        return parts.Length == 6 && parts[1] == "argon2id" ? $"argon2id {parts[2]} {parts[3]}, {verifier.Length} characters" : $"unrecognised ({verifier.Length} characters)";
    }

    public static string Report(Result r)
    {
        var sb = new StringBuilder();
        sb.AppendLine($"Account store:        {r.StorePath}");
        sb.AppendLine($"Store exists:         {(r.StoreExists ? "yes" : "no")}");
        if (r.StoreExists) sb.AppendLine($"Accounts in store:    {r.Users}");
        sb.AppendLine($"Exact username match: {(r.ExactUser ? "yes" : "no")}");
        foreach (var name in r.SimilarUsernames) sb.AppendLine($"Similar username:     {name}");
        if (r.ExactUser)
        {
            sb.AppendLine($"Role / enabled:       {r.Role} / {(r.Enabled == true ? "yes" : "no")}");
            sb.AppendLine($"Verifier format:      {r.VerifierFormat}");
            sb.AppendLine($"Pending reset/recovery: {(r.PendingResetOrRecovery ? "yes" : "no")}");
            sb.AppendLine($"Password matches:     {(r.PasswordMatches == true ? "yes" : "no")}");
        }
        sb.AppendLine($"Active login limits:  {r.ActiveLoginLimits}");
        sb.AppendLine($"Password entered:     {r.PasswordCharacters} characters{(r.PasswordHasNonAscii ? ", includes non-ASCII characters" : "")}");
        sb.AppendLine($"Result: {r.Outcome}");
        sb.Append("Nothing was changed.");
        return sb.ToString();
    }
}
