param(
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$DataDir,
    [string]$DshCommand = 'dsh',
    [string]$DshHome = $(if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $env:USERPROFILE '.dsh' })
)
$ErrorActionPreference = 'Stop'
# Only the official package manager changes the Desktop profile's dependencies.
# Run after fully exiting DSH; never change its installed source or binaries.
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$dataPath = [IO.Path]::GetFullPath($DataDir)
$profilePath = Join-Path ([IO.Path]::GetFullPath($DshHome)) 'profiles\desktop'
$patchPath = Join-Path $profilePath 'cordis.patch.yml'
if (-not (Test-Path -LiteralPath (Join-Path $profilePath 'package.json'))) {
    throw 'Open DSH Desktop once to initialize the desktop profile, then fully quit it.'
}
if (Get-Process -Name 'DeepSeek Harness' -ErrorAction SilentlyContinue) {
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
$envPrevious = $env:DSH_HOME
try {
    $env:DSH_HOME = [IO.Path]::GetFullPath($DshHome)
    & $DshCommand plugin --profile desktop add $PSScriptRoot
    if ($LASTEXITCODE -ne 0) { throw "Official DSH plugin installation failed (exit $LASTEXITCODE); panel configuration was not changed." }
} finally {
    $env:DSH_HOME = $envPrevious
}
if ($newPatch -ne $previous) {
    if (Test-Path -LiteralPath $patchPath) {
        Copy-Item -LiteralPath $patchPath -Destination ($patchPath + '.toolseed-backup-' + [guid]::NewGuid().ToString('N'))
    }
    [IO.File]::WriteAllText($patchPath, $newPatch, [Text.UTF8Encoding]::new($false))
}
Write-Output 'ToolSeed panel installed. Open DSH Desktop, then Settings > ToolSeed.'
Write-Output "Shared ToolSeed data directory: $dataPath"
