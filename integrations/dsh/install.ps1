param(
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$DataDir,
    [string]$DshCommand = 'dsh',
    [string]$DshHome = $(if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $env:USERPROFILE '.dsh' }),
    # Optional pre-fetched adapter tree. Defaults to this script's directory so the
    # existing checkout workflow keeps working unchanged.
    [string]$PluginDir = $PSScriptRoot,
    # Packed local package avoids pnpm directory links losing host peer resolution.
    [string]$PackageFile = '',
    # Plan only: report what would change without installing or editing config.
    [switch]$DryRun,
    # Only for an isolated, non-default DSH home during testing. The live
    # desktop profile must still be closed before it is modified.
    [switch]$SkipRunningCheck,
    # Machine-readable result on stdout.
    [switch]$Json
)
$ErrorActionPreference = 'Stop'
# Only the official package manager changes the Desktop profile's dependencies.
# Run after fully exiting DSH; never change its installed source or binaries.
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$dataPath = [IO.Path]::GetFullPath($DataDir)
$pluginPath = (Resolve-Path -LiteralPath $PluginDir).Path
$pluginSpec = 'file:' + $pluginPath.Replace('\', '/')
if ($PackageFile) {
    $pluginSpec = 'file:' + (Resolve-Path -LiteralPath $PackageFile).Path.Replace('\', '/')
}
if (-not (Test-Path -LiteralPath (Join-Path $pluginPath 'package.json'))) {
    throw "Plugin directory has no package.json: $pluginPath"
}
$profilePath = Join-Path ([IO.Path]::GetFullPath($DshHome)) 'profiles\desktop'
$patchPath = Join-Path $profilePath 'cordis.patch.yml'
if (-not (Test-Path -LiteralPath (Join-Path $profilePath 'package.json'))) {
    throw 'Open DSH Desktop once to initialize the desktop profile, then fully quit it.'
}
if (-not $DryRun -and -not $SkipRunningCheck -and (Get-Process -Name 'DeepSeek Harness' -ErrorAction SilentlyContinue)) {
    throw 'Fully quit DSH Desktop before installing the plugin.'
}
$previous = if (Test-Path -LiteralPath $patchPath) { [IO.File]::ReadAllText($patchPath) } else { '' }
$pattern = '(?ms)^# BEGIN TOOLSEED PANEL\r?\n.*?^# END TOOLSEED PANEL\r?\n?'
if ($previous -notmatch $pattern -and $previous -match '(?m)^\s*-\s*id:\s*toolseed-panel\s*$') {
    throw 'An unmanaged toolseed-panel override already exists. Review it before installing.'
}
# JSON strings are valid YAML scalars, including Windows paths and non-ASCII names.
$pythonYaml = ConvertTo-Json -InputObject $pythonPath -Compress
$dataYaml = ConvertTo-Json -InputObject $dataPath -Compress
$block = @"
# BEGIN TOOLSEED PANEL
- id: toolseed-panel
  name: dsh-toolseed
  config:
    python: $pythonYaml
    dataDir: $dataYaml
# END TOOLSEED PANEL
"@
$newPatch = [regex]::Replace($previous, $pattern, '').TrimEnd() + "`n" + $block + "`n"
$patchChanged = $newPatch -ne $previous
if ($DryRun) {
    $result = [ordered]@{
        ok = $true; dry_run = $true; plugin_dir = $pluginPath; plugin_spec = $pluginSpec; python = $pythonPath
        data_dir = $dataPath; profile = $profilePath; patch = $patchPath
        patch_changed = $patchChanged; installed = $false
    }
    if ($Json) { $result | ConvertTo-Json -Compress } else {
        Write-Output "Dry run: would install $pluginPath"
        Write-Output "Profile: $profilePath (patch changed: $patchChanged)"
    }
    exit 0
}
if (-not $PackageFile) {
    $packed = & $pythonPath -X utf8 -c 'import sys; from pathlib import Path; from toolseed.hosts import package_dsh_plugin; print(package_dsh_plugin(Path(sys.argv[1])))' $pluginPath
    if ($LASTEXITCODE -ne 0) { throw 'Could not build the local ToolSeed plugin package.' }
    $pluginSpec = 'file:' + (Resolve-Path -LiteralPath $packed).Path.Replace('\', '/')
}
$previousPlugin = $null
$packagePath = Join-Path $profilePath 'package.json'
try {
    $packageJson = Get-Content -LiteralPath $packagePath -Raw | ConvertFrom-Json
    $deps = $packageJson.dependencies
    if ($deps -and $deps.'dsh-toolseed') { $previousPlugin = $deps.'dsh-toolseed' }
} catch { }
$envPrevious = $env:DSH_HOME
try {
    $env:DSH_HOME = [IO.Path]::GetFullPath($DshHome)
    & $DshCommand plugin --profile desktop add $pluginSpec
    if ($LASTEXITCODE -ne 0) {
        # Restore a previous registration if this was an upgrade attempt.
        if ($previousPlugin) {
            try { & $DshCommand plugin --profile desktop add $previousPlugin | Out-Null } catch { }
        }
        throw "Official DSH plugin installation failed (exit $LASTEXITCODE); panel configuration was not changed."
    }
} finally {
    $env:DSH_HOME = $envPrevious
}
$patchBackup = $null
if ($patchChanged) {
    if (Test-Path -LiteralPath $patchPath) {
        $patchBackup = $patchPath + '.toolseed-backup-' + [guid]::NewGuid().ToString('N')
        Copy-Item -LiteralPath $patchPath -Destination $patchBackup
    }
    [IO.File]::WriteAllText($patchPath, $newPatch, [Text.UTF8Encoding]::new($false))
}
if ($Json) {
    [ordered]@{
        ok = $true; dry_run = $false; plugin_dir = $pluginPath; python = $pythonPath
        data_dir = $dataPath; profile = $profilePath; patch = $patchPath
        patch_backup = $patchBackup; patch_changed = $patchChanged
        previous_plugin = $previousPlugin; installed = $true
    } | ConvertTo-Json -Compress
} else {
    Write-Output 'ToolSeed panel installed. Open DSH Desktop, then Settings > ToolSeed.'
    Write-Output "Shared ToolSeed data directory: $dataPath"
}
