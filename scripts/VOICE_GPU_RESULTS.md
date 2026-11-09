# MX450 voice benchmark results — 7 November 2026

Measured on this machine: NVIDIA GeForce MX450, 2,048 MiB VRAM, driver 555.97,
compute capability 7.5; Intel i7-1165G7, approximately 16 GB RAM; Windows 11,
Python 3.13.17. AC was connected; the Windows power plan was Balanced.

## Recommended configurations

Use **faster-whisper Base on CUDA with `int8_float32` and Pocket TTS standard
100M on CUDA** when response speed is the priority. Use **Whisper Small with
the same precision and Pocket model** when recognizing more of the phrase is
worth about 400 ms extra on the tested recording. Both combinations fit the
2 GB card in the measured standalone tests.

These are actual runs with both STT and TTS models resident, but inference runs
sequentially as in a listen-then-reply turn. The input was the existing
`save/voice-gpu-check/models/microphone_test.wav` (4.992 seconds). The TTS text was
“Hold the line! Stay with me!” in the `marius` voice. Each row has five timed runs,
excluding imports, loading and warm-up. Pocket used `english_2026-10`, FP32, one
sampler step and seed 42.

| Models resident together | STT median / p95 | TTS first chunk median / p95 | TTS complete median | Sampled peak GPU memory |
| --- | --- | --- | --- | --- |
| Base INT8/FP32 + Pocket 100M | 290 / 319 ms | 66 / 91 ms | 803 ms for 2.32 s speech | 817 MiB |
| Small INT8/FP32 + Pocket 100M | 692 / 748 ms | 76 / 85 ms | 983 ms for 2.32 s speech | 1,041 MiB |

Raw combined reports:

- Base: `save/voice-benchmarks/result-1794069464277555800.json`
- Small: `save/voice-benchmarks/result-1794069370457654800.json`

The Small output retained “can you hear me?” that Base omitted. There is no
manually verified reference transcript for this microphone file, so this is an
observed output difference, not a measured WER improvement. Increasing Base's
beam width to three did not fix this recording: its output was just
“Hello, hello, hello.” Automatic language detection also misclassified this clip
as Arabic and produced an empty transcript. **Use `--language en` for the English
test; compare `ur` and `auto` on your own Urdu/mixed recordings.** No Urdu or
code-switching accuracy claim is supported by this test corpus.

Live chunk playback was verified separately: audio reached the output callback
at **115 ms**, with **zero measured underruns** during that 2.32-second sample.
That measures submission to the audio device, not acoustic speaker latency. Raw
report: `save/voice-benchmarks/result-1794069412249003400.json`.

## What the broader comparison showed

The STT sweep used seven repetitions on the microphone recording and a 1.45-second
synthetic recording. Base's microphone medians were:

| Base CUDA compute type | Microphone median |
| --- | --- |
| FP16 | 481 ms |
| FP32 | 280 ms |
| INT8/FP16 | 325 ms |
| **INT8/FP32** | **232 ms** |

Full sweep: `save/voice-benchmarks/sweep-1794068217585261300/summary.json`.
Earlier data under `sweep-1794067983037145400` was interrupted after discovering
the game was sharing the GPU; it is not used for the recommendation.

The longer sweep induced significant GPU clock/power variation: the card
sometimes ran at 300 MHz under load with software power limiting reported.
Small's seven-run medians consequently rose into seconds. A later cooled
Small INT8/FP32 run measured **579 ms** (three repetitions), followed by the
692 ms combined run above. Do not treat the hot and cooled runs as a controlled
precision-only comparison. The script now saves clock/temperature/utilization
telemetry, and the sweep idles 15 seconds between cases by default. No driver,
power-plan, GPU-clock or fan settings were changed.

Kokoro used the existing ONNX files, two host threads, a 1 GiB CUDA arena limit
and `kSameAsRequested` arena growth. Each row used five repetitions per line:

| Kokoro CUDA configuration | “Hold the line! Stay with me!” | “Haha, you missed me!” | Sampled peak memory |
| --- | --- | --- | --- |
| FP32, exhaustive convolution search | 403 ms | 458 ms | 715 MiB |
| FP32, heuristic search | 403 ms | 344 ms | 715 MiB |
| FP32, default search | 522 ms | 396 ms | 621 MiB |
| FP16, default search | 546 ms | 549 ms | 373 MiB |
| INT8, default search | 6,883 ms | 5,029 ms | 199 MiB |

These Kokoro calls return a full waveform; the first-audio and full-audio times
are equal. Different exports produced slightly different speech durations.
Quantized ONNX graphs may mix CUDA and CPU operations; a CUDA session does not
guarantee that every kernel is on GPU. INT8 saved memory but was unsuitable for
low-latency TTS here. The arena limit does not cap all GPU allocations.
Raw sweep: `save/voice-benchmarks/sweep-1794068811663910000/summary.json`.
An additional FP32 profiling run confirmed **3,924 CUDA kernel events** and
458 CPU kernel events; this was separate from the timing sweep because profiling
adds overhead. Report: `save/voice-benchmarks/result-1794069559078807800.json`.

Pocket's smaller `english_18m_refl_2026-10` model measured **141 ms first audio**,
**1,398 ms complete** for 2.08 seconds of speech and **277 MiB peak GPU memory**
(five repetitions). It saved memory but did not beat the standard model's
measured latency. Quality needs an audition; no listener preference score was
collected. Report: `save/voice-benchmarks/result-1794069316164084100.json`.

## Run the microphone tests

From the project root, fastest measured configuration:

```powershell
.\scripts\run_voice_benchmark.ps1 -Pocket --mode both --interactive --stt-model base --compute-type int8_float32 --language en --repeats 1 --stream-playback
```

For Small, change `--stt-model base` to `--stt-model small`. Press Enter to start,
speak, press Enter to stop. Each turn displays the actual first stop-to-caption
time and streams a fixed test reply. Enter `q` at the next prompt to finish.
There is no AI dialogue-generation latency in this test.

Kokoro/Whisper uses the game's `.venv`. Pocket and its combined microphone test
use `save/voice-pocket/.venv`; both environments are inside this project and use
the same Python version. The game environment was not re-synced or replaced.
Pocket's setup script pins CUDA PyTorch 2.7.1, Pocket 4.0.1, faster-whisper 1.2.1,
CTranslate2 4.8.5 and `av<19`; PyAV 19 was found incompatible and corrected.

See [VOICE_BENCHMARK.md](VOICE_BENCHMARK.md) for setup, replay/sweep commands,
alternate voices, metric definitions and limitations. WAVs and JSON results are
under the ignored `save/voice-benchmarks/` directory. Sampled dedicated VRAM can
miss brief peaks and does not establish headroom or latency with the game running.
