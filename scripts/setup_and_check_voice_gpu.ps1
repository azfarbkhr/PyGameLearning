param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $CheckArguments
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
$uvPath = if ($uvCommand) { $uvCommand.Source } else { Join-Path $env:USERPROFILE '.local\bin\uv.exe' }

if (-not (Test-Path -LiteralPath $uvPath)) {
    throw "uv was not found. Install uv and reopen PowerShell, or add it to PATH."
}

Push-Location $projectRoot
try {
    & $uvPath sync --group voice-gpu
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    # kokoro-onnx declares both CPU and GPU ONNX Runtime distributions. They
    # share files, so overlay the GPU wheel after uv has installed the group.
    & $uvPath pip install --python .venv\Scripts\python.exe --no-deps onnxruntime-gpu==1.24.1
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    & .venv\Scripts\python.exe scripts\check_voice_models.py @CheckArguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
