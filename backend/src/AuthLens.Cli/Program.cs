using AuthLens.Cli;

var options = new Dictionary<string, string>(StringComparer.Ordinal);
for (var i = 1; i + 1 < args.Length; i += 2) options[args[i].TrimStart('-')] = args[i + 1];
return args.FirstOrDefault() switch
{
    "equivalence" => Equivalence.Run(options["data"], options["scenarios"], options["malformed"], options["out"], options.GetValueOrDefault("dataset", "small")),
    "db-enqueue" => await DbCommands.EnqueueAsync(options["data"], int.Parse(options["count"]), options["tag"]),
    "db-claim" => await DbCommands.ClaimAllAsync(options["data"], options["owner"]),
    "bench" => await Bench.RunAsync(options),
    "sod-fingerprints" => SodFingerprints.Run(options["csv"], options["out"]),
    "import-v1-sod" => await ImportV1Sod.RunAsync(options["data"], options["catalogue"], options.GetValueOrDefault("reference")),
    "accounts-code" => await AccountsCommand.IssueAsync(options["data"], options.GetValueOrDefault("recover-administrator")),
    _ => Usage(),
};

static int Usage()
{
    Console.Error.WriteLine("usage: AuthLens.Cli equivalence --data DIR --scenarios FILE --malformed DIR --out FILE | db-enqueue --data DIR --count N --tag T | db-claim --data DIR --owner O | bench ... | import-v1-sod --data DIR --catalogue FILE [--reference FILE] | accounts-code --data DIR [--recover-administrator USERNAME]");
    return 1;
}
