using SapLens.Cli;

var options = new Dictionary<string, string>(StringComparer.Ordinal);
for (var i = 1; i + 1 < args.Length; i += 2) options[args[i].TrimStart('-')] = args[i + 1];
return args.FirstOrDefault() switch
{
    "equivalence" => Equivalence.Run(options["data"], options["scenarios"], options["malformed"], options["out"], options.GetValueOrDefault("dataset", "small")),
    "db-enqueue" => await DbCommands.EnqueueAsync(options["data"], int.Parse(options["count"]), options["tag"]),
    "db-claim" => await DbCommands.ClaimAllAsync(options["data"], options["owner"]),
    "bench" => await Bench.RunAsync(options),
    _ => Usage(),
};

static int Usage()
{
    Console.Error.WriteLine("usage: SapLens.Cli equivalence --data DIR --scenarios FILE --malformed DIR --out FILE | db-enqueue --data DIR --count N --tag T | db-claim --data DIR --owner O | bench ...");
    return 1;
}
