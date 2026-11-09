"""Record or replay one team command and show STT plus the game's local action."""

from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from iron_and_snow.npc_behavior import decide_team_order


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, help="Replay a recorded WAV instead of using the microphone")
    parser.add_argument("--phrase-seconds", type=float, default=5.0,
                        help="Maximum live phrase length in seconds (default: 5)")
    args = parser.parse_args()

    try:
        import speech_recognition as sr
    except ImportError as exc:
        print("SpeechRecognition is missing. Run: uv sync", file=sys.stderr)
        raise SystemExit(2) from exc

    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = True
    recognizer.pause_threshold = .65
    recognizer.non_speaking_duration = .35
    recognizer.phrase_threshold = .2

    try:
        if args.audio:
            with sr.AudioFile(str(args.audio)) as source:
                audio = recognizer.record(source)
            duration = len(audio.frame_data) / (audio.sample_rate * audio.sample_width)
            print(f"Using WAV: {args.audio} ({duration:.2f}s)")
        else:
            print("Speak one short order after the microphone opens; pause to send it.")
            with sr.Microphone(chunk_size=1024) as source:
                recognizer.adjust_for_ambient_noise(source, duration=.35)
                started = time.perf_counter()
                audio = recognizer.listen(source, timeout=6, phrase_time_limit=args.phrase_seconds)
            duration = time.perf_counter() - started
            print(f"Captured phrase in {duration:.2f}s")

        started = time.perf_counter()
        transcript = recognizer.recognize_google(audio).strip()
        stt_seconds = time.perf_counter() - started
    except Exception as exc:
        print(f"Voice test failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    action = decide_team_order(transcript, {"health": 100}, "")
    print(f"Recognized: {transcript}")
    print(f"Google STT request: {stt_seconds * 1000:.0f} ms")
    print(f"Game action: {action}")
    print("Expected examples: ‘cover me’, ‘focus Ramsay’, ‘attack their archers’, ‘flank left’, ‘retreat’.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
