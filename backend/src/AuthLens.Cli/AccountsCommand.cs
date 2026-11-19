using System.Text.Json;
using AuthLens.Application.Accounts;

namespace AuthLens.Cli;

/// <summary>Port of auth_provisioning.cli: a LOCAL administrative operation that prints a single-use activation code (fresh installation) or an
/// administrator recovery code exactly once. The API can consume codes but never issue them; running this needs write access to protected storage.
/// The store must already exist (the Server creates it empty at its first start); this command never creates one.</summary>
public static class AccountsCommand
{
    public static async Task<int> IssueAsync(string dataDirectory, string? recoverAdministrator)
    {
        try
        {
            var store = new AccountStore(AccountStore.For(dataDirectory), TimeProvider.System);
            var (code, expires, purpose) = await store.IssueAsync(recoverAdministrator);
            Console.WriteLine(JsonSerializer.Serialize(new { code, expires, purpose }));
            return 0;
        }
        catch (Exception error) when (error is AuthException or IOException or UnauthorizedAccessException)
        {
            Console.Error.WriteLine("Activation unavailable. Check protected storage, start the server once for a fresh installation, or use --recover-administrator for an existing administrator.");
            return 1;
        }
    }
}
