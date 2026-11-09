param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath 'save/voice-pocket/.venv/Scripts/python.exe')) {
        & uv venv save/voice-pocket/.venv --python .venv/Scripts/python.exe
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    # CUDA 12.6 build; keep it isolated from the game's ONNX/CTranslate2 DLLs.
    & uv pip install --python save/voice-pocket/.venv/Scripts/python.exe torch==2.7.1 --index-url https://download.pytorch.org/whl/cu126
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & uv pip install --python save/voice-pocket/.venv/Scripts/python.exe pocket-tts==4.0.1 soundfile pyaudio faster-whisper==1.2.1 ctranslate2==4.8.5 msvc-runtime 'av<19'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & save/voice-pocket/.venv/Scripts/python.exe -c "import torch; print('PyTorch:',torch.__version__,'CUDA:',torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CUDA unavailable')"
    exit $LASTEXITCODE
}
finally { Pop-Location }
