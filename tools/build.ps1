# Validate and build the installable extension zip into ./dist.
$blender = if ($env:BLENDER) { $env:BLENDER } else { "blender" }
$root = Split-Path -Parent $PSScriptRoot
& $blender --command extension validate (Join-Path $root "csk360")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
New-Item -ItemType Directory -Force (Join-Path $root "dist") | Out-Null
& $blender --command extension build --source-dir (Join-Path $root "csk360") --output-dir (Join-Path $root "dist")
exit $LASTEXITCODE
