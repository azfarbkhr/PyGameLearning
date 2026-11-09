"""Reproducible local voice benchmarks; run with the project's .venv Python.

Examples and metric definitions: scripts/VOICE_BENCHMARK.md.
Models stay resident during a run. No game settings are changed.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import threading
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "save" / "voice-gpu-check" / "models"
OUTPUT_DIR = ROOT / "save" / "voice-benchmarks"
DLL_HANDLES = []


def configure_cuda():
    # Keep Windows DLL-directory handles alive for the whole benchmark.
    if sys.platform != "win32":
        return
    for directory in [*Path(sys.prefix).glob("Lib/site-packages/nvidia/*/bin"),
                      Path(sys.prefix) / "Lib/site-packages/torch/lib",
                      Path(sys.prefix), Path(sys.base_prefix), Path(sys.base_prefix) / "DLLs"]:
        if directory.is_dir():
            DLL_HANDLES.append(os.add_dll_directory(str(directory)))
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
            for dll in [*directory.glob("msvcp140*.dll"), *directory.glob("vcruntime140*.dll")]:
                try:
                    ctypes.WinDLL(str(dll))
                except OSError:
                    pass


class GpuMonitor:
    """Sample total dedicated GPU memory using one low-overhead nvidia-smi process."""

    def __init__(self):
        self.samples = []
        self.telemetry = []
        self.process = None

    def start(self):
        self.initial_processes = "unavailable"
        if not shutil.which("nvidia-smi"):
            return
        self.initial_processes = subprocess.check_output(
            ["nvidia-smi", "--query-compute-apps=pid,process_name", "--format=csv,noheader"],
            text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).strip()
        if self.initial_processes:
            print(f"Other GPU processes already active (results include contention):\n{self.initial_processes}", flush=True)
        self.process = subprocess.Popen(
            ["nvidia-smi", "--query-gpu=memory.used,clocks.current.graphics,temperature.gpu,utilization.gpu,clocks_event_reasons.sw_power_cap", "--format=csv,noheader,nounits",
             "--loop-ms=100"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            try:
                parts = [part.strip() for part in line.split(",")]
                stamp = time.perf_counter()
                self.samples.append((stamp, int(parts[0])))
                self.telemetry.append({"timestamp": stamp, "clock_mhz": parts[1], "temperature_c": parts[2],
                                       "gpu_utilization_percent": parts[3], "software_power_cap": parts[4]})
            except ValueError:
                pass

    def stop(self):
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=5)
            self.process.stdout.close()


def summary(values):
    ordered = sorted(values)
    return {"runs_ms": [round(x, 2) for x in values],
            "median_ms": round(statistics.median(values), 2),
            "p95_ms": round(ordered[math.ceil(.95 * len(ordered)) - 1], 2)}


class StreamPlayer:
    """Nonblocking PCM callback so playback does not serialize GPU generation."""

    def __init__(self, rate):
        import pyaudio
        self.pa = pyaudio
        self.device = pyaudio.PyAudio()
        self.pending = bytearray()
        self.lock = threading.Lock()
        self.finished = False
        self.done = threading.Event()
        self.first_callback = None
        self.underrun_frames = 0
        self.rate = rate
        try:
            self.stream = self.device.open(format=pyaudio.paFloat32, channels=1, rate=rate,
                                           output=True, frames_per_buffer=512, stream_callback=self.callback)
        except Exception:
            self.device.terminate()
            raise

    def callback(self, input_data, frame_count, time_info, status):
        needed = frame_count * 4
        with self.lock:
            data = bytes(self.pending[:needed])
            del self.pending[:len(data)]
            if data and self.first_callback is None:
                self.first_callback = time.perf_counter()
            if len(data) < needed and self.first_callback is not None and not self.finished:
                self.underrun_frames += (needed - len(data)) // 4
            complete = self.finished and not self.pending
        if complete:
            self.done.set()
        return data.ljust(needed, b"\0"), self.pa.paComplete if complete else self.pa.paContinue

    def push(self, pcm):
        with self.lock:
            self.pending.extend(pcm.astype("float32", copy=False).tobytes())

    def close(self):
        with self.lock:
            self.finished = True
            remaining_seconds = len(self.pending) / 4 / self.rate
        try:
            if not self.done.wait(timeout=remaining_seconds + 10):
                raise RuntimeError("Audio output callback did not finish")
        finally:
            self.stream.stop_stream()
            self.stream.close()
            self.device.terminate()


def load_stt(args):
    from faster_whisper import WhisperModel
    import ctranslate2
    if args.device == "cuda":
        supported = sorted(ctranslate2.get_supported_compute_types("cuda"))
        print(f"CUDA compute types: {supported}", flush=True)
        if args.compute_type not in supported:
            raise ValueError(f"Unsupported CUDA compute type: {args.compute_type}")
    return WhisperModel(args.stt_model, device=args.device, compute_type=args.compute_type,
                        cpu_threads=args.threads, num_workers=1,
                        download_root=str(MODEL_DIR / "faster-whisper"),
                        local_files_only=args.local_files_only)


def transcribe(model, audio, args):
    segments, info = model.transcribe(
        audio, language=None if args.language == "auto" else args.language,
        task="transcribe", beam_size=args.beam_size, best_of=1, temperature=0,
        condition_on_previous_text=False, without_timestamps=True,
        word_timestamps=False, vad_filter=args.vad,
        max_new_tokens=96, hotwords=args.hotwords,
    )
    # Inference is lazy: consuming all segments belongs INSIDE the timer.
    return "".join(segment.text for segment in segments).strip(), info.language


def load_tts(args):
    if args.tts_backend == "pocket":
        os.environ.setdefault("HF_HUB_CACHE", str(ROOT / "save" / "voice-pocket" / "models"))
        import torch
        from pocket_tts import TTSModel
        torch.set_num_threads(args.threads)
        if args.device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("PyTorch CUDA is unavailable; install the documented CUDA build.")
        model = TTSModel.load_model(language=args.pocket_config, quantize=False)
        model.to(args.device).eval()
        state = model.get_state_for_audio_prompt(args.pocket_voice)
        print(f"Pocket device: {model.device}; config: {args.pocket_config}; "
              f"voice: {args.pocket_voice}", flush=True)
        if args.device == "cuda":
            torch.cuda.synchronize()
        return model, state

    import onnxruntime as ort
    from kokoro_onnx import Kokoro
    ort.set_default_logger_severity(3)
    name = {"fp32": "kokoro-v1.0.onnx", "fp16": "kokoro-v1.0.fp16.onnx",
            "int8": "kokoro-v1.0.int8.onnx"}[args.tts_precision]
    model = MODEL_DIR / name
    voices = MODEL_DIR / "voices-v1.0.bin"
    if not model.is_file() or not voices.is_file():
        raise FileNotFoundError(f"Missing {model} or {voices}; see VOICE_BENCHMARK.md")
    options = ort.SessionOptions()
    options.intra_op_num_threads = args.threads
    options.inter_op_num_threads = 1
    options.log_severity_level = 3
    if args.profile:
        options.enable_profiling = True
        options.profile_file_prefix = str(args.output / "kokoro-profile")
    providers = ["CPUExecutionProvider"]
    if args.device == "cuda":
        if "CUDAExecutionProvider" not in ort.get_available_providers():
            raise RuntimeError("CUDAExecutionProvider unavailable; no silent CPU fallback allowed.")
        providers = [("CUDAExecutionProvider", {
            "cudnn_conv_algo_search": args.conv_search.upper(),
            "arena_extend_strategy": args.arena_growth,
            "gpu_mem_limit": 1024 * 1024 * 1024,
        }), "CPUExecutionProvider"]
    session = ort.InferenceSession(str(model), sess_options=options, providers=providers)
    if args.device == "cuda" and "CUDAExecutionProvider" not in session.get_providers():
        raise RuntimeError("Kokoro failed to initialize CUDA; refusing CPU fallback.")
    session.disable_fallback()
    print(f"Kokoro providers: {session.get_providers()}", flush=True)
    return Kokoro.from_session(session, str(voices)), None


def synthesize(tts, text, args, player=None):
    import numpy as np
    model, state = tts
    if args.tts_backend == "pocket":
        import torch
        torch.manual_seed(args.seed)
    started = time.perf_counter()
    stream_stats = None
    if args.tts_backend == "pocket":
        import torch
        chunks, first_ms = [], None
        arrivals, ready_samples, needed_buffer = [], 0, 0.0
        # Pocket spawns generation threads; inference_mode tensors cannot be
        # mutated from its no_grad worker threads. Keep ordinary no_grad tensors.
        with torch.no_grad():
            for chunk in model.generate_audio_stream(state, text):
                # CPU copy synchronizes CUDA and measures audio usable by playback.
                pcm = chunk.detach().float().cpu().numpy().reshape(-1)
                arrival = (time.perf_counter() - started) * 1000
                if len(pcm):
                    if first_ms is None:
                        first_ms = arrival
                    needed_buffer = max(needed_buffer, arrival - first_ms - ready_samples / model.sample_rate * 1000)
                    arrivals.append(arrival)
                    ready_samples += len(pcm)
                    if player:
                        player.push(pcm)
                chunks.append(pcm)
        audio, rate = np.concatenate(chunks), model.sample_rate
        stream_stats = {"chunk_count": len(arrivals), "minimum_buffer_ms_for_this_run": round(needed_buffer, 2),
                        "max_chunk_gap_ms": round(max((b-a for a, b in zip(arrivals, arrivals[1:])), default=0), 2)}
    else:
        audio, rate = model.create(text, args.voice, speed=args.speed)
        audio = np.asarray(audio, dtype=np.float32)
        first_ms = (time.perf_counter() - started) * 1000
    return audio, rate, first_ms, (time.perf_counter() - started) * 1000, stream_stats


def capture(args, interactive=False):
    import pyaudio
    device = pyaudio.PyAudio()
    stream = None
    frames = []
    rate = 16000
    try:
        print(f"Microphone: {device.get_default_input_device_info()['name']}", flush=True)
        if interactive:
            if input("Enter = start recording; q = quit: ").strip().lower() == "q":
                return None
        else:
            print(f"Recording {args.record_seconds:g}s after a three-second countdown.", flush=True)
            for value in (3, 2, 1):
                print(value, flush=True)
                time.sleep(1)

        def callback(data, frame_count, time_info, status):
            frames.append(data)
            return None, pyaudio.paContinue

        stream = device.open(format=pyaudio.paInt16, channels=1, rate=rate, input=True,
                             frames_per_buffer=512, stream_callback=callback)
        if interactive:
            input("RECORDING — speak now; press Enter to stop and transcribe: ")
        else:
            print("RECORDING — speak now.", flush=True)
            time.sleep(args.record_seconds)
        released = time.perf_counter()
        stream.stop_stream()
        stream.close()
        stream = None
    finally:
        if stream:
            stream.close()
        device.terminate()
    path = args.output / f"microphone-{time.time_ns()}.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"".join(frames))
    return path, released


def benchmark_stt(model, path, args, release=None):
    import soundfile as sf
    duration = sf.info(str(path)).duration
    if not .1 <= duration <= 30:
        raise ValueError("Use a speech clip between 0.1 and 30 seconds.")
    runs, transcripts, release_ms = [], [], None
    # Warm on a fixture, never consume an untimed pass of a fresh microphone clip.
    for index in range(args.repeats):
        started = time.perf_counter()
        text, language = transcribe(model, str(path), args)
        finished = time.perf_counter()
        if index == 0 and release is not None:
            release_ms = (finished - release) * 1000
            print(f"CAPTION ({language}): {text}\nStop-to-caption: {release_ms:.0f} ms", flush=True)
        runs.append((finished - started) * 1000)
        transcripts.append(text)
    result = {"audio": str(path), "audio_seconds": duration, "language": language,
              "transcripts": transcripts, **summary(runs)}
    if release_ms is not None:
        result["stop_to_caption_ms"] = round(release_ms, 2)
    print(f"STT {args.stt_model}/{args.compute_type}: {result['median_ms']} ms median, "
          f"{result['p95_ms']} ms p95 for {duration:.2f}s audio", flush=True)
    print(f"Recognized ({language}): {transcripts[0]}", flush=True)
    if release_ms is not None:
        print(f"First stop-to-caption: {release_ms:.0f} ms (includes mic cleanup + WAV write)", flush=True)
    return result


def benchmark_tts(tts, text, args):
    import soundfile as sf
    runs, firsts, stream_runs = [], [], []
    for _ in range(args.repeats):
        player = StreamPlayer(tts[0].sample_rate) if args.stream_playback else None
        started = time.perf_counter()
        try:
            audio, rate, first, total, stream_stats = synthesize(tts, text, args, player)
        finally:
            if player:
                player.close()
        if player and stream_stats:
            stream_stats["first_output_callback_ms"] = round((player.first_callback - started) * 1000, 2) if player.first_callback else None
            stream_stats["underrun_ms_after_start"] = round(player.underrun_frames / rate * 1000, 2)
        firsts.append(first)
        runs.append(total)
        if stream_stats:
            stream_runs.append(stream_stats)
    path = args.output / f"{args.tts_backend}-{time.time_ns()}.wav"
    sf.write(str(path), audio, rate, subtype="PCM_16")
    result = {"text": text, "audio": str(path), "audio_seconds": len(audio) / rate,
              "first_audio": summary(firsts), "full_audio": summary(runs)}
    if stream_runs:
        result["streaming_runs"] = stream_runs
    print(f"TTS {args.tts_backend}/{args.tts_precision}: "
          f"first {result['first_audio']['median_ms']} ms; full {result['full_audio']['median_ms']} ms; "
          f"{result['audio_seconds']:.2f}s speech", flush=True)
    if args.stream_playback and stream_runs:
        latest = stream_runs[-1]
        print(f"Playback first output: {latest['first_output_callback_ms']} ms; "
              f"underruns: {latest['underrun_ms_after_start']} ms\nSaved audio: {path}", flush=True)
    if args.playback and not args.stream_playback:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("stt", "tts", "both"), default="both")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--stt-model", default="base")
    parser.add_argument("--compute-type", default="int8_float32")
    parser.add_argument("--language", default="en", help="en (fast English default), ur or auto")
    parser.add_argument("--beam-size", type=int, default=1)
    parser.add_argument("--vad", action="store_true")
    parser.add_argument("--hotwords", default=None)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--audio", type=Path, action="append")
    parser.add_argument("--mic", action="store_true", help="Record a fixed-length clip")
    parser.add_argument("--interactive", action="store_true", help="Repeated Enter-to-start/stop mic tests")
    parser.add_argument("--interactive-text", action="store_true", help="Type text repeatedly to audition TTS")
    parser.add_argument("--record-seconds", type=float, default=5)
    parser.add_argument("--tts-backend", choices=("kokoro", "pocket"), default="kokoro")
    parser.add_argument("--tts-precision", choices=("fp32", "fp16", "int8"), default="fp32")
    parser.add_argument("--voice", default="am_michael")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--pocket-config", default="english_2026-10")
    parser.add_argument("--pocket-voice", default="marius")
    parser.add_argument("--seed", type=int, default=42, help="Repeatable Pocket synthesis sampling")
    parser.add_argument("--text", action="append")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--conv-search", choices=("heuristic", "exhaustive", "default"), default="heuristic")
    parser.add_argument("--arena-growth", choices=("kSameAsRequested", "kNextPowerOfTwo"), default="kSameAsRequested")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--playback", action="store_true")
    parser.add_argument("--stream-playback", action="store_true", help="Play Pocket chunks immediately; use --repeats 1")
    parser.add_argument("--profile", action="store_true", help="Record Kokoro ORT kernel placement; adds timing overhead")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    if args.repeats < 1 or args.threads < 1 or not 0 < args.record_seconds <= 30 or args.beam_size < 1:
        parser.error("repeats, threads and beam-size must be positive; recording must be <=30s")
    if sum(bool(x) for x in (args.audio, args.mic, args.interactive)) > 1:
        parser.error("Choose --audio, --mic or --interactive")
    if args.mode == "tts" and (args.audio or args.mic or args.interactive):
        parser.error("Audio capture requires --mode stt or both")
    if args.interactive_text and (args.mode != "tts" or args.audio or args.mic or args.interactive):
        parser.error("--interactive-text requires --mode tts without microphone/audio input")
    if args.stream_playback and (args.tts_backend != "pocket" or args.mode == "stt"):
        parser.error("--stream-playback requires Pocket TTS")
    if args.device == "cpu" and args.compute_type in ("int8_float16", "int8_float32"):
        args.compute_type = "int8"
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.tts_backend == "pocket":
        os.environ.setdefault("HF_HUB_CACHE", str(ROOT / "save" / "voice-pocket" / "models"))
    configure_cuda()
    versions = {}
    for package in ("faster-whisper", "ctranslate2", "kokoro-onnx", "onnxruntime-gpu", "torch", "pocket-tts", "numpy", "av"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    report = {"python": sys.executable, "platform": platform.platform(), "packages": versions,
              "settings": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
              "results": []}
    print(f"Python: {sys.executable}\nPackages: {versions}", flush=True)
    print("Timing excludes imports/model loading; first microphone pass is never warmed on your clip.", flush=True)
    monitor = GpuMonitor()
    monitor.start()
    report["gpu_processes_before"] = monitor.initial_processes
    tts = None
    try:
        started = time.perf_counter()
        stt = load_stt(args) if args.mode != "tts" else None
        tts = load_tts(args) if args.mode != "stt" else None
        report["load_seconds"] = round(time.perf_counter() - started, 3)
        # Fixed silent fixture for initialization: excludes cold CUDA setup, not speech accuracy.
        if stt:
            import numpy as np
            transcribe(stt, np.zeros(16000, dtype=np.float32), args)
        texts = args.text or ["Hold the line! Stay with me!"]
        if tts:
            synthesize(tts, texts[0], args)
        print(f"Models ready after {report['load_seconds']}s loading + warm-up.", flush=True)
        if args.interactive_text:
            print("Type a line and press Enter to hear it. Enter q to quit. Models stay loaded.", flush=True)
            while True:
                try:
                    text = input("Say: ").strip()
                except EOFError:
                    break
                if text.lower() == "q":
                    break
                if text:
                    report["results"].append({"tts": benchmark_tts(tts, text, args)})
        elif args.interactive:
            while (captured := capture(args, interactive=True)) is not None:
                path, release = captured
                row = {"stt": benchmark_stt(stt, path, args, release)}
                if tts:
                    row["tts"] = benchmark_tts(tts, texts[0], args)
                report["results"].append(row)
        else:
            if stt:
                captures = ([capture(args)] if args.mic else
                            [(p.resolve(), None) for p in (args.audio or [MODEL_DIR / "microphone_test.wav"])])
                for path, release in captures:
                    report["results"].append({"stt": benchmark_stt(stt, path, args, release)})
            if tts:
                for text in texts:
                    report["results"].append({"tts": benchmark_tts(tts, text, args)})
    except KeyboardInterrupt:
        report["interrupted"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(report["error"], file=sys.stderr, flush=True)
    finally:
        if args.profile and tts and args.tts_backend == "kokoro":
            profile = tts[0].sess.end_profiling()
            events = json.loads(Path(profile).read_text(encoding="utf-8"))
            provider_counts = {}
            for event in events:
                provider = event.get("args", {}).get("provider")
                if provider:
                    provider_counts[provider] = provider_counts.get(provider, 0) + 1
            report["kokoro_profile"] = {"file": profile, "kernel_event_counts": provider_counts}
            print(f"ORT kernel placement: {provider_counts}", flush=True)
        monitor.stop()
        report["gpu_memory"] = {"sample_interval_ms": 100, "scope": "all GPU processes, sampled not allocator peak",
                                "sampled_peak_mib": max((m for _, m in monitor.samples), default=None),
                                "last_mib": monitor.samples[-1][1] if monitor.samples else None}
        report["gpu_telemetry"] = monitor.telemetry
        target = args.output / f"result-{time.time_ns()}.json"
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"GPU memory: {report['gpu_memory']}\nReport: {target}", flush=True)
    return 1 if "error" in report else 0


if __name__ == "__main__":
    raise SystemExit(main())
