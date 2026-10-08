<#
Installs the terminal client as the `lustjinn-tui` command, or updates it, from this checkout.

  ./scripts/install-tui.ps1              tests first, then install
  ./scripts/install-tui.ps1 -SkipTests   install as the code stands

The command is a frozen copy with its own environment (`uv tool install`), so it keeps working
whatever you do in the repo afterwards, until you run this again. Run it when you judge the code
safe. Your settings and sign-in live apart from it (%LOCALAPPDATA%\lustjinn) and are kept.
#>
param([switch]$SkipTests)

$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path "$PSScriptRoot\..")

# A terminal opened before uv joined the PATH (VS Code keeps the PATH it started with) cannot see
# it: read the PATH as Windows has it saved now, for this script only.
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    $saved = @(
        [Environment]::GetEnvironmentVariable('Path', 'Machine'),
        [Environment]::GetEnvironmentVariable('Path', 'User'),
        $env:Path
    ) -join ';'
    $env:Path = $saved
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv is not installed: winget install astral-sh.uv, then open a new terminal.'
}

$commit = (git rev-parse --short HEAD).Trim()
$branch = (git branch --show-current).Trim()
$changed = git status --porcelain -- tui
$from = if ($changed) { "$commit on $branch, with uncommitted changes in tui/" } else { "$commit on $branch" }

if (-not $SkipTests) {
    Write-Host "Testing the terminal client ($from)..."
    uv run pytest tui/tests -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw "The terminal client's tests failed; nothing was installed." }
}

Write-Host "Installing lustjinn-tui from $from..."
uv tool install --reinstall ./tui
if ($LASTEXITCODE -ne 0) { throw "uv could not install the terminal client." }

# Record what is installed, beside the client's own settings.
$home_ = Join-Path $env:LOCALAPPDATA 'lustjinn'
New-Item -ItemType Directory -Force $home_ | Out-Null
"$from, installed $(Get-Date -Format 'yyyy-MM-dd HH:mm')" | Set-Content (Join-Path $home_ 'installed.txt')

# Where uv puts the command must be on the PATH for every new terminal; added once, then left alone.
$bin = (uv tool dir --bin).Trim()
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User') -split ';' | Where-Object { $_ }
if (-not ($userPath | Where-Object { $_.TrimEnd('\') -ieq $bin.TrimEnd('\') })) {
    uv tool update-shell
    Write-Host "Added $bin to your PATH. Open a new terminal tab for it to take effect."
}

Write-Host "Done: lustjinn-tui is $from. Run it from any new terminal: lustjinn-tui"
