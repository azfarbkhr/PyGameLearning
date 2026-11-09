r"""Smoke-test local Kokoro TTS and faster-whisper on CUDA or CPU.

Run the Windows setup and check with:
    .\scripts\setup_and_check_voice_gpu.ps1

The first run downloads the Kokoro ONNX files and multilingual faster-whisper tiny.
Pass --audio path/to/clip.wav to test a recording instead of synthesized audio.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "save" / "voice-gpu-check" / "models"
KOKORO_VOICES = MODEL_DIR / "voices-v1.0.bin"
KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
KOKORO_MODELS = {
    "int8": (
        MODEL_DIR / "kokoro-v1.0.int8.onnx",
        f"{KOKORO_RELEASE}/kokoro-v1.0.int8.onnx",
    ),
    "fp32": (
        MODEL_DIR / "kokoro-v1.0.onnx",
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx",
    ),
}


def configure_windows_cuda_dlls() -> None:
    """Expose pip-installed CUDA/cuDNN DLLs before importing their consumers."""
    if sys.platform != "win32":
        return

    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    nvidia_root = site_packages / "nvidia"
    if nvidia_root.exists():
        for dll_dir in nvidia_root.glob("*/bin"):
            os.add_dll_directory(str(dll_dir))
            os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")

    # CTranslate2 and ONNX Runtime use the Microsoft C++ runtime. Load the
    # copies bundled with the active Python distribution where available.
    runtime_dirs = [Path(sys.prefix), Path(sys.base_prefix), Path(sys.base_prefix) / "DLLs"]
    for runtime_dir in runtime_dirs:
        if runtime_dir.is_dir():
            os.add_dll_directory(str(runtime_dir))
            for dll in (*runtime_dir.glob("msvcp140*.dll"), *runtime_dir.glob("vcruntime140*.dll")):
                try:
                    ctypes.WinDLL(str(dll))
                except OSError:
                    pass


def download_if_missing(path: Path, url: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {path.name} ...", flush=True)
    temporary_path = path.with_suffix(path.suffix + ".part")
    try:
        urllib.request.urlretrieve(url, temporary_path)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def gpu_memory_mib() -> str:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return "nvidia-smi unavailable"
    try:
        return subprocess.check_output(
            [nvidia_smi, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        return "unavailable"


def record_microphone(seconds: float) -> Path:
    """Record a short local WAV clip for the real microphone recognition test."""
    try:
        import pyaudio
    except ImportError as error:
        raise RuntimeError("PyAudio is missing; run the setup script again.") from error

    sample_rate = 16_000
    chunk_size = 1_024
    audio = pyaudio.PyAudio()
    stream = None
    try:
        print(f"Default microphone: {audio.get_default_input_device_info()['name']}")
        for count in (3, 2, 1):
            print(f"Recording starts in {count}...", flush=True)
            time.sleep(1)
        print(f"Speak a short sentence now ({seconds:g} seconds).", flush=True)
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=sample_rate,
            input=True,
            frames_per_buffer=chunk_size,
        )
        frames = []
        started = time.perf_counter()
        for _ in range(round(sample_rate / chunk_size * seconds)):
            frames.append(stream.read(chunk_size, exception_on_overflow=False))
        recorded_seconds = time.perf_counter() - started
        stream.stop_stream()
        stream.close()
        stream = None
        target = MODEL_DIR / "microphone_test.wav"
        with wave.open(str(target), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(audio.get_sample_size(pyaudio.paInt16))
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b"".join(frames))
        print(f"Recorded {seconds:g}s in {recorded_seconds:.2f}s; saved {target}")
        return target
    finally:
        if stream is not None:
            stream.stop_stream()
            stream.close()
        audio.terminate()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--audio", type=Path, help="Optional WAV/audio file to transcribe")
    parser.add_argument("--mic", action="store_true", help="Record a short clip from the default microphone")
    parser.add_argument("--record-seconds", type=float, default=5.0, help="Microphone recording length (default: 5)")
    parser.add_argument("--repeats", type=int, default=3, help="Measured inference repetitions after warm-up (default: 3)")
    parser.add_argument("--tts-precision", choices=KOKORO_MODELS, default="fp32", help="Kokoro model precision (default: fp32; best tested CUDA latency)")
    parser.add_argument("--no-playback", action="store_true", help="Do not play the generated Kokoro sample")
    parser.add_argument("--prepare-only", action="store_true", help="Download the selected Kokoro files without running inference")
    args = parser.parse_args()

    if args.audio and not args.audio.is_file():
        parser.error(f"Audio file does not exist: {args.audio}")
    if args.audio and args.mic:
        parser.error("Use either --audio or --mic, not both")
    if args.record_seconds <= 0:
        parser.error("--record-seconds must be greater than zero")
    if args.repeats < 1:
        parser.error("--repeats must be at least one")

    configure_windows_cuda_dlls()

    try:
        import onnxruntime as ort
        from faster_whisper import WhisperModel
        from kokoro_onnx import Kokoro
    except ImportError as error:
        print(f"Missing voice GPU dependencies: {error}", file=sys.stderr)
        print("Install them with: .\\scripts\\setup_and_check_voice_gpu.ps1", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"Could not load a CUDA runtime DLL: {error}", file=sys.stderr)
        print("Run .\\scripts\\setup_and_check_voice_gpu.ps1 to install the project CUDA runtimes.", file=sys.stderr)
        return 2

    ort.set_default_logger_severity(3)
    print(f"Python: {sys.executable}")
    print(f"Platform: {platform.platform()}")
    print(f"ONNX Runtime providers: {', '.join(ort.get_available_providers())}")

    if args.device == "cuda" and "CUDAExecutionProvider" not in ort.get_available_providers():
        print(
            "CUDA provider is unavailable. Run scripts/setup_and_check_voice_gpu.ps1 first; "
            "it installs the CUDA-enabled ONNX Runtime into the project venv.",
            file=sys.stderr,
        )
        return 3
    os.environ["ONNX_PROVIDER"] = "CUDAExecutionProvider" if args.device == "cuda" else "CPUExecutionProvider"

    kokoro_model, kokoro_url = KOKORO_MODELS[args.tts_precision]
    download_if_missing(kokoro_model, kokoro_url)
    download_if_missing(KOKORO_VOICES, f"{KOKORO_RELEASE}/voices-v1.0.bin")
    if args.prepare_only:
        print("Preparing multilingual Whisper tiny model...", flush=True)
        WhisperModel(
            "tiny", device=args.device,
            compute_type="int8_float16" if args.device == "cuda" else "int8",
            download_root=str(MODEL_DIR / "faster-whisper"), cpu_threads=2, num_workers=1,
        )
        print(f"Prepared Kokoro {args.tts_precision} and multilingual Whisper tiny in {MODEL_DIR}")
        return 0

    try:
        start = time.perf_counter()
        tts = Kokoro(str(kokoro_model), str(KOKORO_VOICES))
        kokoro_load = time.perf_counter() - start
        print(f"Kokoro {args.tts_precision} loaded in {kokoro_load:.2f}s; session providers: {', '.join(tts.sess.get_providers())}")

        start = time.perf_counter()
        whisper = WhisperModel(
            "tiny",
            device=args.device,
            compute_type="int8_float16" if args.device == "cuda" else "int8",
            download_root=str(MODEL_DIR / "faster-whisper"),
            cpu_threads=2,
            num_workers=1,
        )
        whisper_load = time.perf_counter() - start
        print(f"Whisper multilingual tiny loaded in {whisper_load:.2f}s")
        print("Models are loaded. Warm-up and latency measurements start now; model loading is excluded.", flush=True)

        phrase = "Haha, you missed me!"
        print("Warming up Kokoro text-to-speech ...", flush=True)
        warm_audio, sample_rate = tts.create(phrase, "af_heart", speed=1.0)
        sample = MODEL_DIR / "kokoro_gpu_sample.wav"
        import soundfile as sf

        sf.write(sample, warm_audio, sample_rate)
        tts_durations = []
        for run in range(1, args.repeats + 1):
            started = time.perf_counter()
            audio, sample_rate = tts.create(phrase, "af_heart", speed=1.0)
            tts_durations.append(time.perf_counter() - started)
        tts_median = sorted(tts_durations)[len(tts_durations) // 2]
        speech_seconds = len(audio) / sample_rate
        print(f"TTS warm-up generated {speech_seconds:.2f}s of speech (not timed).")
        print("TTS measured runs: " + ", ".join(f"{duration * 1000:.0f} ms" for duration in tts_durations))
        print(f"TTS median: {tts_median * 1000:.0f} ms; real-time factor: {tts_median / speech_seconds:.2f}x")

        if args.mic:
            transcription_audio = record_microphone(args.record_seconds)
        elif args.audio:
            transcription_audio = args.audio.resolve()
            print(f"Transcribing provided recording: {transcription_audio}")
        else:
            transcription_audio = sample
            print("Transcribing the generated speech sample (synthetic audio).")

        print("Warming up Whisper speech-to-text ...", flush=True)

        def transcribe_clip():
            segments, info = whisper.transcribe(
                str(transcription_audio),
                language="en",
                beam_size=1,
                vad_filter=False,
            )
            return "".join(segment.text for segment in segments).strip(), info.duration

        warm_text, clip_seconds = transcribe_clip()
        stt_durations = []
        transcript = warm_text
        for _ in range(args.repeats):
            started = time.perf_counter()
            transcript, clip_seconds = transcribe_clip()
            stt_durations.append(time.perf_counter() - started)
        stt_median = sorted(stt_durations)[len(stt_durations) // 2]
        print("STT measured runs: " + ", ".join(f"{duration * 1000:.0f} ms" for duration in stt_durations))
        print(f"STT median: {stt_median * 1000:.0f} ms for {clip_seconds:.2f}s audio; real-time factor: {stt_median / clip_seconds:.2f}x")
        if args.mic:
            print(f"Mic stop-to-caption latency: about {stt_median * 1000:.0f} ms (recording took {args.record_seconds:.1f}s).")
        print(f"Recognized text: {transcript or '[no speech recognized]'}")
        if not args.no_playback and not args.mic and not args.audio and sys.platform == "win32":
            try:
                import winsound

                print(f"Playing Kokoro sample: {sample}", flush=True)
                winsound.PlaySound(str(sample), winsound.SND_FILENAME)
            except (OSError, RuntimeError) as error:
                print(f"Could not play audio automatically: {error}")
                print(f"Sample saved at: {sample}")
        elif args.mic or args.audio:
            print(f"Audio input saved/used: {transcription_audio}")
        print(f"Model load time (excluded from latency): Kokoro {kokoro_load:.2f}s; Whisper {whisper_load:.2f}s")
        print(f"GPU memory while models are resident: {gpu_memory_mib()} MiB (nvidia-smi total, when available)")
        print(f"GPU memory after inference: {gpu_memory_mib()} MiB (nvidia-smi total, when available)")
        print("CUDA/provider result:", "PASS" if args.device == "cuda" else "CPU run complete")
        return 0
    except Exception as error:  # show common CUDA/driver/model setup failures cleanly
        print(f"Voice model check failed: {type(error).__name__}: {error}", file=sys.stderr)
        if args.device == "cuda":
            print(
                "Run .\\scripts\\setup_and_check_voice_gpu.ps1 --device cpu to isolate a CUDA setup issue.",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
