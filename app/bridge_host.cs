// AIconomy Zero-Extraction Native RAM Secret Bridge (<30ms startup, zero temp extraction, zero GUI exe lock)
// Compiled with Windows built-in Microsoft.NET\Framework64\v4.0.30319\csc.exe
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

[assembly: AssemblyTitle("AIconomy MCP Bridge")]
[assembly: AssemblyDescription("AIconomy Native Stdio MCP Secret Bridge")]
[assembly: AssemblyCompany("AIconomy")]
[assembly: AssemblyProduct("AIconomy")]
[assembly: AssemblyVersion("1.6.0.0")]
[assembly: AssemblyFileVersion("1.6.0.0")]

internal static class Program
{
    private static IntPtr s_jobHandle = IntPtr.Zero;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct DATA_BLOB
    {
        public int cbData;
        public IntPtr pbData;
    }

    [DllImport("crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool CryptUnprotectData(
        ref DATA_BLOB pDataIn,
        IntPtr ppszDataDescr,
        IntPtr pOptionalEntropy,
        IntPtr pvReserved,
        IntPtr pPromptStruct,
        int dwFlags,
        ref DATA_BLOB pDataOut
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr LocalFree(IntPtr hMem);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFOW
    {
        public int cb;
        public string lpReserved;
        public string lpDesktop;
        public string lpTitle;
        public int dwX;
        public int dwY;
        public int dwXSize;
        public int dwYSize;
        public int dwXCountChars;
        public int dwYCountChars;
        public int dwFillAttribute;
        public int dwFlags;
        public short wShowWindow;
        public short cbReserved2;
        public IntPtr lpReserved2;
        public IntPtr hStdInput;
        public IntPtr hStdOutput;
        public IntPtr hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION
    {
        public IntPtr hProcess;
        public IntPtr hThread;
        public uint dwProcessId;
        public uint dwThreadId;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateJobObjectW(IntPtr lpJobAttributes, string lpName);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(
        IntPtr hJob,
        int JobObjectInfoClass,
        ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION lpJobObjectInfo,
        int cbJobObjectInfoLength
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr GetStdHandle(int nStdHandle);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetHandleInformation(IntPtr hObject, uint dwMask, uint dwFlags);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool CreateProcessW(
        string lpApplicationName,
        StringBuilder lpCommandLine,
        IntPtr lpProcessAttributes,
        IntPtr lpThreadAttributes,
        bool bInheritHandles,
        uint dwCreationFlags,
        IntPtr lpEnvironment,
        string lpCurrentDirectory,
        ref STARTUPINFOW lpStartupInfo,
        out PROCESS_INFORMATION lpProcessInformation
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint WaitForSingleObject(IntPtr hHandle, uint dwMilliseconds);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetExitCodeProcess(IntPtr hProcess, out uint lpExitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr hObject);

    private static readonly HashSet<string> SensitiveEnvExact = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GITHUB_PERSONAL_ACCESS_TOKEN",
        "GITLAB_PERSONAL_ACCESS_TOKEN",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "ELEVENLABS_API_KEY",
        "MESHY_API_KEY",
        "CONTEXT7_API_KEY",
        "STRIPE_SECRET_KEY",
        "SUPABASE_ACCESS_TOKEN",
        "NOTION_TOKEN",
        "SENTRY_ACCESS_TOKEN",
        "CLOUDFLARE_API_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_CLIENT_SECRET",
        "PGPASSWORD",
        "MYSQL_PWD",
        "DATABASE_URL",
        "POSTGRES_URL",
        "POSTGRES_CONNECTION_URI",
        "MONGODB_URI",
        "MDB_MCP_CONNECTION_STRING",
        "REDIS_URL"
    };

    private static readonly string[] SensitiveEnvSuffixes = new string[]
    {
        "_API_KEY",
        "_SECRET",
        "_SECRET_KEY",
        "_ACCESS_TOKEN",
        "_AUTH_TOKEN",
        "_PERSONAL_ACCESS_TOKEN",
        "_PRIVATE_KEY",
        "_PASSWORD",
        "_PASSWD",
        "_TOKEN",
        "_PAT",
        "_DSN",
        "_CONNECTION_STRING",
        "_CONNECTION_URI"
    };

    private static readonly char[] BatchUnsafeChars = new char[]
    {
        ' ', '\t', '\n', '\v', '"', '&', '|', '<', '>', '^', '(', ')', '%', '!', ';', ',', '='
    };

    private static readonly Regex PgUriRegex = new Regex(
        @"^((?:postgres|postgresql)://)([^/\s:@""']*)(?::([^@\s/""']*))?(@.+)$",
        RegexOptions.IgnoreCase | RegexOptions.Compiled
    );

    private static string DefaultDataDir()
    {
        try
        {
            string exeDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\', '/');
            if (File.Exists(Path.Combine(exeDir, "portable.txt")))
            {
                return Path.Combine(exeDir, "data");
            }
            string parent1 = Path.GetDirectoryName(exeDir);
            string parent2 = string.IsNullOrEmpty(parent1) ? null : Path.GetDirectoryName(parent1);
            if (!string.IsNullOrEmpty(parent2) && File.Exists(Path.Combine(parent2, "portable.txt")))
            {
                return parent1;
            }
        }
        catch { }

        string localApp = Environment.GetEnvironmentVariable("LOCALAPPDATA");
        if (string.IsNullOrEmpty(localApp))
        {
            localApp = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "AppData", "Local");
        }
        return Path.Combine(localApp, "AIconomy", "data");
    }

    private static IntPtr EnsureKillOnCloseJob()
    {
        if (s_jobHandle != IntPtr.Zero) return s_jobHandle;
        IntPtr hJob = CreateJobObjectW(IntPtr.Zero, null);
        if (hJob == IntPtr.Zero) return IntPtr.Zero;
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation.LimitFlags = 0x00002000u; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (!SetInformationJobObject(hJob, 9, ref info, Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION))))
        {
            CloseHandle(hJob);
            return IntPtr.Zero;
        }
        s_jobHandle = hJob;
        return s_jobHandle;
    }

    private static void SplitPostgresUriSecret(string uri, out string sanitizedUri, out string password)
    {
        sanitizedUri = (uri ?? "").Trim();
        password = "";
        if (string.IsNullOrEmpty(sanitizedUri)) return;
        Match m = PgUriRegex.Match(sanitizedUri);
        if (!m.Success) return;
        string scheme = m.Groups[1].Value;
        string user = m.Groups[2].Value;
        string rawPw = m.Groups[3].Success ? m.Groups[3].Value : "";
        string hostPart = m.Groups[4].Value;
        if (string.IsNullOrEmpty(rawPw)) return;
        try { password = Uri.UnescapeDataString(rawPw); }
        catch { password = rawPw; }
        sanitizedUri = !string.IsNullOrEmpty(user)
            ? (scheme + user + hostPart)
            : (scheme + hostPart.TrimStart('@'));
    }

    private static string DecryptDpapiUnprotected(string cipherB64)
    {
        if (string.IsNullOrEmpty(cipherB64)) return "";
        byte[] raw = Convert.FromBase64String(cipherB64);
        GCHandle handle = GCHandle.Alloc(raw, GCHandleType.Pinned);
        DATA_BLOB blobIn = new DATA_BLOB { cbData = raw.Length, pbData = handle.AddrOfPinnedObject() };
        DATA_BLOB blobOut = new DATA_BLOB();
        try
        {
            if (!CryptUnprotectData(ref blobIn, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 0x01, ref blobOut))
            {
                return "";
            }
            try
            {
                byte[] plain = new byte[blobOut.cbData];
                Marshal.Copy(blobOut.pbData, plain, 0, blobOut.cbData);
                return Encoding.UTF8.GetString(plain);
            }
            finally
            {
                if (blobOut.pbData != IntPtr.Zero) LocalFree(blobOut.pbData);
            }
        }
        finally
        {
            handle.Free();
        }
    }

    private static string ResolvePipeName()
    {
        string custom = Environment.GetEnvironmentVariable("AICONOMY_PIPE_NAME");
        if (!string.IsNullOrEmpty(custom)) return custom.Trim();
        string user = Environment.GetEnvironmentVariable("USERNAME");
        if (string.IsNullOrEmpty(user)) user = "user";
        return "AIconomy.SingleInstance." + user.Replace(" ", "_");
    }

    private static Dictionary<string, object> RequestLaunchSpecFromGuiPipe(
        string toolId,
        string fullDataDir,
        JavaScriptSerializer ser,
        out bool lockedError,
        out bool deniedError
    )
    {
        lockedError = false;
        deniedError = false;
        string pipeName = ResolvePipeName();
        try
        {
            using (NamedPipeClientStream pipe = new NamedPipeClientStream(".", pipeName, PipeDirection.InOut))
            {
                pipe.Connect(600);
                string dirB64 = Convert.ToBase64String(Encoding.UTF8.GetBytes(fullDataDir));
                byte[] req = Encoding.ASCII.GetBytes("resolve_launch:" + toolId + "|" + dirB64);
                pipe.Write(req, 0, req.Length);
                pipe.Flush();
                using (StreamReader reader = new StreamReader(pipe, Encoding.ASCII, false, 4096, true))
                {
                    string resp = (reader.ReadLine() ?? "").Trim();
                    if (resp == "LOCKED")
                    {
                        lockedError = true;
                        return null;
                    }
                    if (resp == "DENIED" || string.IsNullOrEmpty(resp))
                    {
                        deniedError = true;
                        return null;
                    }
                    if (resp.StartsWith("LAUNCH:", StringComparison.Ordinal))
                    {
                        string b64 = resp.Substring(7).Trim();
                        string json = Encoding.UTF8.GetString(Convert.FromBase64String(b64));
                        return ser.Deserialize<Dictionary<string, object>>(json);
                    }
                }
            }
        }
        catch
        {
            lockedError = true;
            return null;
        }
        deniedError = true;
        return null;
    }

    private static string ResolveCliOAuthToken(string cliBin, List<string> tokenArgs)
    {
        if (string.IsNullOrEmpty(cliBin) || tokenArgs == null || tokenArgs.Count == 0) return "";
        string exe = ResolveExecutable(cliBin);
        if (string.IsNullOrEmpty(exe)) return "";
        try
        {
            ProcessStartInfo psi = new ProcessStartInfo
            {
                FileName = exe,
                Arguments = JoinWindowsArgs(tokenArgs),
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };
            using (Process p = Process.Start(psi))
            {
                if (p == null) return "";
                string stdout = p.StandardOutput.ReadToEnd();
                if (!p.WaitForExit(4000))
                {
                    try { p.Kill(); } catch { }
                    return "";
                }
                if (p.ExitCode == 0 && !string.IsNullOrWhiteSpace(stdout))
                {
                    string[] lines = stdout.Trim().Split(new char[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
                    if (lines.Length > 0) return lines[0].Trim();
                }
            }
        }
        catch { }
        return "";
    }

    private static string ResolveExecutable(string cmd)
    {
        if (string.IsNullOrEmpty(cmd)) return "";
        if (File.Exists(cmd)) return Path.GetFullPath(cmd);
        string pathEnv = Environment.GetEnvironmentVariable("PATH") ?? "";
        string[] dirs = pathEnv.Split(new char[] { ';' }, StringSplitOptions.RemoveEmptyEntries);
        string[] exts = new string[] { ".cmd", ".exe", ".bat", "" };
        foreach (string dir in dirs)
        {
            string cleanDir = dir.Trim().Trim('"');
            if (string.IsNullOrEmpty(cleanDir)) continue;
            foreach (string ext in exts)
            {
                try
                {
                    string cand = Path.Combine(cleanDir, cmd + ext);
                    if (File.Exists(cand)) return cand;
                }
                catch { }
            }
        }
        return cmd;
    }

    private static bool TryUnwrapNodeBatchWrapper(string exePath, List<string> argsIn, out string nodeExe, out List<string> nodeArgs)
    {
        nodeExe = null;
        nodeArgs = null;
        try
        {
            string fileName = Path.GetFileName(exePath);
            if (!string.Equals(fileName, "npx.cmd", StringComparison.OrdinalIgnoreCase)
                && !string.Equals(fileName, "npm.cmd", StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }
            string dir = Path.GetDirectoryName(exePath);
            if (string.IsNullOrEmpty(dir)) return false;
            string candNode = Path.Combine(dir, "node.exe");
            string cliJs = string.Equals(fileName, "npx.cmd", StringComparison.OrdinalIgnoreCase)
                ? Path.Combine(dir, "node_modules", "npm", "bin", "npx-cli.js")
                : Path.Combine(dir, "node_modules", "npm", "bin", "npm-cli.js");
            if (File.Exists(candNode) && File.Exists(cliJs))
            {
                nodeExe = candNode;
                nodeArgs = new List<string> { cliJs };
                nodeArgs.AddRange(argsIn);
                return true;
            }
        }
        catch { }
        return false;
    }

    private static string QuoteWinArg(string arg)
    {
        if (arg == null) return "\"\"";
        if (arg.Length > 0 && arg.IndexOfAny(new char[] { ' ', '\t', '\n', '\v', '"' }) < 0)
        {
            return arg;
        }
        StringBuilder sb = new StringBuilder();
        sb.Append('"');
        int backslashes = 0;
        foreach (char c in arg)
        {
            if (c == '\\')
            {
                backslashes++;
            }
            else if (c == '"')
            {
                sb.Append('\\', backslashes * 2 + 1);
                sb.Append('"');
                backslashes = 0;
            }
            else
            {
                if (backslashes > 0)
                {
                    sb.Append('\\', backslashes);
                    backslashes = 0;
                }
                sb.Append(c);
            }
        }
        if (backslashes > 0) sb.Append('\\', backslashes * 2);
        sb.Append('"');
        return sb.ToString();
    }

    private static string QuoteBatchArg(string arg)
    {
        if (string.IsNullOrEmpty(arg)) return "\"\"";
        if (arg.IndexOfAny(BatchUnsafeChars) < 0) return arg;
        // Maintain strictly even double-quote parity so cmd.exe can never break out of quote mode on & | > < ^
        StringBuilder sb = new StringBuilder();
        sb.Append('"');
        foreach (char c in arg)
        {
            if (c == '"') sb.Append("\"\"");
            else if (c == '%') sb.Append("%%");
            else sb.Append(c);
        }
        if (arg.EndsWith("\\", StringComparison.Ordinal))
        {
            sb.Append('\\');
        }
        sb.Append('"');
        return sb.ToString();
    }

    private static string JoinWindowsArgs(IEnumerable<string> args)
    {
        List<string> quoted = new List<string>();
        foreach (string a in args) quoted.Add(QuoteWinArg(a));
        return string.Join(" ", quoted.ToArray());
    }

    private static string JoinBatchArgs(IEnumerable<string> args)
    {
        List<string> quoted = new List<string>();
        foreach (string a in args) quoted.Add(QuoteBatchArg(a));
        return string.Join(" ", quoted.ToArray());
    }

    private static bool IsSensitiveKey(string key)
    {
        if (SensitiveEnvExact.Contains(key)) return true;
        foreach (string sfx in SensitiveEnvSuffixes)
        {
            if (key.EndsWith(sfx, StringComparison.OrdinalIgnoreCase)) return true;
        }
        return false;
    }

    private static bool IsVaultPinProtected(string fullDataDir, JavaScriptSerializer ser)
    {
        string vaultPath = Path.Combine(fullDataDir, "aiconomy-vault.dpapi.json");
        if (!File.Exists(vaultPath)) return false;
        try
        {
            Dictionary<string, object> vDoc = ser.Deserialize<Dictionary<string, object>>(File.ReadAllText(vaultPath, Encoding.UTF8));
            if (vDoc != null && vDoc.ContainsKey("__vault_meta__") && vDoc["__vault_meta__"] is Dictionary<string, object>)
            {
                Dictionary<string, object> meta = (Dictionary<string, object>)vDoc["__vault_meta__"];
                return meta.ContainsKey("protected") && meta["protected"] is bool && (bool)meta["protected"];
            }
        }
        catch { }
        return false;
    }

    public static int Main(string[] args)
    {
        if (args.Length >= 1 && args[0] == "--ping")
        {
            Console.WriteLine("AICONOMY_BRIDGE_OK");
            return 0;
        }

        int offset = 0;
        if (args.Length >= 1 && args[0] == "--mcp-exec") offset = 1;
        if (args.Length <= offset)
        {
            Console.Error.WriteLine("Usage: aiconomy-bridge --mcp-exec <tool_id> [--data-dir <path>]");
            return 2;
        }

        string toolId = args[offset].Trim();
        string dataDir = DefaultDataDir();
        int idx = offset + 1;
        while (idx < args.Length)
        {
            if (args[idx] == "--data-dir" && idx + 1 < args.Length)
            {
                dataDir = args[idx + 1];
                idx += 2;
            }
            else
            {
                idx++;
            }
        }

        string fullDataDir;
        try { fullDataDir = Path.GetFullPath(dataDir); }
        catch { fullDataDir = dataDir; }

        JavaScriptSerializer ser = new JavaScriptSerializer { MaxJsonLength = 8 * 1024 * 1024 };

        string toolName = toolId;
        string rawCmd = "";
        List<string> cmdArgs = new List<string>();
        Dictionary<string, string> allowedEnv = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        string vaultKey = "";

        if (IsVaultPinProtected(fullDataDir, ser))
        {
            // PIN-protected mode: NEVER trust disk aiconomy-bridge-specs.json! Fetch authoritative launch spec from unlocked GUI in RAM.
            bool lockedErr;
            bool deniedErr;
            Dictionary<string, object> authSpec = RequestLaunchSpecFromGuiPipe(toolId, fullDataDir, ser, out lockedErr, out deniedErr);
            if (authSpec == null)
            {
                if (lockedErr)
                {
                    Console.Error.WriteLine("AIconomy vault is locked with a Master Passphrase. Open AIconomy and unlock your vault before starting '" + toolId + "'.");
                }
                else
                {
                    Console.Error.WriteLine("AIconomy --mcp-exec: launch denied for '" + toolId + "' (ensure Tools are Started and tool is enabled in AIconomy).");
                }
                return 3;
            }
            if (authSpec.ContainsKey("name") && authSpec["name"] != null) toolName = authSpec["name"].ToString();
            if (authSpec.ContainsKey("cmd") && authSpec["cmd"] != null) rawCmd = authSpec["cmd"].ToString();
            if (authSpec.ContainsKey("vault_key") && authSpec["vault_key"] != null) vaultKey = authSpec["vault_key"].ToString();
            if (authSpec.ContainsKey("args") && authSpec["args"] is IEnumerable)
            {
                foreach (object item in (IEnumerable)authSpec["args"])
                {
                    if (item != null) cmdArgs.Add(item.ToString());
                }
            }
            if (authSpec.ContainsKey("env") && authSpec["env"] is Dictionary<string, object>)
            {
                foreach (KeyValuePair<string, object> kv in (Dictionary<string, object>)authSpec["env"])
                {
                    if (kv.Value != null) allowedEnv[kv.Key] = kv.Value.ToString();
                }
            }
        }
        else
        {
            string specsPath = Path.Combine(fullDataDir, "aiconomy-bridge-specs.json");
            if (!File.Exists(specsPath))
            {
                Console.Error.WriteLine("AIconomy --mcp-exec: bridge manifest missing (" + specsPath + "). Start Tools in AIconomy first.");
                return 2;
            }

            Dictionary<string, object> rootDoc;
            try
            {
                rootDoc = ser.Deserialize<Dictionary<string, object>>(File.ReadAllText(specsPath, Encoding.UTF8));
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("AIconomy --mcp-exec: invalid bridge manifest: " + ex.Message);
                return 2;
            }

            Dictionary<string, object> toolsMap = rootDoc != null && rootDoc.ContainsKey("tools")
                ? rootDoc["tools"] as Dictionary<string, object>
                : null;
            if (toolsMap == null || !toolsMap.ContainsKey(toolId))
            {
                Console.Error.WriteLine("AIconomy --mcp-exec: unknown or inactive tool '" + toolId + "'.");
                return 2;
            }

            Dictionary<string, object> spec = toolsMap[toolId] as Dictionary<string, object>;
            if (spec == null) return 2;

            toolName = spec.ContainsKey("name") && spec["name"] != null ? spec["name"].ToString() : toolId;
            rawCmd = spec.ContainsKey("cmd") && spec["cmd"] != null ? spec["cmd"].ToString() : "";
            if (spec.ContainsKey("args") && spec["args"] is IEnumerable)
            {
                foreach (object item in (IEnumerable)spec["args"])
                {
                    if (item != null) cmdArgs.Add(item.ToString());
                }
            }
            if (spec.ContainsKey("env") && spec["env"] is Dictionary<string, object>)
            {
                foreach (KeyValuePair<string, object> kv in (Dictionary<string, object>)spec["env"])
                {
                    if (kv.Value != null) allowedEnv[kv.Key] = kv.Value.ToString();
                }
            }

            vaultKey = spec.ContainsKey("vault_key") && spec["vault_key"] != null ? spec["vault_key"].ToString() : "";
            bool vaultReq = spec.ContainsKey("vault_required") && spec["vault_required"] is bool && (bool)spec["vault_required"];
            string secretArgFlag = spec.ContainsKey("secret_arg_flag") && spec["secret_arg_flag"] != null ? spec["secret_arg_flag"].ToString() : "";
            string secretEnvVar = spec.ContainsKey("secret_env_var") && spec["secret_env_var"] != null ? spec["secret_env_var"].ToString() : vaultKey;
            bool oauthMode = spec.ContainsKey("oauth_mode") && spec["oauth_mode"] is bool && (bool)spec["oauth_mode"];
            string oauthCliBin = spec.ContainsKey("oauth_cli_bin") && spec["oauth_cli_bin"] != null ? spec["oauth_cli_bin"].ToString() : "";
            List<string> oauthTokenArgs = new List<string>();
            if (spec.ContainsKey("oauth_token_args") && spec["oauth_token_args"] is IEnumerable)
            {
                foreach (object item in (IEnumerable)spec["oauth_token_args"])
                {
                    if (item != null) oauthTokenArgs.Add(item.ToString());
                }
            }

            string secretVal = "";
            if (oauthMode && !string.IsNullOrEmpty(oauthCliBin) && !string.IsNullOrEmpty(vaultKey))
            {
                secretVal = ResolveCliOAuthToken(oauthCliBin, oauthTokenArgs);
                if (string.IsNullOrEmpty(secretVal) && vaultReq)
                {
                    Console.Error.WriteLine("AIconomy --mcp-exec: OAuth CLI token unavailable for '" + toolName + "'.");
                    return 3;
                }
            }
            else if (!string.IsNullOrEmpty(vaultKey))
            {
                string vaultPath = Path.Combine(fullDataDir, "aiconomy-vault.dpapi.json");
                if (File.Exists(vaultPath))
                {
                    try
                    {
                        Dictionary<string, object> vDoc = ser.Deserialize<Dictionary<string, object>>(File.ReadAllText(vaultPath, Encoding.UTF8));
                        if (vDoc != null && vDoc.ContainsKey(vaultKey) && vDoc[vaultKey] is string)
                        {
                            secretVal = DecryptDpapiUnprotected((string)vDoc[vaultKey]);
                        }
                    }
                    catch { }
                }

                if (string.IsNullOrEmpty(secretVal) && vaultReq)
                {
                    Console.Error.WriteLine("AIconomy --mcp-exec: missing required credential for '" + toolName + "'.");
                    return 3;
                }
            }

            if (!string.IsNullOrEmpty(secretVal))
            {
                if (secretArgFlag == "__PG_POSITIONAL__")
                {
                    string cleanPgUri;
                    string pgPw;
                    SplitPostgresUriSecret(secretVal, out cleanPgUri, out pgPw);
                    if (!string.IsNullOrEmpty(cleanPgUri) && !cmdArgs.Contains(cleanPgUri))
                    {
                        cmdArgs.Add(cleanPgUri);
                    }
                    if (!string.IsNullOrEmpty(pgPw))
                    {
                        allowedEnv["PGPASSWORD"] = pgPw;
                    }
                }
                else if (secretArgFlag == "__POSITIONAL__")
                {
                    if (!cmdArgs.Contains(secretVal)) cmdArgs.Add(secretVal);
                }
                else if (!string.IsNullOrEmpty(secretArgFlag) && !cmdArgs.Contains(secretArgFlag))
                {
                    cmdArgs.Add(secretArgFlag);
                    cmdArgs.Add(secretVal);
                }

                if (!string.IsNullOrEmpty(secretEnvVar) && secretArgFlag != "__PG_POSITIONAL__")
                {
                    allowedEnv[secretEnvVar] = secretVal;
                }
            }
        }

        if (string.IsNullOrEmpty(rawCmd))
        {
            Console.Error.WriteLine("AIconomy --mcp-exec: missing command for '" + toolName + "'.");
            return 2;
        }

        string exePath = ResolveExecutable(rawCmd);
        string unwrappedNode;
        List<string> unwrappedArgs;
        if (TryUnwrapNodeBatchWrapper(exePath, cmdArgs, out unwrappedNode, out unwrappedArgs))
        {
            exePath = unwrappedNode;
            cmdArgs = unwrappedArgs;
        }

        bool isBatch = exePath.EndsWith(".cmd", StringComparison.OrdinalIgnoreCase)
            || exePath.EndsWith(".bat", StringComparison.OrdinalIgnoreCase);

        string fullCmdLine = isBatch
            ? ("cmd.exe /d /s /c \"" + QuoteBatchArg(exePath) + (cmdArgs.Count > 0 ? " " + JoinBatchArgs(cmdArgs) : "") + "\"")
            : (QuoteWinArg(exePath) + (cmdArgs.Count > 0 ? " " + JoinWindowsArgs(cmdArgs) : ""));

        HashSet<string> keepKeys = new HashSet<string>(allowedEnv.Keys, StringComparer.OrdinalIgnoreCase);
        if (!string.IsNullOrEmpty(vaultKey)) keepKeys.Add(vaultKey);

        SortedDictionary<string, string> childEnv = new SortedDictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (DictionaryEntry de in Environment.GetEnvironmentVariables())
        {
            string k = de.Key != null ? de.Key.ToString() : "";
            string v = de.Value != null ? de.Value.ToString() : "";
            if (string.IsNullOrEmpty(k)) continue;
            if (!keepKeys.Contains(k) && IsSensitiveKey(k)) continue;
            childEnv[k] = v;
        }
        if (!childEnv.ContainsKey("npm_config_ignore_scripts"))
        {
            childEnv["npm_config_ignore_scripts"] = "true";
        }
        foreach (KeyValuePair<string, string> kv in allowedEnv) childEnv[kv.Key] = kv.Value;

        StringBuilder envBuilder = new StringBuilder();
        foreach (KeyValuePair<string, string> kv in childEnv)
        {
            envBuilder.Append(kv.Key).Append('=').Append(kv.Value).Append('\0');
        }
        envBuilder.Append('\0');
        byte[] envBytes = Encoding.Unicode.GetBytes(envBuilder.ToString());

        IntPtr hIn = GetStdHandle(-10);
        IntPtr hOut = GetStdHandle(-11);
        IntPtr hErr = GetStdHandle(-12);
        if (hIn != IntPtr.Zero && hIn != new IntPtr(-1)) SetHandleInformation(hIn, 1, 1);
        if (hOut != IntPtr.Zero && hOut != new IntPtr(-1)) SetHandleInformation(hOut, 1, 1);
        if (hErr != IntPtr.Zero && hErr != new IntPtr(-1)) SetHandleInformation(hErr, 1, 1);

        STARTUPINFOW si = new STARTUPINFOW();
        si.cb = Marshal.SizeOf(typeof(STARTUPINFOW));
        si.dwFlags = 0x00000100; // STARTF_USESTDHANDLES
        si.hStdInput = hIn;
        si.hStdOutput = hOut;
        si.hStdError = hErr;

        IntPtr hJob = EnsureKillOnCloseJob();
        PROCESS_INFORMATION pi;
        StringBuilder mutableCmd = new StringBuilder(fullCmdLine);
        GCHandle envHandle = GCHandle.Alloc(envBytes, GCHandleType.Pinned);
        try
        {
            // CREATE_NO_WINDOW (0x08000000) | CREATE_UNICODE_ENVIRONMENT (0x00000400)
            bool started = CreateProcessW(
                null,
                mutableCmd,
                IntPtr.Zero,
                IntPtr.Zero,
                true,
                0x08000400u,
                envHandle.AddrOfPinnedObject(),
                null,
                ref si,
                out pi
            );
            if (!started)
            {
                int err = Marshal.GetLastWin32Error();
                Console.Error.WriteLine("AIconomy --mcp-exec: CreateProcessW failed for '" + rawCmd + "' (Win32 error " + err + ").");
                return 127;
            }
            if (hJob != IntPtr.Zero)
            {
                AssignProcessToJobObject(hJob, pi.hProcess);
            }
            CloseHandle(pi.hThread);
            try
            {
                WaitForSingleObject(pi.hProcess, 0xFFFFFFFFu);
                uint exitCode = 0;
                GetExitCodeProcess(pi.hProcess, out exitCode);
                return unchecked((int)exitCode);
            }
            finally
            {
                CloseHandle(pi.hProcess);
            }
        }
        finally
        {
            envHandle.Free();
        }
    }
}
