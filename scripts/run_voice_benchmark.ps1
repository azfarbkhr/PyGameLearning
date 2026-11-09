param(
    [switch] $Pocket,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $BenchmarkArguments
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$relativePython = if ($Pocket) { 'save\voice-pocket\.venv\Scripts\python.exe' } else { '.venv\Scripts\python.exe' }
$pythonPath = Join-Path $projectRoot $relativePython
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Missing $pythonPath. See scripts/VOICE_BENCHMARK.md for setup."
}
Push-Location $projectRoot
try {
    # No uv sync here: preserve the verified CUDA ONNX Runtime installation.
    $runArguments = @('scripts/benchmark_voice_gpu.py')
    if ($Pocket) { $runArguments += @('--tts-backend', 'pocket', '--mode', 'tts') }
    if (-not $BenchmarkArguments) {
        $BenchmarkArguments = if ($Pocket) { @('--playback', '--repeats', '3') } else { @('--interactive', '--repeats', '1') }
    }
    & $pythonPath @runArguments @BenchmarkArguments
    exit $LASTEXITCODE
}
finally { Pop-Location }
