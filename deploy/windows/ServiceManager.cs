// Build with the Windows .NET Framework compiler. No runtime PowerShell scripts.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Security.AccessControl;
using System.Security.Principal;
using System.ServiceProcess;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using System.Xml;
using System.Xml.Linq;
using Microsoft.Win32;

namespace SapLens {
    public static class ServiceSetup {
        public static string Root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
        public static string Wrapper { get { return Path.Combine(Root, "SAPLensService.exe"); } }
        public static string Config { get { return Path.Combine(Root, "SAPLensService.xml"); } }
        public static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 1048576 };
        public static string PrivateRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "SAP Lens Server Access");
        public static string Users { get { return Path.Combine(PrivateRoot, "users.json"); } }

        public static string Run(string file, string args, string input, Dictionary<string,string> environment = null) {
            var p = new Process();
            p.StartInfo = new ProcessStartInfo(file, args) { UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true, RedirectStandardInput = input != null,
                WorkingDirectory = Root, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
            if (environment != null) foreach (var pair in environment) p.StartInfo.EnvironmentVariables[pair.Key] = pair.Value;
            var output = new StringBuilder(); var errors = new StringBuilder();
            p.OutputDataReceived += (s,e) => { if (e.Data != null) output.AppendLine(e.Data); };
            p.ErrorDataReceived += (s,e) => { if (e.Data != null) errors.AppendLine(e.Data); };
            p.Start(); p.BeginOutputReadLine(); p.BeginErrorReadLine();
            if (input != null) {
                byte[] bytes = Encoding.UTF8.GetBytes(input);
                p.StandardInput.BaseStream.Write(bytes, 0, bytes.Length); p.StandardInput.Close();
            }
            if (!p.WaitForExit(60000)) { p.Kill(); throw new InvalidOperationException("Operation timed out; check the service status and logs before retrying."); }
            p.WaitForExit();
            if (p.ExitCode != 0) throw new InvalidOperationException("Operation failed: " + errors.ToString() + output.ToString());
            return output.ToString().Trim();
        }
        public static string Quote(string value) {
            if (value.IndexOfAny(new char[] {'"', '\r', '\n', '\0'}) >= 0 || value.EndsWith("\\"))
                throw new ArgumentException("Invalid command argument.");
            return "\"" + value + "\"";
        }
        static string Hash(string file) { using (var s = File.OpenRead(file)) using (var h = SHA256.Create()) return BitConverter.ToString(h.ComputeHash(s)).Replace("-", "").ToLowerInvariant(); }
        public static void VerifyBundle() {
            if (Hash(Wrapper) != "05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da") throw new InvalidOperationException("The service wrapper is not the verified pinned WinSW build.");
            var report = Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(Root, "verification-report.json")));
            if ((string)report["verification"] != "passed") throw new InvalidOperationException("Bundle verification is missing.");
            foreach (var row in (Dictionary<string,object>)report["files"]) {
                string file = Path.GetFullPath(Path.Combine(Root, row.Key.Replace('/', Path.DirectorySeparatorChar)));
                if (!file.StartsWith(Root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) || Hash(file) != (string)row.Value)
                    throw new InvalidOperationException("Bundle files were modified. Extract a fresh verified package.");
            }
        }
        public static string Status() {
            using (var key = Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Services\SAPLens")) {
                if (key == null) return "Not registered";
                string image = Convert.ToString(key.GetValue("ImagePath")).Trim();
                if (!String.Equals(image.Trim('"'), Wrapper, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidOperationException("SAPLens belongs to another installation. No changes were made.");
            }
            using (var service = new ServiceController("SAPLens")) return service.Status.ToString();
        }
        public static XDocument ReadConfig() {
            using (var reader = XmlReader.Create(Config, new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null })) return XDocument.Load(reader);
        }
        public static Dictionary<string,string> Settings() {
            return ReadConfig().Root.Elements("env").ToDictionary(e => (string)e.Attribute("name"), e => (string)e.Attribute("value"));
        }
        public static void Control(string command) {
            string status = Status();
            if (status == "Not registered") throw new InvalidOperationException("Register the service first.");
            if (!new string[] { "start", "stop", "restart", "uninstall" }.Contains(command)) throw new ArgumentException("Unknown action.");
            if (command == "uninstall" && status != "Stopped") Control("stop");
            Run(Wrapper, command, null);
            var target = command == "stop" ? ServiceControllerStatus.Stopped : ServiceControllerStatus.Running;
            if (command != "uninstall") using (var service = new ServiceController("SAPLens")) service.WaitForStatus(target, TimeSpan.FromSeconds(40));
        }
        static void Acl(string path, bool writable, bool directory) {
            string inherit = directory ? "(OI)(CI)" : "";
            Run("icacls.exe", Quote(path) + " /inheritance:r /grant:r " + Quote("*S-1-5-18:" + inherit + "F") + " " +
                Quote("*S-1-5-32-544:" + inherit + "F") + " " + Quote("NT SERVICE\\SAPLens:" + inherit + (writable ? "M" : "RX")), null);
        }
        static void ProtectProgramDirectory() {
            var security = new DirectorySecurity();
            security.SetAccessRuleProtection(true, false);
            var administrators = new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null);
            security.SetOwner(administrators);
            foreach (IdentityReference account in new IdentityReference[] { administrators,
                     new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null), new NTAccount("NT SERVICE", "SAPLens") }) {
                FileSystemRights rights = account is NTAccount ? FileSystemRights.ReadAndExecute : FileSystemRights.FullControl;
                security.AddAccessRule(new FileSystemAccessRule(account, rights, InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
            }
            new DirectoryInfo(Root).SetAccessControl(security);
        }
        static void PrivateAcl(string path) {
            Run("icacls.exe", Quote(path) + " /inheritance:r /grant:r \"*S-1-5-18:(OI)(CI)F\" \"*S-1-5-32-544:(OI)(CI)F\"", null);
        }
        public static string[] Addresses() {
            var names = new List<string> { Environment.MachineName.ToLowerInvariant() };
            try { names.Add(Dns.GetHostEntry(Environment.MachineName).HostName.ToLowerInvariant()); } catch (SocketException) { }
            foreach (var nic in NetworkInterface.GetAllNetworkInterfaces().Where(n => n.OperationalStatus == OperationalStatus.Up && n.NetworkInterfaceType != NetworkInterfaceType.Loopback))
                foreach (var ip in nic.GetIPProperties().UnicastAddresses.Where(a => a.Address.AddressFamily == AddressFamily.InterNetwork)) names.Add(ip.Address.ToString());
            return names.Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        }
        public static string[] ValidateHosts(string value) {
            string[] hosts = value.Split(',').Select(s => s.Trim().ToLowerInvariant()).Where(s => s.Length > 0).Distinct().ToArray();
            if (hosts.Length == 0 || hosts.Length > 32) throw new ArgumentException("Select 1–32 server names/IP addresses.");
            foreach (string host in hosts) {
                IPAddress ip;
                if (IPAddress.TryParse(host, out ip)) {
                    if (ip.AddressFamily != AddressFamily.InterNetwork || ip.Equals(IPAddress.Any) || ip.Equals(IPAddress.Broadcast)) throw new ArgumentException("Use an IPv4 access address, not a wildcard listener.");
                } else if (Uri.CheckHostName(host) != UriHostNameType.Dns || host.Length > 253 || host.Contains("*") || host.Contains(":")) throw new ArgumentException("Use DNS names or IPv4 addresses without ports or URL prefixes.");
            }
            return hosts;
        }
        // Minimal DER for RSA private-key PEM and typed DNS/IP Subject Alternative Names.
        static byte[] Der(byte tag, byte[] bytes) {
            var r = new List<byte> { tag };
            if (bytes.Length < 128) r.Add((byte)bytes.Length);
            else { var length = new List<byte>(); int n = bytes.Length; while (n > 0) { length.Insert(0, (byte)(n & 255)); n >>= 8; } r.Add((byte)(128 + length.Count)); r.AddRange(length); }
            r.AddRange(bytes); return r.ToArray();
        }
        static byte[] Integer(byte[] bytes) {
            int start = 0; while (start < bytes.Length - 1 && bytes[start] == 0) start++;
            var data = bytes.Skip(start).ToList(); if ((data[0] & 128) != 0) data.Insert(0, 0); return Der(2, data.ToArray());
        }
        static string Pem(string label, byte[] bytes) { return "-----BEGIN " + label + "-----\n" + Convert.ToBase64String(bytes, Base64FormattingOptions.InsertLineBreaks) + "\n-----END " + label + "-----\n"; }
        public const int CertificateKeyBits = 3072;
        static void GenerateCertificate(string[] hosts, string cert, string key) {
            // The platform default RSA factory on .NET Framework returns the legacy CSP provider, which ignores the key size setter and generates a 1024-bit
            // key; the packaged runtime's OpenSSL rejects that (EE_KEY_TOO_SMALL). RSACng takes the size in its constructor.
            using (var rsa = new RSACng(CertificateKeyBits)) {
                if (rsa.KeySize != CertificateKeyBits) throw new InvalidOperationException("The certificate key could not be created with " + CertificateKeyBits + " bits. No certificate was written.");
                var request = new CertificateRequest("CN=" + hosts[0], rsa, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
                var san = new List<byte>();
                foreach (string host in hosts) { IPAddress ip; san.AddRange(IPAddress.TryParse(host, out ip) ? Der(0x87, ip.GetAddressBytes()) : Der(0x82, Encoding.ASCII.GetBytes(host))); }
                request.CertificateExtensions.Add(new X509Extension("2.5.29.17", Der(0x30, san.ToArray()), false));
                request.CertificateExtensions.Add(new X509BasicConstraintsExtension(false, false, 0, true));
                request.CertificateExtensions.Add(new X509KeyUsageExtension(X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.KeyEncipherment, true));
                var eku = new OidCollection(); eku.Add(new Oid("1.3.6.1.5.5.7.3.1")); request.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension(eku, false));
                string certificatePem;
                using (var certificate = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddMinutes(-5), DateTimeOffset.UtcNow.AddDays(365))) {
                    certificatePem = Pem("CERTIFICATE", certificate.Export(X509ContentType.Cert));
                }
                RSAParameters p = rsa.ExportParameters(true);
                // Checked on the key that is actually exported, before any file exists: a weak key is never written or activated.
                if (p.Modulus == null || p.Modulus.Length * 8 < CertificateKeyBits) throw new InvalidOperationException("The generated certificate key is weaker than " + CertificateKeyBits + " bits. No certificate was written.");
                byte[] der = Der(0x30, new byte[][] { Integer(new byte[] {0}), Integer(p.Modulus), Integer(p.Exponent), Integer(p.D), Integer(p.P), Integer(p.Q), Integer(p.DP), Integer(p.DQ), Integer(p.InverseQ) }.SelectMany(b => b).ToArray());
                // New files only (exclusive creation): an existing certificate or key is never overwritten.
                try {
                    using (var stream = new FileStream(key, FileMode.CreateNew, FileAccess.Write, FileShare.None)) { byte[] pem = Encoding.ASCII.GetBytes(Pem("RSA PRIVATE KEY", der)); stream.Write(pem, 0, pem.Length); Array.Clear(pem, 0, pem.Length); }
                    using (var stream = new FileStream(cert, FileMode.CreateNew, FileAccess.Write, FileShare.None)) { byte[] pem = Encoding.ASCII.GetBytes(certificatePem); stream.Write(pem, 0, pem.Length); }
                } finally { Array.Clear(der, 0, der.Length); }
            }
        }
        static void WriteConfig(Dictionary<string,string> settings) {
            var service = new XElement("service", new XElement("id", "SAPLens"), new XElement("name", "SAP Lens Server"),
                new XElement("description", "SAP Lens shared server"), new XElement("executable", @"%BASE%\app\SAP-Lens.exe"),
                new XElement("workingdirectory", @"%BASE%\app"), new XElement("startmode", "Automatic"),
                new XElement("serviceaccount", new XElement("username", @"NT AUTHORITY\LocalService")),
                new XElement("stoptimeout", "25 sec"), new XElement("stopparentprocessfirst", "true"),
                new XElement("onfailure", new XAttribute("action", "restart"), new XAttribute("delay", "10 sec")),
                new XElement("onfailure", new XAttribute("action", "restart"), new XAttribute("delay", "30 sec")),
                new XElement("logpath", Path.Combine(settings["SAP_LENS_DATA_DIR"], "logs")),
                new XElement("log", new XAttribute("mode", "roll-by-size"), new XElement("sizeThreshold", 10240), new XElement("keepFiles", 5)));
            foreach (var pair in settings) service.Add(new XElement("env", new XAttribute("name", pair.Key), new XAttribute("value", pair.Value)));
            string temporary = Config + ".pending"; new XDocument(service).Save(temporary);
            if (File.Exists(Config)) File.Replace(temporary, Config, Config + ".previous"); else File.Move(temporary, Config);
        }
        public static string ActivationCode(string recoverAdministrator) {
            var settings = Settings();
            if ((!settings.ContainsKey("SAP_LENS_AUTH") || settings["SAP_LENS_AUTH"] != "sessions") && !File.Exists(Path.Combine(settings["SAP_LENS_DATA_DIR"],@"securityccounts.sqlite3")))
                throw new InvalidOperationException("Session authentication is not active. Complete the documented account migration first.");
            VerifyBundle(); Status(); // existing installation ownership guards
            string arguments = "--identity-code --data-directory " + Quote(settings["SAP_LENS_DATA_DIR"]);
            if (!String.IsNullOrWhiteSpace(recoverAdministrator)) arguments += " --recover-administrator " + Quote(recoverAdministrator);
            string result = Run(Path.Combine(Root, @"app\SAP-Lens.exe"), arguments, null);
            var value = Json.Deserialize<Dictionary<string,object>>(result);
            return Convert.ToString(value["code"]);
        }
        public static string MigrateIdentity(string newAdministrator) {
            VerifyBundle(); if (Status() != "Stopped") throw new InvalidOperationException("Stop this owned service before account migration.");
            var settings=Settings();
            if (!settings.ContainsKey("SAP_LENS_BACKUP_KEY_FILE")) throw new InvalidOperationException("Save stopped configuration to provision a private external backup key first.");
            string auth=settings["SAP_LENS_AUTH"];
            string arguments="--migrate-identity --data-directory "+Quote(settings["SAP_LENS_DATA_DIR"])+" --legacy-auth "+(auth=="users"?"users":"local");
            if (auth=="users") arguments+=" --legacy-accounts "+Quote(AccountFile(settings));
            else {
                if (String.IsNullOrWhiteSpace(newAdministrator)) throw new InvalidOperationException("Enter a new recovery administrator name for this shared-access installation. No shared password is migrated.");
                arguments+=" --new-administrator "+Quote(newAdministrator);
            }
            var result=Json.Deserialize<Dictionary<string,object>>(Run(Path.Combine(Root,@"app\SAP-Lens.exe"),arguments,null,settings));
            object recovery;
            if (result.TryGetValue("recovery",out recovery) && recovery != null)
                return "Migration complete. Use Recover administrator in the application with this one-time code (15 minutes); set a new personal password.\n\n"+Convert.ToString(((Dictionary<string,object>)recovery)["code"]);
            return "Migration complete. Existing personal credentials and disabled accounts were preserved. Manage accounts inside SAP Lens; the encrypted recovery snapshot is retained.";
        }
        public static void ExportBackupKey(string destination) {
            VerifyBundle(); Status();
            var settings=Settings();
            if(!settings.ContainsKey("SAP_LENS_BACKUP_KEY_FILE"))throw new InvalidOperationException("Save the stopped service configuration to provision its private backup key first.");
            Run(Path.Combine(Root,@"app\SAP-Lens.exe"),"--maintenance export-backup-key --data "+Quote(settings["SAP_LENS_DATA_DIR"])+" --key-file "+Quote(settings["SAP_LENS_BACKUP_KEY_FILE"])+" --output "+Quote(destination),null);
        }
        public static string AccountFile(Dictionary<string,string> settings) {
            string auth, path;
            if (!settings.TryGetValue("SAP_LENS_AUTH", out auth) || auth != "users")
                throw new InvalidOperationException("The service is not configured for individual accounts. Saving an account would not change its active authentication mode.");
            if (!settings.TryGetValue("SAP_LENS_USERS_FILE", out path) || !Path.IsPathRooted(path))
                throw new InvalidOperationException("The service account-file configuration is missing or invalid.");
            return Path.GetFullPath(path);
        }
        static void SaveUser(string path, string name, string password, string role, bool enabled, bool registered) {
            var payload = new Dictionary<string,object> { {"username",name}, {"password",password}, {"role",role}, {"enabled",enabled} };
            Run(Path.Combine(Root, @"app\SAP-Lens.exe"), "--manage-user " + Quote(path), Json.Serialize(payload));
            if (registered) Acl(path, false, false);
        }
        public static void User(string name, string password, string role, bool enabled) {
            if (Status() == "Not registered") throw new InvalidOperationException("Register the service before editing accounts.");
            string path = AccountFile(Settings());
            if (!File.Exists(path)) throw new InvalidOperationException("The configured account file is unavailable. Check service configuration and permissions; existing accounts were not reset.");
            SaveUser(path, name, password, role, enabled, true);
        }
        public const string ModeHttp = "http", ModeSelfSigned = "selfsigned", ModeCustom = "custom";
        // One wording for the rule, shown before anything is saved: what HTTP allows, why, and what to choose instead.
        public const string HttpLocalOnly = "HTTP is for local access on this computer only, because passwords would cross the network unencrypted. To use HTTP set Listen address to 127.0.0.1 and use only localhost or 127.0.0.1 as host names. For access from other computers choose HTTPS; a self-signed certificate can be generated for you.";
        public static bool IsLoopbackName(string host) { IPAddress ip; return host == "localhost" || (IPAddress.TryParse(host, out ip) && IPAddress.IsLoopback(ip)); }
        // HTTP carries passwords and data unencrypted: binding it beyond this computer needs an explicit acknowledgement. It is never chosen for an existing HTTPS installation automatically.
        public static bool HttpNeedsAcknowledgement(string listener, string[] hosts) { IPAddress address; return !(IPAddress.TryParse(listener, out address) && IPAddress.IsLoopback(address)) || hosts.Any(h => !IsLoopbackName(h)); }
        public static void Save(string hostsText, int port, string data, string listener, string mode, string cert, string key, bool acknowledgeHttp) {
            VerifyBundle(); string state = Status(); bool installed = state != "Not registered";
            var current = installed ? Settings() : null;
            string accountFile = current != null && current.ContainsKey("SAP_LENS_AUTH") && current["SAP_LENS_AUTH"] == "users" ? AccountFile(current) : Users;
            if (current != null && current.ContainsKey("SAP_LENS_AUTH") && current["SAP_LENS_AUTH"] == "users" && !File.Exists(accountFile))
                throw new InvalidOperationException("The configured account file is unavailable; it will not be recreated or reset automatically.");
            if (port < 1 || port > 65535) throw new ArgumentException("Use a port from 1 to 65535.");
            if (installed && state != "Stopped") throw new InvalidOperationException("Stop the service before changing its configuration.");
            if (mode != ModeHttp && mode != ModeSelfSigned && mode != ModeCustom) throw new ArgumentException("Choose HTTP, HTTPS with a self-signed certificate, or HTTPS with an existing certificate.");
            string[] hosts = ValidateHosts(hostsText);
            IPAddress address;
            if (!IPAddress.TryParse(listener, out address) || address.AddressFamily != AddressFamily.InterNetwork) throw new ArgumentException("Listen address must be an IPv4 address (0.0.0.0 listens on all IPv4 interfaces).");
            if (!Path.IsPathRooted(data)) throw new ArgumentException("Use an absolute data directory.");
            data = Path.GetFullPath(data).TrimEnd(Path.DirectorySeparatorChar);
            if (data.Equals(Root, StringComparison.OrdinalIgnoreCase) || data.StartsWith(Root + "\\", StringComparison.OrdinalIgnoreCase) || data.Length < 4 || data.StartsWith(@"\\")) throw new ArgumentException("Use a dedicated local data folder outside the application.");
            if (PrivateRoot.Equals(data,StringComparison.OrdinalIgnoreCase) || PrivateRoot.StartsWith(data+"\\",StringComparison.OrdinalIgnoreCase) || data.StartsWith(PrivateRoot+"\\",StringComparison.OrdinalIgnoreCase)) throw new ArgumentException("Data and access credentials must use separate dedicated directories.");
            foreach(string protectedRoot in new string[]{Environment.GetFolderPath(Environment.SpecialFolder.Windows),Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86)})
                if(!String.IsNullOrEmpty(protectedRoot) && (data.Equals(protectedRoot,StringComparison.OrdinalIgnoreCase)||data.StartsWith(protectedRoot+"\\",StringComparison.OrdinalIgnoreCase)))throw new ArgumentException("Do not store mutable data in Windows or Program Files.");
            if (!installed && Directory.Exists(data) && Directory.EnumerateFileSystemEntries(data).Any()) throw new ArgumentException("Choose an empty dedicated data folder for first registration. Existing files were preserved.");
            if (installed && !String.Equals(Settings()["SAP_LENS_DATA_DIR"], data, StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("Data relocation requires a stopped-service backup/migration. The existing data location was preserved.");
            if (!installed && File.Exists(Config)) throw new InvalidOperationException("An existing service configuration is preserved. Review it before registering again.");
            // Transport rules are checked before anything is created or changed.
            if (mode == ModeHttp && HttpNeedsAcknowledgement(listener, hosts)) throw new ArgumentException(HttpLocalOnly);
            if (mode == ModeCustom && (!Path.IsPathRooted(cert) || !Path.IsPathRooted(key) || !File.Exists(cert) || !File.Exists(key))) throw new ArgumentException("Select an existing PEM certificate and unencrypted PEM private key.");
            Directory.CreateDirectory(PrivateRoot); PrivateAcl(PrivateRoot);
            string auth = current != null && current.ContainsKey("SAP_LENS_AUTH") ? current["SAP_LENS_AUTH"] : "sessions";
            string backupKey = current != null && current.ContainsKey("SAP_LENS_BACKUP_KEY_FILE") ? current["SAP_LENS_BACKUP_KEY_FILE"] : Path.Combine(PrivateRoot,"backup-"+Guid.NewGuid().ToString("N")+".key");
            if (!File.Exists(backupKey)) Run(Path.Combine(Root,@"app\SAP-Lens.exe"),"--maintenance init-backup-key --data "+Quote(data)+" --output "+Quote(backupKey),null);
            Run(Path.Combine(Root,@"app\SAP-Lens.exe"),"--maintenance check-backup-key --data "+Quote(data)+" --key-file "+Quote(backupKey),null);
            bool https = mode != ModeHttp;
            if (!https && HttpNeedsAcknowledgement(listener, hosts))
                throw new ArgumentException(HttpLocalOnly);
            if (!https) {
                if (HttpNeedsAcknowledgement(listener, hosts) && !acknowledgeHttp) throw new ArgumentException("HTTP is not encrypted: passwords and data cross the network in clear text. Confirm the acknowledgement to bind HTTP beyond this computer.");
                cert = ""; key = "";  // HTTP mode never carries or generates a certificate
            } else if (mode == ModeSelfSigned) {
                string id = Guid.NewGuid().ToString("N"); cert = Path.Combine(PrivateRoot, "server-" + id + ".crt"); key = Path.Combine(PrivateRoot, "server-" + id + ".key");
                GenerateCertificate(hosts, cert, key);
            } else {
                if (!Path.IsPathRooted(cert) || !Path.IsPathRooted(key) || !File.Exists(cert) || !File.Exists(key)) throw new ArgumentException("Select an existing PEM certificate and unencrypted PEM private key.");
                // Copy into protected storage; don't change ACLs on an operator's original certificate files.
                string id = Guid.NewGuid().ToString("N"); string copyCert = Path.Combine(PrivateRoot, "server-" + id + ".crt"), copyKey = Path.Combine(PrivateRoot, "server-" + id + ".key");
                File.Copy(cert, copyCert); File.Copy(key, copyKey); cert = copyCert; key = copyKey;
            }
            var settings = new Dictionary<string,string> { {"SAP_LENS_DEPLOYMENT_MODE","server"}, {"SAP_LENS_HOST",listener}, {"SAP_LENS_PORT",port.ToString()},
                {"SAP_LENS_DATA_DIR",data}, {"SAP_LENS_SOURCE_DIR",Path.Combine(data,"sources")}, {"SAP_LENS_PUBLIC_ORIGIN",(https ? "https://" : "http://") + hosts[0] + ":" + port},
                {"SAP_LENS_ALLOWED_HOSTS",String.Join(",",hosts)}, {"SAP_LENS_AUTH",auth},
                {"SAP_LENS_LOG_LEVEL","info"}, {"SAP_LENS_BACKUP_KEY_FILE",backupKey} };
            if (auth == "users") settings["SAP_LENS_USERS_FILE"] = accountFile;
            if (https) { settings["SAP_LENS_TLS_CERT_FILE"] = cert; settings["SAP_LENS_TLS_KEY_FILE"] = key; }
            else if (HttpNeedsAcknowledgement(listener, hosts)) settings["SAP_LENS_ALLOW_HTTP"] = "1";
            if (!installed && !File.Exists(Path.Combine(data,@"security\accounts.sqlite3"))) {
                if (Directory.Exists(data) && Directory.EnumerateFileSystemEntries(data).Any()) throw new InvalidOperationException("Existing data requires stopped local identity migration before new service registration. It will not be treated as first-run data.");
                Directory.CreateDirectory(data); PrivateAcl(data);
                Run(Path.Combine(Root,@"app\SAP-Lens.exe"),"--initialize-identity "+Quote(data),null);
            }
            // Validate TLS key/certificate matching and all SANs with the actual packaged runtime before activation.
            var old = File.Exists(Config) ? File.ReadAllText(Config) : null;
            WriteConfig(settings);
            try { ValidateRuntime(settings); }
            catch {
                // The previous configuration stays exactly as it was; the certificate files created by THIS attempt (unique names) are
                // removed so a rejected pair is neither left behind nor picked up later. Files of earlier configurations are untouched.
                if (old == null) File.Delete(Config); else File.WriteAllText(Config, old);
                if (https) { try { if (File.Exists(cert)) File.Delete(cert); if (File.Exists(key)) File.Delete(key); } catch (IOException) { } catch (UnauthorizedAccessException) { } }
                throw;
            }
            if (!installed) { Run(Wrapper, "install", null); Run("sc.exe", "sidtype SAPLens unrestricted", null); }
            Directory.CreateDirectory(data); Acl(data, true, true);
            Directory.CreateDirectory(Path.Combine(data,"logs")); Directory.CreateDirectory(Path.Combine(data,"sources"));
            Acl(PrivateRoot, false, true); Acl(backupKey, false, false); if (auth == "users") Acl(accountFile, false, false); if (https) Acl(key, false, false);
            ProtectProgramDirectory();
        }
        public static void SelfTest() {
            ValidateHosts("server01,server01.example.invalid,192.0.2.10");
            string path = Path.Combine(Path.GetTempPath(), "sap-lens-manager-test-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(path);
            try {
                var accountSettings = new Dictionary<string,string> {{"SAP_LENS_AUTH","users"},{"SAP_LENS_USERS_FILE",Path.Combine(path,"custom-users.json")}};
                if (AccountFile(accountSettings) != Path.Combine(path,"custom-users.json")) throw new InvalidOperationException("Account store selection failed.");
                accountSettings["SAP_LENS_AUTH"]="basic";
                bool rejected=false;
                try { AccountFile(accountSettings); } catch (InvalidOperationException) { rejected=true; }
                if (!rejected) throw new InvalidOperationException("Shared authentication was accepted for account editing.");
                GenerateCertificate(new string[]{"server01","server01.example.invalid","192.0.2.10"},Path.Combine(path,"cert.pem"),Path.Combine(path,"key.pem"));
                string pem=File.ReadAllText(Path.Combine(path,"cert.pem")).Replace("-----BEGIN CERTIFICATE-----", "").Replace("-----END CERTIFICATE-----", "");
                using(var certificate=new X509Certificate2(Convert.FromBase64String(pem))) {
                    if(!certificate.Extensions.Cast<X509Extension>().Any(e=>e.Oid.Value=="2.5.29.17"))throw new InvalidOperationException("Certificate SAN generation failed.");
                }
            } finally { Directory.Delete(path,true); }
        }
        static void ValidateRuntime(Dictionary<string,string> settings) {
            var p = new Process(); p.StartInfo = new ProcessStartInfo(Path.Combine(Root, @"app\SAP-Lens.exe"), "--check-server-config") {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardError = true, RedirectStandardOutput = true, WorkingDirectory = Root };
            foreach (var row in settings) p.StartInfo.EnvironmentVariables[row.Key] = row.Value;
            p.Start(); string error = p.StandardError.ReadToEnd(); p.StandardOutput.ReadToEnd();
            if (!p.WaitForExit(30000)) { p.Kill(); throw new InvalidOperationException("Configuration validation timed out."); }
            if (p.ExitCode != 0) throw new InvalidOperationException("Server configuration is invalid. Check certificate validity, matching private key and SANs for every enabled address. " + error);
        }
    }

    public class Manager : Form {
        TextBox hosts = new TextBox(), data = new TextBox(), listener = new TextBox(), cert = new TextBox(), key = new TextBox(), recoveryUser = new TextBox();
        NumericUpDown port = new NumericUpDown(); CheckBox acknowledge = new CheckBox(); ComboBox mode = new ComboBox(); Label httpWarning = new Label();
        Label status = new Label(); TextBox urls = new TextBox();
        public Manager() {
            Text = "SAP Lens Service Manager"; ClientSize = new Size(780, 670); MinimumSize = new Size(780, 700); StartPosition = FormStartPosition.CenterScreen;
            Font = new Font("Segoe UI", 9); AutoScaleMode = AutoScaleMode.Dpi;
            var table = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(18), ColumnCount = 2, AutoScroll = true };
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 170)); table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); Controls.Add(table);
            status.AutoSize = true; Add(table,"Service status",status);
            hosts.Text = String.Join(",",ServiceSetup.Addresses()); Add(table,"Enabled names / IPv4s",hosts);
            var note = new Label { Text="Comma-separated hostname, FQDN, DNS aliases or IPv4 addresses. Certificate SANs must match all entries.", AutoSize=true, MaximumSize=new Size(550,0) }; Add(table,"",note);
            listener.Text="0.0.0.0"; Add(table,"Listen IPv4 address",listener);
            port.Minimum=1; port.Maximum=65535; port.Value=18743; Add(table,"Port",port);
            data.Text=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),"SAP Lens Server"); Add(table,"Data directory",data);
            mode.DropDownStyle=ComboBoxStyle.DropDownList; mode.Items.AddRange(new object[]{"HTTPS - network access, generate a self-signed certificate (default)","HTTPS - use an existing certificate","HTTP - no certificate (unencrypted)"}); mode.SelectedIndex=0; Add(table,"Connection mode",mode);
            Add(table,"Existing PEM certificate",cert); Add(table,"Existing PEM private key",key);
            httpWarning.Text="Warning: HTTP is not encrypted. Passwords and SAP role data cross the network in clear text. Use HTTP only on a loopback listener and hostname; remote password sign-in requires HTTPS."; httpWarning.AutoSize=true; httpWarning.MaximumSize=new Size(550,0); httpWarning.ForeColor=Color.DarkRed; Add(table,"",httpWarning);
            acknowledge.Text="I understand that HTTP traffic is unencrypted"; acknowledge.AutoSize=true; Add(table,"",acknowledge);
            mode.SelectedIndexChanged += (s,e) => ApplyMode(); ApplyMode();
            Add(table,"Recovery administrator",recoveryUser);
            var actions=new FlowLayoutPanel {AutoSize=true,WrapContents=true,Dock=DockStyle.Fill};
            Button(actions,"Register / save configuration",()=>{ ServiceSetup.Save(hosts.Text,(int)port.Value,data.Text,listener.Text,ModeKey(),cert.Text,key.Text,acknowledge.Checked); LoadConfig(); });
            Button(actions,"Start",()=>ServiceSetup.Control("start")); Button(actions,"Stop",()=>ServiceSetup.Control("stop")); Button(actions,"Restart",()=>ServiceSetup.Control("restart"));
            Button(actions,"Refresh",()=>{}); Button(actions,"Unregister",()=>{ if(MessageBox.Show("Unregister this service? Application files, accounts, certificates and data will be retained.",Text,MessageBoxButtons.YesNo)==DialogResult.Yes)ServiceSetup.Control("uninstall"); });
            Button(actions,"Migrate legacy accounts",()=>{if(MessageBox.Show("Stop the service and verify your separate recovery key first. Preserve old account files and an encrypted application snapshot?",Text,MessageBoxButtons.YesNo)==DialogResult.Yes)MessageBox.Show(ServiceSetup.MigrateIdentity(recoveryUser.Text),"Account migration");});
            Button(actions,"Recover administrator",()=>{ if(MessageBox.Show("Revoke this administrator's sessions and issue a one-time recovery code?",Text,MessageBoxButtons.YesNo)==DialogResult.Yes)MessageBox.Show(ServiceSetup.ActivationCode(recoveryUser.Text),"Administrator recovery code — valid for 15 minutes"); });
            Button(actions,"First-run activation code",()=>{ string code=ServiceSetup.ActivationCode(null); MessageBox.Show("Use this code on the SAP Lens first-run page within 15 minutes. It is shown only here; do not put it in logs.\n\n"+code,Text); });
            Button(actions,"Export backup recovery key",()=>{using(var dialog=new SaveFileDialog{Title="Store a private recovery key separately from backup archives",Filter="SAP Lens recovery key (*.key)|*.key",FileName="SAP-Lens-recovery.key"}){if(dialog.ShowDialog()==DialogResult.OK){ServiceSetup.ExportBackupKey(dialog.FileName);MessageBox.Show("Recovery copy created. Keep it private and separate from archives. In SAP Lens Backup & Restore, verify this copy before enabling automatic backups.",Text);}}});
            Button(actions,"Open logs",()=>Process.Start("explorer.exe",ServiceSetup.Quote(Path.Combine(data.Text,"logs")))); Add(table,"Actions",actions);
            urls.Multiline=true;urls.ReadOnly=true;urls.Height=85;Add(table,"Configured URLs",urls);
            Add(table,"Deployment",new Label{AutoSize=true,MaximumSize=new Size(550,0),Text="Keep this extracted folder in its permanent location. Restrict the port in Windows Firewall to approved machines/subnets. No firewall rule is opened automatically. Self-signed certificates show a browser trust warning. Stop the service before changing configuration. Data relocation requires a separate backup/migration."});
            LoadConfig(); RefreshStatus();
        }
        string ModeKey(){return mode.SelectedIndex==2?ServiceSetup.ModeHttp:mode.SelectedIndex==1?ServiceSetup.ModeCustom:ServiceSetup.ModeSelfSigned;}
        void ApplyMode(){bool custom=mode.SelectedIndex==1,http=mode.SelectedIndex==2;cert.Enabled=key.Enabled=custom;httpWarning.Visible=acknowledge.Visible=http;if(!http)acknowledge.Checked=false;}
        void Add(TableLayoutPanel t,string label,Control control){ int row=t.RowCount++;t.RowStyles.Add(new RowStyle(SizeType.AutoSize));t.Controls.Add(new Label{Text=label,AutoSize=true,Margin=new Padding(0,8,8,6)},0,row);control.Dock=DockStyle.Fill;control.Margin=new Padding(0,4,0,6);t.Controls.Add(control,1,row); }
        void Button(FlowLayoutPanel p,string title,Action action){var b=new Button{Text=title,AutoSize=true};b.Click+=(s,e)=>{Enabled=false;UseWaitCursor=true;try{action();RefreshStatus();}catch(Exception error){MessageBox.Show(error.Message,Text,MessageBoxButtons.OK,MessageBoxIcon.Error);}finally{Enabled=true;UseWaitCursor=false;}};p.Controls.Add(b);}
        void LoadConfig(){if(!File.Exists(ServiceSetup.Config))return;try{var v=ServiceSetup.Settings();hosts.Text=v["SAP_LENS_ALLOWED_HOSTS"];listener.Text=v["SAP_LENS_HOST"];port.Value=int.Parse(v["SAP_LENS_PORT"]);data.Text=v["SAP_LENS_DATA_DIR"];cert.Text=v.ContainsKey("SAP_LENS_TLS_CERT_FILE")?v["SAP_LENS_TLS_CERT_FILE"]:"";key.Text=v.ContainsKey("SAP_LENS_TLS_KEY_FILE")?v["SAP_LENS_TLS_KEY_FILE"]:"";mode.SelectedIndex=v["SAP_LENS_PUBLIC_ORIGIN"].StartsWith("http://",StringComparison.OrdinalIgnoreCase)?2:cert.Text.Length>0?1:0;acknowledge.Checked=v.ContainsKey("SAP_LENS_ALLOW_HTTP");ApplyMode();}catch(Exception e){MessageBox.Show("Existing configuration could not be loaded: "+e.Message,Text);}}
        void RefreshStatus(){try{status.Text=ServiceSetup.Status();if(File.Exists(ServiceSetup.Config)){var v=ServiceSetup.Settings();status.Text+=" | Authentication: "+(v.ContainsKey("SAP_LENS_AUTH")?v["SAP_LENS_AUTH"]:"unknown");urls.Lines=ServiceSetup.ValidateHosts(v["SAP_LENS_ALLOWED_HOSTS"]).Select(h=>(v["SAP_LENS_PUBLIC_ORIGIN"].StartsWith("http://",StringComparison.OrdinalIgnoreCase)?"http://":"https://")+h+":"+v["SAP_LENS_PORT"]).ToArray();}else urls.Text="Register the service to configure access URLs.";}catch(Exception e){status.Text=e.Message;}}
        [STAThread] public static int Main(string[] args){try{if(args.Length==1&&args[0]=="--self-test"){ServiceSetup.SelfTest();return 0;}Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);Application.Run(new Manager());return 0;}catch(Exception e){if(args.Length==0)MessageBox.Show(e.Message,"SAP Lens Service Manager");return 1;}}
    }
}
