"""Compare GPU voice settings in isolated processes, using this Python environment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--section", choices=("stt", "tts", "all"), default="all")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--audio", type=Path, action="append")
    parser.add_argument("--cooldown-seconds", type=float, default=15,
                        help="Idle between cases; still inspect saved clock/power telemetry")
    args = parser.parse_args()
    target = ROOT / "save" / "voice-benchmarks" / f"sweep-{time.time_ns()}"
    target.mkdir(parents=True)
    cases = []
    if args.section in ("tts", "all"):
        for precision, search in [("fp32", "exhaustive"), ("fp32", "heuristic"),
                                  ("fp32", "default"), ("fp16", "default"), ("int8", "default")]:
            cases.append((f"tts-{precision}-{search}", [
                "--mode", "tts", "--tts-precision", precision, "--conv-search", search,
                "--text", "Hold the line! Stay with me!",
                "--text", "Haha, you missed me!",
            ]))
    if args.section in ("stt", "all"):
        for model in ("base", "small"):
            for compute in ("float16", "float32", "int8_float16", "int8_float32"):
                command = ["--mode", "stt", "--stt-model", model, "--compute-type", compute,
                           "--language", "en", "--local-files-only"]
                for path in args.audio or []:
                    command.extend(["--audio", str(path.resolve())])
                cases.append((f"stt-{model}-{compute}", command))
    manifest = []
    for case_index, (label, flags) in enumerate(cases):
        if case_index and args.cooldown_seconds > 0:
            print(f"Cooling down for {args.cooldown_seconds:g}s ...", flush=True)
            time.sleep(args.cooldown_seconds)
        output = target / label
        output.mkdir()
        command = [sys.executable, str(ROOT / "scripts/benchmark_voice_gpu.py"),
                   "--repeats", str(args.repeats), "--output", str(output), *flags]
        print(f"Running {label} ...", flush=True)
        with (output / "console.log").open("w", encoding="utf-8") as log:
            try:
                process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                status = process.wait(timeout=180)
            except subprocess.TimeoutExpired:
                # Windows venv python.exe is a redirector: kill its owned child tree too.
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    process.kill()
                process.wait()
                status = "timeout (180s)"
        entry = {"label": label, "status": status, "command": command}
        reports = list(output.glob("result-*.json"))
        if reports:
            report = json.loads(reports[-1].read_text(encoding="utf-8"))
            entry.update({"report": str(reports[-1]), "gpu_memory": report["gpu_memory"],
                          "results": report["results"], "error": report.get("error")})
        manifest.append(entry)
        (target / "summary.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        times = [{kind: value.get("median_ms", value.get("full_audio", {}).get("median_ms"))
                  for kind, value in row.items()} for row in entry.get("results", [])]
        print(f"{label}: status={status}, medians_ms={times}, "
              f"peak_MiB={entry.get('gpu_memory', {}).get('sampled_peak_mib')}", flush=True)
    print(f"Sweep summary: {target / 'summary.json'}", flush=True)
    return int(any(entry["status"] != 0 for entry in manifest))


if __name__ == "__main__":
    raise SystemExit(main())
