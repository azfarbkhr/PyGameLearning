# Local GPU voice tests

Run these commands from `D:\WorkPersonal\PyGameLearning` in PowerShell. The
Kokoro/Whisper tests use the game's exact `.venv\Scripts\python.exe`. There is no
global Python install and the launcher does not run `uv sync` or change the game.
Close the game and other GPU workloads for clean comparisons. An active game can
be used deliberately for a separate load test; the report records existing GPU
processes so these results can be distinguished.

## Speak and measure latency

```powershell
.\scripts\run_voice_benchmark.ps1
```

Models load and warm up once. Press **Enter** to start recording, speak, then
press **Enter** again to stop. The caption and stop-to-caption latency appear
immediately after recognition. Enter `q` at the next start prompt to exit and save
the report. Recordings remain local. Ctrl+C also saves accumulated results.

Explicit settings (replace these with the winner in the results report):

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_voice_gpu.py --interactive --stt-model base --compute-type int8_float32 --language en --repeats 1
```

Use `--language en` for an English-only comparison, `--language ur` for Urdu, and
`--language auto` for automatic language detection. Multilingual models support
Urdu, but code-switching accuracy must be judged on your recordings. The benchmark
does not apply game actions or claim accuracy from timing alone. Add
`--hotwords "Ramsay, Tormund, Sansa, Winterfell"` to compare name recognition.
The default is explicitly English: automatic detection misclassified the existing
microphone fixture as Arabic and returned an empty transcript in a measured run.

To record for a fixed duration instead of using Enter to stop:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_voice_gpu.py --mic --record-seconds 5 --stt-model base --compute-type int8_float32 --language en --repeats 1
```

The fixed-duration test has a three-second countdown. Its stop-to-caption metric
starts after the configured recording duration, not after the last spoken word.

## Type text and hear speech

```powershell
.\scripts\test_tts_gpu.ps1
```

This TTS-only test uses Pocket on the MX450, without loading recognition or
recording your microphone. Type any English line at `Say:` and press Enter.
It streams the speech immediately and reports first-chunk readiness, first audio
output callback, full synthesis time and playback underruns. Models stay loaded
between lines. Enter `q` to exit and save the JSON report.

To speak one supplied line, play three sample battlefield lines, or select a
different voice:

```powershell
.\scripts\test_tts_gpu.ps1 -Text "Hold the line! Stay with me!"
.\scripts\test_tts_gpu.ps1 -Demo
.\scripts\test_tts_gpu.ps1 -Voice javert
```

The default voice is `marius`. A newly selected voice may download its embedding
once. The test uses the already prepared `save/voice-pocket/.venv`, and saves WAVs
and timing reports under `save/voice-benchmarks/`.

## Replay an identical clip or compare settings

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_voice_gpu.py --audio save\voice-gpu-check\models\microphone_test.wav --stt-model small --compute-type int8_float32 --language en --repeats 7
.\.venv\Scripts\python.exe scripts\sweep_voice_gpu.py --section stt --repeats 7 --audio save\voice-gpu-check\models\microphone_test.wav
.\.venv\Scripts\python.exe scripts\sweep_voice_gpu.py --section tts --repeats 5
```

The sweep runs each case in a separate process, sequentially. It tests Base and
Small across FP16, FP32, INT8/FP16 and INT8/FP32, or Kokoro precision/convolution
search variants. It retains errors and raw logs. Models must already be cached
for the STT sweep; a regular run can download a requested model on first use.

TTS-only audition (uses the selected character voice, without recording):

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_voice_gpu.py --mode tts --tts-precision fp32 --conv-search exhaustive --voice am_michael --text "Hold the line! Stay with me!" --playback
```

Use `--voice am_fenrir`, `--voice af_bella`, or another installed Kokoro voice to
audition alternatives. Use `--speed 1.1` only as a speaking-rate experiment, not
as a substitute for measuring synthesis latency. FP16 and INT8 files must exist
under `save/voice-gpu-check/models` before selecting those precisions.

## Pocket TTS GPU comparison

Pocket runs in a project-local isolated environment because its CUDA PyTorch
build has different dependency/DLL needs from the game's ONNX Runtime stack:

```powershell
.\scripts\setup_pocket_gpu.ps1
.\scripts\run_voice_benchmark.ps1 -Pocket --text "Hold the line! Stay with me!" --repeats 5 --playback
```

This downloads a large CUDA PyTorch wheel the first time. The setup pins
`torch==2.7.1` from the official CUDA 12.6 index and `pocket-tts==4.0.1`.
The official weights require accepting the model terms at
<https://huggingface.co/kyutai/pocket-tts> and local authentication:

```powershell
.\.venv\Scripts\hf.exe auth login
```

Never put a Hugging Face token in a script or report. The standard shared
Hugging Face credential cache is used. Model downloads are excluded from timing.
Pocket's default test uses `english_2026-10`, one sampler step, the `marius`
voice and CUDA FP32. It synchronizes each chunk to CPU before measuring when
audio becomes usable. Pocket does not offer official Urdu synthesis here.
Pocket weights are cached inside `save/voice-pocket/models/`. Sampling uses seed
42 for repeatable audition comparisons; change it with `--seed`.

The isolated environment also includes faster-whisper so a combined microphone
test can be run explicitly:

```powershell
.\save\voice-pocket\.venv\Scripts\python.exe scripts\benchmark_voice_gpu.py --tts-backend pocket --mode both --interactive --stt-model base --compute-type int8_float32 --language en --repeats 1 --stream-playback
```

This last command plays Pocket chunks as they arrive, using a nonblocking audio
callback. Each turn speaks a fixed benchmark reply, not an AI-generated answer.
Its report includes the first output callback time and any playback underruns.
Callback submission time is still not an acoustic measurement at the speaker.
The environment pins `av<19` to match the game: PyAV 19 breaks the audio decoder
used by faster-whisper 1.2.1.

For a smaller-memory Pocket comparison, add
`--pocket-config english_18m_refl_2026-10`. This is a separate 18.2M model and
requires its own small weights/voice embedding download. Smaller parameter count
does not guarantee faster generation; compare its saved audio and timings with
the standard model before selecting it.

## What the numbers mean

- `median_ms` / `p95_ms`: wall time for complete STT decoding, including file
  decode and consumption of the lazy segment iterator. Small sample p95 values
  are descriptive, not statistical guarantees.
- `stop_to_caption_ms`: the **first** result on a new microphone recording,
  including stream cleanup and writing/reading its WAV. No untimed decoding of
  that recording occurs first. It excludes time spent speaking.
- `first_audio`: synthesis start to audio ready on CPU. For this Kokoro call it
  is the full waveform; Pocket yields actual streaming chunks.
- `full_audio`: time to produce the complete waveform; playback duration and
  writing the result WAV are excluded. `--playback` auditions the completed WAV
  **after** timing; it does not measure speaker/device latency or stream playback.
  `--stream-playback` is the separate Pocket-only live chunk playback option.
- Pocket's `streaming_runs` records chunk gaps and the extra initial buffer that
  would have avoided an underrun for that particular measured run. This is a
  diagnostic, not a worst-case guarantee for live gameplay.
- `gpu_memory.sampled_peak_mib`: total dedicated GPU memory sampled every 100ms
  with one `nvidia-smi` process, including other processes. It can miss brief
  peaks; it is not an allocator peak, and successful operation is not a guarantee
  of enough headroom with the game running.
- Cold imports, downloads, model loading and warm-up are excluded from warm
  inference timing. STT warms on a separate silent fixture; TTS warms on a fixed
  line. Use the saved per-run values to inspect first-pass effects.
- `gpu_telemetry` records clocks, temperature, utilization and software power
  limiting. The sweep idles 15 seconds between configurations by default;
  increase `--cooldown-seconds` when the laptop is limiting clocks. Results under
  power limiting must not be treated as a pure model-precision comparison.

Results, recordings and audition WAVs are stored under `save/voice-benchmarks/`.
Every JSON includes the Python executable, package versions and exact settings.
The GPU path refuses whole-session CPU fallback; some ONNX shape operations may
still run on CPU. `--profile` records actual kernel provider placement but adds
overhead, so use it separately from timing comparisons.

For a new checkout, the existing `setup_and_check_voice_gpu.ps1` installs the
game's optional voice dependencies and overlays ONNX Runtime GPU 1.24.1.
Running `uv sync` afterward can replace that overlay. The benchmark launcher
intentionally uses the interpreter directly to preserve the tested environment.
