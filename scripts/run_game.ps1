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

    # Install the CUDA ONNX Runtime after sync because the CPU and GPU wheels
    # share the same module files in this package setup.
    & $uvPath pip install --python .venv\Scripts\python.exe --no-deps onnxruntime-gpu==1.24.1
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    # Download and initialize both local models before entering the game.
    & .venv\Scripts\python.exe scripts\check_voice_models.py --device cuda --tts-precision fp32 --prepare-only
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'CUDA preparation failed; preparing local models for CPU fallback.'
        & .venv\Scripts\python.exe scripts\check_voice_models.py --device cpu --tts-precision fp32 --prepare-only
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    $previousTtsBackend = $env:IRON_SNOW_TTS_BACKEND
    $previousSttBackend = $env:IRON_SNOW_STT_BACKEND
    $env:IRON_SNOW_TTS_BACKEND = 'kokoro'
    $env:IRON_SNOW_STT_BACKEND = 'whisper'
    try {
        & .venv\Scripts\python.exe -m iron_and_snow.game
        exit $LASTEXITCODE
    }
    finally {
        $env:IRON_SNOW_TTS_BACKEND = $previousTtsBackend
        $env:IRON_SNOW_STT_BACKEND = $previousSttBackend
    }
}
finally {
    Pop-Location
}
