using System.Diagnostics;
using System.Text.Json;
using AuthLens.Domain.Analysis;
using AuthLens.Domain.Sod;

namespace AuthLens.Cli;

/// <summary>Language-level benchmark, the counterpart of tools/bench_algorithms.py: the same operations on the same files, in one process, no HTTP and no
/// storage. Every operation is repeated; the first sample is the cold (JIT) one.</summary>
public static class Bench
{
    private static (List<double> Samples, T Result) Timed<T>(int runs, Func<T> action)
    {
        var samples = new List<double>();
        T result = default!;
        for (var i = 0; i < runs; i++)
        {
            var watch = Stopwatch.StartNew();
            result = action();
            samples.Add(Math.Round(watch.Elapsed.TotalMilliseconds, 2));
        }
        return (samples, result);
    }

    public static Task<int> RunAsync(IReadOnlyDictionary<string, string> options)
    {
        var data = Path.Combine(options["data"], options.GetValueOrDefault("dataset", "large"));
        var today = DateOnly.FromDateTime(DateTime.Now);
        var ops = new Dictionary<string, List<double>>();
        (ops["catalogue_build"], var catalogue) = Timed(3, () => Equivalence.LoadCatalogue(Path.Combine(data, "roles.csv")).Catalogue);
        (ops["users_build"], var users) = Timed(3, () => Equivalence.LoadUsers(Path.Combine(data, "users.csv"), catalogue).Users);
        (ops["sod_parse"], var sod) = Timed(3, () => Equivalence.LoadSod(Path.Combine(data, "sod.csv")));
        (ops["role_lookup_text"], _) = Timed(7, () => RoleLookup.Find(catalogue, new RoleLookupQuery(Search: "ROLE_01*")));
        (ops["role_lookup_tcodes_or"], _) = Timed(7, () => RoleLookup.Find(catalogue, new RoleLookupQuery(Tcodes: ["T0010", "T0020", "T0030"], TransactionMode: "or")));
        (ops["role_lookup_area"], _) = Timed(7, () => RoleLookup.Find(catalogue, new RoleLookupQuery(FunctionKeys: ["FI", "MM"])));
        (ops["user_lookup_all"], _) = Timed(7, () => UserLookup.Find(users, true, new UserLookupQuery(), today));
        (ops["user_lookup_tcode"], _) = Timed(7, () => UserLookup.Find(users, true, new UserLookupQuery(Tcodes: ["T0010"], ShowExpired: true), today));
        (ops["user_lookup_search"], _) = Timed(7, () => UserLookup.Find(users, true, new UserLookupQuery(Search: "user0001*"), today));
        (ops["compare"], _) = Timed(7, () => UserComparison.Compare(catalogue, users, "USER00001", "USER00008", "all", today));
        (ops["sod_analyze"], var result) = Timed(3, () => SodAnalyzer.Analyze(catalogue, users, sod, today, "active"));
        using var process = Process.GetCurrentProcess();
        var summary = new Dictionary<string, object>
        {
            ["implementation"] = "dotnet-v2", ["runtime"] = Environment.Version.ToString(), ["operations"] = ops, ["sod_user_findings"] = result.Users.Count,
            ["peak_rss_mb"] = Math.Round(process.PeakWorkingSet64 / 1024.0 / 1024.0, 1),
        };
        File.WriteAllText(options["out"], JsonSerializer.Serialize(summary, new JsonSerializerOptions { WriteIndented = true }));
        foreach (var (name, samples) in ops)
            Console.WriteLine($"{name,-24} first {samples[0],9:0.0} ms   median(rest) {Median(samples.Skip(1).ToList()),9:0.0} ms");
        Console.WriteLine($"peak RSS {summary["peak_rss_mb"]} MB");
        return Task.FromResult(0);
    }

    private static double Median(List<double> values)
    {
        values.Sort();
        return values.Count % 2 == 1 ? values[values.Count / 2] : (values[values.Count / 2 - 1] + values[values.Count / 2]) / 2;
    }
}
