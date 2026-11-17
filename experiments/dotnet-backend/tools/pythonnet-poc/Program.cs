using System.Diagnostics;
using System.Text.Json.Nodes;
using Python.Runtime;

// Python.NET proof of concept for REPORTING_ARCHITECTURE.md. Modes:
//   inproc FIXTURES          CPython embedded in this process: render every model (PDF, DOCX), sanitize images, threads, then a native crash.
//   worker                   Python.NET host: one JSON request per stdin line -> one JSON answer per stdout line.
//   drive FIXTURES           Starts `worker` child processes: requests, a crash, a timeout, concurrency.
var mode = args[0];
// Evidence for REPORTING_ARCHITECTURE.md only; not part of the solution and never shipped. Paths come from the environment.
var Backend = Environment.GetEnvironmentVariable("SAPLENS_V1_BACKEND") ?? throw new InvalidOperationException("SAPLENS_V1_BACKEND (v1 backend folder) is required");
var Site = Environment.GetEnvironmentVariable("SAPLENS_V1_SITE_PACKAGES") ?? throw new InvalidOperationException("SAPLENS_V1_SITE_PACKAGES is required");
var PythonLibrary = Environment.GetEnvironmentVariable("SAPLENS_PYTHON_LIBRARY") ?? "/usr/lib/x86_64-linux-gnu/libpython3.12.so";

void Init()
{
    var sw = Stopwatch.StartNew();
    Environment.SetEnvironmentVariable("SAP_LENS_CONFIG_DIR", Directory.CreateTempSubdirectory("pynet-").FullName);
    Runtime.PythonDLL = PythonLibrary;
    PythonEngine.Initialize();
    PythonEngine.BeginAllowThreads();
    using (Py.GIL())
    {
        dynamic sys = Py.Import("sys");
        sys.path.insert(0, Site); sys.path.insert(0, Backend);
        PythonEngine.Exec("import branding, sod_reports, json, base64\n" +
            "def render(model_json, kind, logo_b64):\n" +
            "    m=json.loads(model_json); logo=base64.b64decode(logo_b64) if logo_b64 else None\n" +
            "    sod_reports.report_logo=lambda d: logo if d['logo_id'] else None\n" +
            "    return base64.b64encode(sod_reports.render(m, kind)).decode()\n" +
            "def sanitize(b64):\n" +
            "    return base64.b64encode(branding.sanitize_image(base64.b64decode(b64))).decode()\n", Globals());
    }
    Console.Error.WriteLine($"init {sw.ElapsedMilliseconds} ms");
}
PyDict? globals = null;
PyDict Globals() => globals ??= new PyDict();

string Call(string function, params string?[] arguments)
{
    using (Py.GIL())
    {
        using var f = Globals().GetItem(function);
        return f.Invoke(arguments.Select(a => a is null ? PyObject.None : new PyString(a).As<PyObject>()).ToArray()).As<string>();
    }
}

if (mode == "inproc")
{
    var fixtures = args[1];
    Init();
    var reference = JsonNode.Parse(File.ReadAllText(Path.Combine(fixtures, "reporting.python.json")))!["reports"]!.AsObject();
    var logo = Convert.ToBase64String(File.ReadAllBytes(Path.Combine(fixtures, "logo.png")));
    foreach (var (name, entry) in reference)
        foreach (var kind in new[] { "pdf", "docx" })
        {
            var sw = Stopwatch.StartNew();
            try
            {
                var bytes = Convert.FromBase64String(Call("render", entry!["model"]!.ToJsonString(), kind, entry["model"]!["logo_id"] is null ? null : logo));
                var v1 = Path.Combine(fixtures, $"{name}.v1.{kind}");
                Console.WriteLine($"{name}.{kind}: {bytes.Length} bytes in {sw.ElapsedMilliseconds} ms, identical to v1 file: {File.Exists(v1) && File.ReadAllBytes(v1).SequenceEqual(bytes)}");
            }
            catch (PythonException error) { Console.WriteLine($"{name}.{kind}: Python error {error.Type.Name}: {error.Message[..Math.Min(80, error.Message.Length)]} ({sw.ElapsedMilliseconds} ms)"); }
        }
    foreach (var image in Directory.GetFiles(Path.Combine(fixtures, "images")).Order())
    {
        try { Console.WriteLine($"{Path.GetFileName(image)}: {Convert.FromBase64String(Call("sanitize", Convert.ToBase64String(File.ReadAllBytes(image)))).Length} bytes"); }
        catch (PythonException error) { Console.WriteLine($"{Path.GetFileName(image)}: refused ({error.Message})"); }
    }
    // Concurrency: 8 threads x 4 renders of the large model; the GIL serializes Python work.
    var model = reference["large"]!["model"]!.ToJsonString();
    var one = Stopwatch.StartNew(); Call("render", model, "pdf", null); var single = one.ElapsedMilliseconds;
    var all = Stopwatch.StartNew();
    Parallel.For(0, 32, new ParallelOptions { MaxDegreeOfParallelism = 8 }, _ => Call("render", model, "pdf", null));
    Console.WriteLine($"large.pdf single {single} ms; 32 renders on 8 threads {all.ElapsedMilliseconds} ms (serial estimate {single * 32} ms)");
    Console.WriteLine($"process working set {Environment.WorkingSet / 1048576} MB");
    if (args.Contains("--shutdown"))
    {
        var sw = Stopwatch.StartNew();
        try { PythonEngine.Shutdown(); Console.WriteLine($"PythonEngine.Shutdown ok in {sw.ElapsedMilliseconds} ms"); }
        catch (Exception error) { Console.WriteLine($"PythonEngine.Shutdown failed: {error.GetType().Name}: {error.Message[..Math.Min(160, error.Message.Length)]}"); }
        return;
    }
    if (args.Contains("--crash"))
    {
        Console.WriteLine("triggering a native crash inside Python (ctypes.string_at(0))...");
        Console.Out.Flush();
        using (Py.GIL()) PythonEngine.Exec("import ctypes; ctypes.string_at(0)");
        Console.WriteLine("unreachable: the process survived");
    }
    return;
}

if (mode == "worker")
{
    Init();
    string? line;
    while ((line = Console.ReadLine()) is not null)
    {
        var request = JsonNode.Parse(line)!.AsObject();
        var answer = new JsonObject { ["id"] = request["id"]?.DeepClone() };
        try
        {
            switch ((string)request["op"]!)
            {
                case "render": answer["data"] = Call("render", (string)request["model"]!, (string)request["kind"]!, (string?)request["logo"]); break;
                case "sanitize": answer["data"] = Call("sanitize", (string)request["image"]!); break;
                case "crash": using (Py.GIL()) PythonEngine.Exec("import ctypes; ctypes.string_at(0)"); break;
                case "hang": using (Py.GIL()) PythonEngine.Exec("import time; time.sleep(3600)"); break;
            }
        }
        catch (PythonException error) { answer["error"] = error.Type.Name; }
        Console.WriteLine(answer.ToJsonString());
    }
    return;
}

if (mode == "drive")
{
    var fixtures = args[1];
    var reference = JsonNode.Parse(File.ReadAllText(Path.Combine(fixtures, "reporting.python.json")))!["reports"]!.AsObject();
    var self = Environment.ProcessPath!;
    Process Start()
    {
        var info = new ProcessStartInfo(self, Path.GetFileName(self) == "dotnet" ? $"\"{typeof(Program).Assembly.Location}\" worker" : "worker") { RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
        return Process.Start(info)!;
    }
    async Task<(JsonNode? Answer, string Outcome, long Ms)> Ask(Process worker, JsonObject request, TimeSpan timeout)
    {
        var sw = Stopwatch.StartNew();
        await worker.StandardInput.WriteLineAsync(request.ToJsonString());
        await worker.StandardInput.FlushAsync();
        var read = worker.StandardOutput.ReadLineAsync();
        if (await Task.WhenAny(read, Task.Delay(timeout)) != read) { worker.Kill(entireProcessTree: true); return (null, "timeout: worker killed", sw.ElapsedMilliseconds); }
        var line = await read;
        if (line is null) { await worker.WaitForExitAsync(); return (null, $"worker died, exit code {worker.ExitCode}", sw.ElapsedMilliseconds); }
        return (JsonNode.Parse(line), "ok", sw.ElapsedMilliseconds);
    }
    var startup = Stopwatch.StartNew();
    var w = Start();
    var first = await Ask(w, new JsonObject { ["id"] = 1, ["op"] = "render", ["model"] = reference["standard"]!["model"]!.ToJsonString(), ["kind"] = "docx" }, TimeSpan.FromSeconds(60));
    Console.WriteLine($"first request incl. worker start: {startup.ElapsedMilliseconds} ms ({first.Outcome})");
    var second = await Ask(w, new JsonObject { ["id"] = 2, ["op"] = "render", ["model"] = reference["large"]!["model"]!.ToJsonString(), ["kind"] = "pdf" }, TimeSpan.FromSeconds(60));
    Console.WriteLine($"warm large.pdf: {second.Ms} ms ({second.Outcome}, {Convert.FromBase64String((string)second.Answer!["data"]!).Length} bytes)");
    var bad = await Ask(w, new JsonObject { ["id"] = 3, ["op"] = "sanitize", ["image"] = Convert.ToBase64String(File.ReadAllBytes(Path.Combine(fixtures, "images", "corrupt.jpg"))) }, TimeSpan.FromSeconds(10));
    Console.WriteLine($"corrupt image: {bad.Answer?.ToJsonString()}");
    var crash = await Ask(w, new JsonObject { ["id"] = 4, ["op"] = "crash" }, TimeSpan.FromSeconds(10));
    Console.WriteLine($"native crash in the worker: {crash.Outcome}; driver still running: True");
    var w2 = Start();
    var hang = await Ask(w2, new JsonObject { ["id"] = 5, ["op"] = "hang" }, TimeSpan.FromSeconds(3));
    Console.WriteLine($"hung request: {hang.Outcome} after {hang.Ms} ms");
    // Concurrency: a pool of 4 workers, 16 large PDFs.
    var pool = Enumerable.Range(0, 4).Select(_ => Start()).ToList();
    await Task.WhenAll(pool.Select(p => Ask(p, new JsonObject { ["id"] = 0, ["op"] = "sanitize", ["image"] = Convert.ToBase64String(File.ReadAllBytes(Path.Combine(fixtures, "images", "small.png"))) }, TimeSpan.FromSeconds(60))));
    var all = Stopwatch.StartNew();
    await Task.WhenAll(pool.Select(async p => { for (var i = 0; i < 4; i++) await Ask(p, new JsonObject { ["id"] = i, ["op"] = "render", ["model"] = reference["large"]!["model"]!.ToJsonString(), ["kind"] = "pdf" }, TimeSpan.FromSeconds(60)); }));
    Console.WriteLine($"16 large PDFs on a pool of 4 workers: {all.ElapsedMilliseconds} ms");
    foreach (var p in pool) { p.StandardInput.Close(); }
    foreach (var p in pool) Console.WriteLine($"worker working set {p.WorkingSet64 / 1048576} MB");
}
