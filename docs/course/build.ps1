# Builds the course PDF from chapters/*.md, in file-name order.
#   ./docs/course/build.ps1          -> lustjinn-course.pdf (dark)
#   ./docs/course/build.ps1 -Light   -> lustjinn-course-light.pdf (for printing)
# Needs pandoc and typst on PATH (winget: JohnMacFarlane.Pandoc, Typst.Typst).
#
# Two stages: pandoc turns the Markdown into Typst source (course.typ, gitignored), then typst
# compiles it. Compiling here rather than through pandoc's --pdf-engine keeps course.typ next to
# template.typ, so the paths it references (code-dark.tmTheme) resolve.
param([switch]$Light)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# @(...) keeps it an array even with one chapter: splatting a lone string passes it letter by letter.
$chapters = @(Get-ChildItem chapters -Filter *.md | Sort-Object Name | ForEach-Object { "chapters/$($_.Name)" })
$out = if ($Light) { 'lustjinn-course-light.pdf' } else { 'lustjinn-course.pdf' }
$variant = if ($Light) { @('-V', 'light=true') } else { @() }

pandoc @chapters `
  --from markdown `
  --to typst `
  --metadata-file metadata.yaml `
  --metadata "date=$(Get-Date -Format 'd MMMM yyyy')" `
  --lua-filter callouts.lua `
  --template template.typ `
  --syntax-highlighting idiomatic `
  @variant `
  --output course.typ
if ($LASTEXITCODE -ne 0) { throw "pandoc failed with exit code $LASTEXITCODE" }

typst compile course.typ $out
if ($LASTEXITCODE -ne 0) { throw "typst failed with exit code $LASTEXITCODE" }

Write-Host "Built $out"
