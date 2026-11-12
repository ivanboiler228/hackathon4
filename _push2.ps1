$ErrorActionPreference = "Continue"

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public class CredReader9 {
    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    public static extern bool CredRead(string target, int type, int flags, out IntPtr credential);
    [DllImport("advapi32.dll")]
    public static extern void CredFree(IntPtr cred);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct CREDENTIAL {
        public uint Flags;
        public uint Type;
        public IntPtr TargetName;
        public IntPtr Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public uint CredentialBlobSize;
        public IntPtr CredentialBlob;
        public uint Persist;
        public uint AttributeCount;
        public IntPtr Attributes;
        public IntPtr TargetAlias;
        public IntPtr UserName;
    }

    public static string[] Read(string target) {
        IntPtr p;
        if (!CredRead(target, 1, 0, out p)) { return null; }
        try {
            CREDENTIAL c = (CREDENTIAL)Marshal.PtrToStructure(p, typeof(CREDENTIAL));
            string user = c.UserName == IntPtr.Zero ? "" : Marshal.PtrToStringUni(c.UserName);
            string pass = c.CredentialBlob == IntPtr.Zero ? "" : Marshal.PtrToStringUni(c.CredentialBlob, (int)(c.CredentialBlobSize / 2));
            return new string[] { user, pass };
        } finally {
            CredFree(p);
        }
    }
}
"@

$cred = [CredReader9]::Read("GitHub for Visual Studio - https://ivanboiler228@github.com/")
if (-not $cred) { Write-Output "no credential"; exit 2 }

$tmp = Join-Path $env:TEMP ("gitcred-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$oldHome = $env:HOME

try {
    $line = "https://{0}:{1}@github.com" -f $cred[0], $cred[1]
    Set-Content -Path (Join-Path $tmp ".git-credentials") -Value $line -NoNewline -Encoding ASCII
    $env:HOME = $tmp
    $env:GIT_TERMINAL_PROMPT = "0"

    $log = & cmd /c "git -c credential.helper= -c credential.helper=store push -u origin main 2>&1"
    $code = $LASTEXITCODE
    $log | ForEach-Object { Write-Output $_ }
    Write-Output ("PUSH_EXIT={0}" -f $code)
} finally {
    $env:HOME = $oldHome
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
