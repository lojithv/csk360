# Run the headless test suite. Set $env:BLENDER to blender.exe if it is not on PATH.
#   ./tools/test.ps1            all tests
#   ./tools/test.ps1 -k move    tests whose name contains "move"
param([string]$k = "")
$blender = if ($env:BLENDER) { $env:BLENDER } else { "blender" }
$root = Split-Path -Parent $PSScriptRoot
$extra = @()
if ($k) { $extra = @("--", "-k", $k) }
& $blender -b --factory-startup --python-exit-code 1 -P (Join-Path $root "tests/run_tests.py") @extra
exit $LASTEXITCODE
