<#
Changes machine-wide Windows crash-capture settings and records the before and
after values. Run only with explicit authorization from an elevated shell.
Without -Restore, enables automatic memory dumps and disables automatic reboot;
with -Restore, applies the script's configured baseline values.
#>

param(
    [switch]$Restore
)

$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Administrator privileges are required to change Windows crash-capture settings.'
}

$registryPath = 'HKLM:\SYSTEM\CurrentControlSet\Control\CrashControl'
$before = Get-ItemProperty $registryPath

if ($Restore) {
    $desired = [ordered]@{ CrashDumpEnabled = 3; AutoReboot = 1; LogEvent = 1 }
} else {
    $desired = [ordered]@{ CrashDumpEnabled = 7; AutoReboot = 0; LogEvent = 1 }
}

foreach ($entry in $desired.GetEnumerator()) {
    Set-ItemProperty $registryPath -Name $entry.Key -Type DWord -Value $entry.Value
}

$after = Get-ItemProperty $registryPath
$evidence = [ordered]@{
    schema = 'les-cloches-windows-crash-capture-v1'
    recorded_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    restore = [bool]$Restore
    before = [ordered]@{
        CrashDumpEnabled = $before.CrashDumpEnabled
        AutoReboot = $before.AutoReboot
        LogEvent = $before.LogEvent
    }
    after = [ordered]@{
        CrashDumpEnabled = $after.CrashDumpEnabled
        AutoReboot = $after.AutoReboot
        LogEvent = $after.LogEvent
    }
}

$output = Join-Path $PSScriptRoot 'WINDOWS_CRASH_CAPTURE_SETTINGS.json'
$temporary = "$output.tmp"
$evidence | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $temporary -Encoding utf8
Move-Item -LiteralPath $temporary -Destination $output -Force
$evidence | ConvertTo-Json -Depth 4
