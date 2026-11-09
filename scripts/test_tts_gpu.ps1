param(
    [string] $Text,
    [string] $Voice = 'marius',
    [switch] $Demo
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot 'save\voice-pocket\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Pocket environment is missing. Run .\scripts\setup_pocket_gpu.ps1 first.'
}
if ($Demo -and $Text) { throw 'Choose -Text or -Demo, or use neither to type lines interactively.' }

Push-Location $projectRoot
try {
    $runArguments = @(
        'scripts/benchmark_voice_gpu.py', '--mode', 'tts', '--tts-backend', 'pocket',
        '--device', 'cuda', '--pocket-voice', $Voice, '--repeats', '1', '--stream-playback'
    )
    if ($Demo) {
        foreach ($line in @(
            'Hold the line! Stay with me!',
            'Tormund, flank left. We take Winterfell together.',
            'You missed me. Try again, if you dare!'
        )) { $runArguments += @('--text', $line) }
    }
    elseif ($Text) { $runArguments += @('--text', $Text) }
    else { $runArguments += '--interactive-text' }

    & $pythonPath @runArguments
    exit $LASTEXITCODE
}
finally { Pop-Location }
