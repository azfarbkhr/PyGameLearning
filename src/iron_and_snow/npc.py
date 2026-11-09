"""Background Codex and voice services for Bolton NPC experimentation."""
from __future__ import annotations

import importlib.util
import asyncio
import ctypes
import difflib
import glob
import json
import math
import os
import queue
import re
import sys
import unicodedata
import threading
import time
from pathlib import Path


class CodexNPC:
    def __init__(self, root: Path, director=None):
        self.root = root
        self.director = director
        self.workdir = Path(__file__).resolve().parent
        self.source_profiles = self.workdir / "characters"
        self.profile_dir = self.source_profiles
        self.active_character = "ramsay_bolton"
        self.tactical_character = "ramsay_bolton"
        self.character_name = "Ramsay Bolton"
        self.profile_text = ""
        self.profile_mtime = 0.0
        self._sync_profiles()
        self._load_profile(self.active_character)
        self.result_queue: queue.Queue = queue.Queue()
        self.tactic_queue: queue.Queue = queue.Queue()
        self.speech_queue: queue.Queue = queue.Queue(maxsize=3)
        self.tts_jobs: queue.Queue = queue.Queue(maxsize=4)
        self.tts_worker_lock = threading.Lock()
        self.tts_worker_active = False
        self.tts_backend = os.getenv("IRON_SNOW_TTS_BACKEND", "kokoro").strip().lower()
        self.last_tts_backend_used = "kokoro" if self.tts_backend == "kokoro" else "edge"
        self.kokoro = None
        self.kokoro_ready = threading.Event()
        self.kokoro_error = ""
        self.kokoro_dll_handles = []
        self.stt_backend = os.getenv("IRON_SNOW_STT_BACKEND", "whisper").strip().lower()
        self.whisper = None
        self.whisper_ready = threading.Event()
        self.whisper_error = ""
        self.last_stt_backend_used = "google"
        self.speech_epoch = 0
        self.pending_calls = queue.Queue()
        self.pending_dialogue = None
        self.busy_lock = threading.Lock()
        self.busy = False
        self.ready = director is not None
        self.last_latency = None
        self.last_stt_latency = None
        self.last_tts_latency = None
        self.last_stt_error = ""
        self.last_tts_error = ""
        self.last_error = ""
        self.recent_ai_lines = []
        self.scripted_line_index = {}
        self.max_dialogue_seconds = 4.25
        self.max_voice_dialogue_seconds = 18.0
        self.max_council_dialogue_seconds = 25.0
        self.latest_dialogue_request_id = None
        self.last_prompt_character = {"allies": None, "enemies": None}
        self.active_codex_side = None
        self.listening = False
        self.speech_state = "idle"
        self.listen_stop = threading.Event()
        self.audio_thread = None
        self.policy_path = self.workdir / "npc_behavior.py"
        self.policy_mtime = 0.0
        self.policy = None
        self.load_policy()
        self.offline = os.getenv("IRON_SNOW_OFFLINE") == "1"
        if self.offline:
            self.kokoro_ready.set()
            self.whisper_ready.set()
            self.last_error = "Offline verification; live Codex and audio disabled"
            self.ready = True
            return
        if self.tts_backend == "kokoro":
            print("[voice] Requested local Kokoro CUDA backend; preloading in the background.", flush=True)
            threading.Thread(target=self._load_kokoro, daemon=True).start()
        else:
            self.kokoro_ready.set()
            print("[voice] Using Edge TTS backend.", flush=True)
            if self.stt_backend == "whisper":
                threading.Thread(target=self._load_whisper, daemon=True).start()
        if self.tts_backend == "kokoro" and self.stt_backend != "whisper":
            self.whisper_ready.set()
        # Codex lives in the two faction sessions owned by BattleDirector.
        # This service only handles speech, transcripts, profiles, and local fallbacks.
        self.ready = director is not None

    @property
    def tts_status(self):
        if self.tts_backend != "kokoro":
            return "EDGE TTS"
        if not self.kokoro_ready.is_set():
            return "KOKORO LOADING"
        if self.kokoro is None or self.last_tts_backend_used == "edge":
            return "EDGE FALLBACK"
        return "KOKORO GPU"

    def warm(self, chapter, state):
        # Open the persistent session during the story card, but keep battle
        # barks local so the first live conversation never waits behind a warm-up.
        self.current_chapter = chapter
        self.latest_state = dict(state)

    def _sync_profiles(self):
        self.source_profiles.mkdir(parents=True, exist_ok=True)

    def _start_pending_work(self):
        with self.busy_lock:
            pending = self.pending_dialogue
            self.pending_dialogue = None
        if pending:
            self._run_pending_dialogue(pending)
            return
        try:
            prompt, task, context, character_slug = self.pending_calls.get_nowait()
        except queue.Empty:
            return
        self._run_async(prompt, task=task, context=context, character_slug=character_slug)

    def _run_pending_dialogue(self, pending):
        prompt, task, context, character_slug, request_id, effort, response_ttl = pending
        if request_id is not None and request_id != self.latest_dialogue_request_id:
            return
        self._run_async(prompt, task=task, context=context, character_slug=character_slug,
                        request_id=request_id, effort=effort, response_ttl=response_ttl)

    def select_character(self, slug):
        if not re.fullmatch(r"[a-z0-9_]+", slug):
            raise ValueError("Character profile names must be lowercase slugs.")
        if not (self.profile_dir / f"{slug}.md").is_file():
            raise FileNotFoundError(f"Unknown character profile: {slug}")
        self._load_profile(slug)

    def _load_profile(self, slug):
        profile = self.profile_dir / f"{slug}.md"
        self.active_character = slug
        self.character_name = " ".join(part.capitalize() for part in slug.split("_"))
        self.profile_text = profile.read_text(encoding="utf-8") if profile.exists() else "A determined northern fighter."
        self.profile_mtime = profile.stat().st_mtime if profile.exists() else 0

    def _profile_for(self, slug):
        profile = self.profile_dir / f"{slug}.md"
        try:
            text = profile.read_text(encoding="utf-8")
        except OSError:
            text = "A determined northern fighter."
        if slug == self.active_character:
            self.profile_text = text
            try:
                self.profile_mtime = profile.stat().st_mtime
            except OSError:
                pass
        return text

    def scripted_line(self, character_slug, event, default=""):
        """Pick an immediate, authored line from a character's Markdown profile."""
        profile = self._profile_for(character_slug)
        section = profile.split("## Battle dialogue", 1)
        if len(section) < 2:
            return default
        lines = section[1].split("\n## ", 1)[0].splitlines()
        pool = []
        for line in lines:
            match = re.match(r"\s*-\s*([a-z0-9_]+):\s*(.+?)\s*$", line, re.IGNORECASE)
            if match and match.group(1).lower() == event.lower():
                pool = [text.strip() for text in match.group(2).split("|") if text.strip()]
                break
        if not pool:
            return default
        key = (character_slug, event)
        index = self.scripted_line_index.get(key, 0)
        self.scripted_line_index[key] = index + 1
        return pool[index % len(pool)]

    def scripted_reply(self, character_slug, player_line):
        """Fast conversational fallback, keyed by meaning and rotated to avoid repeats."""
        text = player_line.lower()
        if character_slug == "ramsay_bolton":
            if "rickon" in text or "brother" in text:
                event = "reply_rickon"
            elif any(word in text for word in ("why", "reason", "afraid", "fear")):
                event = "reply_question"
            elif any(word in text for word in ("surrender", "yield", "give up")):
                event = "reply_surrender"
            elif any(word in text for word in ("attack", "fight", "come", "kill")):
                event = "reply_challenge"
            else:
                event = "reply_default"
        elif character_slug in {"sansa_stark", "tormund_giantsbane"}:
            if any(word in text for word in ("archer", "arrow", "bow", "ranged")):
                event = "plan_archers"
            elif any(word in text for word in ("flank", "left", "right", "side", "surround")):
                event = "plan_flank"
            elif any(word in text for word in ("cover", "protect", "defend", "hold", "retreat", "safe")):
                event = "plan_defense"
            else:
                event = "plan_default"
        else:
            event = "reply_default"
        defaults = {
            "sansa_stark": "Use cover, hold the reserve, and make the Boltons move first.",
            "tormund_giantsbane": "Keep their eyes on the center. I'll take the open side.",
        }
        return self.scripted_line(character_slug, event,
                                  defaults.get(character_slug, "The North will answer you on the battlefield."))

    def _run_async(self, prompt, *, task="dialogue", context=None, character_slug=None, request_id=None,
                   effort="low", response_ttl=None):
        character_slug = character_slug or (self.tactical_character if task == "tactic" else self.active_character)
        if not self.ready:
            if not self.last_error and task == "tactic":
                self.pending_calls.put((prompt, task, context, character_slug))
            elif not self.last_error and task == "dialogue":
                with self.busy_lock:
                    self.pending_dialogue = (prompt, task, context, character_slug, request_id, effort, response_ttl)
            return
        if self.offline or self.director is None:
            if task == "dialogue":
                name = " ".join(part.capitalize() for part in character_slug.split("_"))
                self.result_queue.put({"speaker": name.upper(), "character": character_slug,
                                       "text": self._fallback_line(task, character_slug), "request_id": request_id,
                                       "source": "fallback"})
            return
        with self.busy_lock:
            if self.busy:
                if task == "tactic":
                    self.pending_calls.put((prompt, task, context, character_slug))
                elif task == "dialogue":
                    # Keep only the latest live exchange; the local voiced
                    # response already covers any older utterance.
                    self.pending_dialogue = (prompt, task, context, character_slug, request_id, effort, response_ttl)
                return
            self.busy = True
        started = time.perf_counter()
        def worker():
            try:
                profile_text = self._profile_for(character_slug)
                character_name = " ".join(p.capitalize() for p in character_slug.split("_"))
                # Keep only the character card's useful personality/behavior
                # sections. Scripted bark banks are handled locally in MD.
                profile_card = profile_text.split("## Battle dialogue", 1)[0].strip()
                side = "enemies" if character_slug == "ramsay_bolton" else "allies"
                self.active_codex_side = side
                if self.last_prompt_character[side] != character_slug:
                    character_context = f"ACTIVE CHARACTER CARD ({character_slug}.md):\n{profile_card}\n"
                else:
                    character_context = f"ACTIVE CHARACTER: {character_name}. Continue the established persona.\n"
                payload = (f"TASK: {task}\n{character_context}"
                           f"CURRENT GAME STATE: {json.dumps(context or {}, separators=(',', ':'), ensure_ascii=False)}\n"
                           f"NEW EVENT: {prompt}")
                if task == "dialogue" and request_id != self.latest_dialogue_request_id:
                    return
                result = self.director.run_turn(side, payload, request_id=request_id, effort=effort)
                self.last_prompt_character[side] = character_slug
                text = (result.final_response or "").strip().replace("’", "'").replace("‘", "'")
                proposed_orders = []
                if (context or {}).get("phase") == "pre_battle_council":
                    text, proposed_orders = self.parse_council_reply(text)
                text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
                self.last_latency = time.perf_counter() - started
                if task == "tactic":
                    tactic = next((v for v in ("press", "withdraw", "call_archers", "feint") if v in text.lower()), "press")
                    self.tactic_queue.put(tactic)
                    self._load_policy_if_changed()
                else:
                    normalized = re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()
                    repeated = any(difflib.SequenceMatcher(None, normalized, old).ratio() > .86 for old in self.recent_ai_lines[-5:])
                    is_current = request_id is None or request_id == self.latest_dialogue_request_id
                    if (self.last_latency <= (response_ttl or self.max_dialogue_seconds)
                            and normalized and not repeated and is_current):
                        self.recent_ai_lines.append(normalized)
                        self.result_queue.put({"speaker": character_name.upper(), "character": character_slug,
                                               "text": text[:220], "request_id": request_id,
                                               "source": "codex", "orders": proposed_orders})
            except Exception as exc:
                self.last_error = str(exc)
                print(f"[codex] {side} {task} failed: {exc}", flush=True)
                if task == "dialogue":
                    character_name = " ".join(p.capitalize() for p in character_slug.split("_"))
                    self.result_queue.put({"speaker": character_name.upper(), "character": character_slug,
                                           "text": self._fallback_line(task, character_slug), "request_id": request_id,
                                           "source": "fallback"})
            finally:
                next_call = None
                next_dialogue = None
                with self.busy_lock:
                    self.active_codex_side = None
                    self.busy = False
                    next_dialogue = self.pending_dialogue
                    self.pending_dialogue = None
                    if not next_dialogue:
                        try:
                            next_call = self.pending_calls.get_nowait()
                        except queue.Empty:
                            pass
                if next_dialogue:
                    self._run_pending_dialogue(next_dialogue)
                elif next_call:
                    self._run_async(next_call[0], task=next_call[1], context=next_call[2], character_slug=next_call[3])
        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def parse_council_reply(text):
        """Accept only known unit/action proposals from the adviser."""
        try:
            raw = text.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
            data = json.loads(raw)
        except (ValueError, TypeError):
            # A plain spoken reply is usable, but cannot change the plan.
            return text[:220], []
        if not isinstance(data, dict) or not isinstance(data.get("reply"), str):
            raise ValueError(f"Council response needs a spoken reply: {raw[:300]}")
        targets = {"sansa stark", "tormund", "wun wun", "archers", "northmen", "team"}
        actions = {"follow", "cover", "focus", "target_archers", "flank_left", "flank_right", "hold", "retreat"}
        orders = []
        for order in data.get("orders", []) if isinstance(data.get("orders"), list) else []:
            if (isinstance(order, dict) and isinstance(order.get("target"), str)
                    and isinstance(order.get("action"), str) and order["target"] in targets
                    and order["action"] in actions):
                accepted = {"target": order["target"], "action": order["action"]}
                point = order.get("point")
                if (isinstance(point, list) and len(point) == 2
                        and all(isinstance(v, (int, float)) and math.isfinite(v) for v in point)
                        and 32 <= point[0] <= 3268 and 640 <= point[1] <= 1062):
                    accepted["point"] = point
                orders.append(accepted)
        return data["reply"].strip()[:220], orders[:3]

    def dialogue_timeout(self, state, voice=False):
        if (state or {}).get("phase") == "pre_battle_council":
            return self.max_council_dialogue_seconds
        return self.max_voice_dialogue_seconds if voice else self.max_dialogue_seconds

    def send_player_line(self, line, state, *, voice=False, request_id=None):
        self.latest_dialogue_request_id = request_id
        if (state or {}).get("phase") == "pre_battle_council":
            prompt = (f"Planning council for {state.get('chapter', 'the battle')}. Jon Snow says: {line}. "
                      "Suggest a coordinated plan using the council JSON format, or ask a short clarifying question with empty orders. "
                      "Use only available_units when provided. Respect Jon's current assignments. Do not claim an order was issued.")
        elif (state or {}).get("channel") == "team":
            prompt = (f"Jon addresses your team: {line}. React naturally as the selected ally. "
                      "A separate commander session coordinates units; acknowledge the actual current orders "
                      "or ask one short useful question. Never impersonate Ramsay.")
        else:
            prompt = f"Jon Snow says: {line}"
        self._run_async(
            prompt,
            context=state, character_slug=self.active_character, request_id=request_id,
            effort="low",
            response_ttl=self.dialogue_timeout(state, voice),
        )

    def decide_team_order(self, line, state):
        """Apply a bounded squad action locally so an order never waits on AI."""
        allowed = {"follow", "cover", "focus", "target_archers", "flank_left", "flank_right", "hold", "retreat", "unrecognized"}
        action = "follow"
        try:
            self._load_policy_if_changed()
            spec = importlib.util.spec_from_file_location("shared_npc_runtime_policy", self.policy_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            decide = getattr(module, "decide_team_order", None)
            if callable(decide):
                action = decide(line, state, self._profile_for("jon_snow"))
        except Exception:
            lowered = line.lower()
            action = ("cover" if any(term in lowered for term in ("cover", "protect", "guard me", "help me"))
                      else "target_archers" if "archer" in lowered
                      else "focus" if any(term in lowered for term in ("attack", "focus", "target"))
                      else "unrecognized")
        if action not in allowed:
            action = "follow"
        return action, None

    def send_story_event(self, event):
        self._run_async(event, context={"chapter": "Winterfell", "event": event}, character_slug=self.tactical_character)

    def taunt(self, event, state):
        self._run_async(f"Battle event: {event}. Deliver a brief response in Ramsay Bolton's voice, at most 12 words.", context=state, character_slug=self.tactical_character)

    def request_tactic(self, state):
        # Safe baseline policy executes immediately while Codex reasons in parallel.
        tactic = self._decide(state)
        self.tactic_queue.put(tactic)
        self._run_async(
            f"Review {self.tactical_character}'s current state and battle profile. If a durable behavior change "
            "would improve future decisions, make a small change only to the shared npc_behavior.py, preserving "
            "decide(state, profile_text) and decide_team_order(command, state, profile_text). Then choose one "
            "current action. Return the action token first, followed by an optional one-sentence summary.",
            task="tactic", context=state,
        )

    def _request_script_update(self, prompt):
        self._run_async(prompt, task="tactic", context={"chapter": "startup"}, character_slug=self.tactical_character)

    def _decide(self, state):
        try:
            self._load_policy_if_changed()
            action = self.policy(state, self._profile_for(self.tactical_character)) if self.policy else "press"
            return action if action in {"press", "withdraw", "call_archers", "feint"} else "press"
        except Exception:
            return "press"

    def load_policy(self):
        try:
            spec = importlib.util.spec_from_file_location("shared_npc_runtime_policy", self.policy_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if (callable(getattr(module, "decide", None))
                    and callable(getattr(module, "decide_team_order", None))):
                self.policy = module.decide
                self.policy_mtime = self.policy_path.stat().st_mtime
        except Exception as exc:
            self.last_error = f"NPC policy kept previous version: {exc}"

    def _load_policy_if_changed(self):
        try:
            if self.policy_path.stat().st_mtime != self.policy_mtime:
                self.load_policy()
        except OSError:
            pass

    def _fallback_line(self, task, character_slug="ramsay_bolton"):
        if task != "dialogue":
            return "press"
        return {
            "ramsay_bolton": "You mistake survival for victory, Snow.",
            "sansa_stark": "We take Winterfell together, but we do it with a plan.",
            "tormund_giantsbane": "Right. Let's hit the Bolton bastards before they hit us.",
        }.get(character_slug, "The North stands together.")

    def speak(self, text, *, character_slug=None, request_id=None):
        if self.offline:
            return
        if not text:
            return
        # Start playing the first complete sentence while the next synthesizes.
        chunks = re.split(r"(?<=[.!?])\s+", text[:220].strip())
        chunks = chunks[:2] + ([" ".join(chunks[2:])] if len(chunks) > 2 else [])
        for chunk in chunks:
            job = (chunk, character_slug or self.active_character, request_id, self.speech_epoch)
            try:
                self.tts_jobs.put_nowait(job)
            except queue.Full:
                break
        with self.tts_worker_lock:
            if not self.tts_worker_active:
                self.tts_worker_active = True
                threading.Thread(target=self._tts_worker, daemon=True).start()

    def _load_kokoro(self):
        """Load and warm the local CUDA voice model away from the game loop."""
        try:
            if sys.platform == "win32":
                site_packages = Path(sys.prefix) / "Lib" / "site-packages"
                nvidia_root = site_packages / "nvidia"
                if nvidia_root.exists():
                    for dll_dir in nvidia_root.glob("*/bin"):
                        self.kokoro_dll_handles.append(os.add_dll_directory(str(dll_dir)))
                        os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")
                for runtime_dir in (Path(sys.prefix), Path(sys.base_prefix), Path(sys.base_prefix) / "DLLs"):
                    if runtime_dir.is_dir():
                        self.kokoro_dll_handles.append(os.add_dll_directory(str(runtime_dir)))
                        for dll in (*runtime_dir.glob("msvcp140*.dll"), *runtime_dir.glob("vcruntime140*.dll")):
                            try:
                                ctypes.WinDLL(str(dll))
                            except OSError:
                                pass

            os.environ["ONNX_PROVIDER"] = "CUDAExecutionProvider"
            import onnxruntime as ort
            from kokoro_onnx import Kokoro

            if "CUDAExecutionProvider" not in ort.get_available_providers():
                raise RuntimeError("ONNX Runtime has no CUDA provider")

            model_dir = self.root / "save" / "voice-gpu-check" / "models"
            model_path = model_dir / "kokoro-v1.0.onnx"
            voices_path = model_dir / "voices-v1.0.bin"
            if not model_path.is_file() or not voices_path.is_file():
                raise FileNotFoundError("Kokoro FP32 model files are missing; run scripts/run_game.ps1")

            self.kokoro = Kokoro(str(model_path), str(voices_path))
            self.kokoro.create("The North stands together.", "af_bella", speed=1.0)
            self.kokoro_error = ""
            active_providers = self.kokoro.sess.get_providers()
            if "CUDAExecutionProvider" not in active_providers:
                raise RuntimeError(f"Kokoro did not activate CUDA; providers: {active_providers}")
            print(f"[voice] Kokoro CUDA ready; model preloaded. Active providers: {active_providers}", flush=True)
        except Exception as exc:
            self.kokoro = None
            self.kokoro_error = f"Kokoro unavailable; using Edge TTS: {exc}"
            self.last_tts_error = self.kokoro_error
            print(f"[voice] {self.kokoro_error}", flush=True)
        finally:
            self.kokoro_ready.set()
            if self.stt_backend == "whisper":
                threading.Thread(target=self._load_whisper, daemon=True).start()

    def _load_whisper(self):
        """Preload multilingual Whisper for local English/Urdu voice commands."""
        try:
            if sys.platform == "win32":
                site_packages = Path(sys.prefix) / "Lib" / "site-packages"
                for dll_dir in (site_packages / "nvidia").glob("*/bin"):
                    self.kokoro_dll_handles.append(os.add_dll_directory(str(dll_dir)))
                    os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")
                for runtime_dir in (Path(sys.prefix), Path(sys.base_prefix), Path(sys.base_prefix) / "DLLs"):
                    if runtime_dir.is_dir():
                        self.kokoro_dll_handles.append(os.add_dll_directory(str(runtime_dir)))
            from faster_whisper import WhisperModel

            model_dir = self.root / "save" / "voice-gpu-check" / "models" / "faster-whisper"
            try:
                self.whisper = WhisperModel(
                    "tiny", device="cuda", compute_type="int8_float16",
                    download_root=str(model_dir), cpu_threads=2, num_workers=1,
                )
                self.last_stt_backend_used = "whisper-cuda"
            except Exception as cuda_error:
                print(f"[voice] Whisper CUDA unavailable ({cuda_error}); falling back to CPU.", flush=True)
                self.whisper = WhisperModel(
                    "tiny", device="cpu", compute_type="int8",
                    download_root=str(model_dir), cpu_threads=2, num_workers=1,
                )
                self.last_stt_backend_used = "whisper-cpu"
            self.whisper_error = ""
            print(f"[voice] Multilingual Whisper tiny ready ({self.last_stt_backend_used}).", flush=True)
        except Exception as exc:
            self.whisper = None
            self.whisper_error = str(exc)
            print(f"[voice] Local Whisper unavailable; using Google recognition: {exc}", flush=True)
        finally:
            self.whisper_ready.set()

    def _transcribe_local(self, recognizer, audio):
        """Convert captured PCM to a local multilingual Whisper transcript."""
        if not self.whisper_ready.wait(timeout=20) or self.whisper is None:
            raise RuntimeError(self.whisper_error or "Local Whisper is still loading")
        import numpy as np

        pcm = audio.get_raw_data(convert_rate=16000, convert_width=2)
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self.whisper.transcribe(
            samples, language=None, beam_size=1, vad_filter=True,
            condition_on_previous_text=False,
        )
        transcript = " ".join(segment.text.strip() for segment in segments).strip()
        return transcript

    def _kokoro_voice(self, profile_text):
        selected = re.search(r"(?im)^\s*Kokoro voice:\s*([a-z0-9_]+)\s*$", profile_text)
        if selected:
            return selected.group(1)
        gender = re.search(r"(?im)^\s*Voice gender:\s*(female|male)\s*$", profile_text)
        return "af_bella" if gender and gender.group(1).lower() == "female" else "am_michael"

    def _synthesize_kokoro(self, text, profile_text, path):
        if not self.kokoro_ready.wait(timeout=12):
            raise TimeoutError("Kokoro did not finish loading before the speech request")
        if self.kokoro is None:
            raise RuntimeError(self.kokoro_error or "Kokoro is unavailable")
        import soundfile as sf

        audio, sample_rate = self.kokoro.create(
            text,
            self._kokoro_voice(profile_text),
            speed=1.0,
        )
        sf.write(path, audio, sample_rate, subtype="PCM_16")

    def _tts_worker(self):
        while True:
            try:
                text, character_slug, request_id, epoch = self.tts_jobs.get(timeout=.25)
            except queue.Empty:
                with self.tts_worker_lock:
                    if self.tts_jobs.empty():
                        self.tts_worker_active = False
                        return
                continue
            started = time.perf_counter()
            path = None
            try:
                if epoch != self.speech_epoch:
                    continue
                profile_text = self._profile_for(character_slug)
                out_dir = self.root / "save" / "voice"
                out_dir.mkdir(parents=True, exist_ok=True)
                local_error = ""
                used_backend = "edge"
                if self.tts_backend == "kokoro":
                    path = out_dir / f"line-{time.time_ns()}.wav"
                    try:
                        self._synthesize_kokoro(text, profile_text, path)
                        used_backend = "kokoro"
                    except Exception as exc:
                        local_error = f"Kokoro TTS: {exc}; using Edge TTS"
                        print(f"[voice] {local_error}", flush=True)
                        path.unlink(missing_ok=True)
                        path = None
                if path is None:
                    import edge_tts

                    path = out_dir / f"line-{time.time_ns()}.mp3"

                    async def generate():
                        await edge_tts.Communicate(text, self._edge_voice(profile_text), rate="+14%", volume="-2%").save(str(path))

                    asyncio.run(generate())
                self.last_tts_latency = time.perf_counter() - started
                self.last_tts_backend_used = used_backend
                self.last_tts_error = local_error
                print(f"[voice] {used_backend} TTS generated in {self.last_tts_latency:.2f}s "
                      f"({len(text)} chars)", flush=True)
                if epoch == self.speech_epoch:
                    try:
                        self.speech_queue.put_nowait((str(path), request_id, epoch))
                    except queue.Full:
                        try:
                            stale_path, _, _ = self.speech_queue.get_nowait()
                            Path(stale_path).unlink(missing_ok=True)
                        except queue.Empty:
                            pass
                        self.speech_queue.put_nowait((str(path), request_id, epoch))
                else:
                    path.unlink(missing_ok=True)
            except Exception as exc:
                self.last_tts_error = f"Edge TTS: {exc}"
                self.last_error = self.last_tts_error
            finally:
                self.tts_jobs.task_done()

    def _edge_voice(self, profile_text=None):
        profile_text = profile_text if profile_text is not None else self.profile_text
        gender = re.search(r"(?im)^\s*Voice gender:\s*(female|male)\s*$", profile_text)
        voice = re.search(r"(?im)^\s*Edge TTS voice:\s*([A-Za-z0-9-]+)\s*$", profile_text)
        if voice:
            return voice.group(1)
        if gender and gender.group(1).lower() == "female":
            return "en-US-AvaNeural"
        return "en-US-ChristopherNeural"

    def poll_speech(self):
        try:
            return self.speech_queue.get_nowait()
        except queue.Empty:
            return None

    def cancel_dialogue(self):
        """Interrupt obsolete inference without blocking the Pygame thread."""
        request_id = self.latest_dialogue_request_id
        self.latest_dialogue_request_id = None
        with self.busy_lock:
            self.pending_dialogue = None
            side = self.active_codex_side or ("enemies" if self.active_character == "ramsay_bolton" else "allies")
        if self.director is not None and request_id is not None:
            self.director.cancel_dialogue(side, request_id)

    def cancel_speech(self):
        """Discard speech from a previous chapter and any audio not yet played."""
        self.speech_epoch += 1
        for pending in (self.tts_jobs, self.speech_queue):
            while True:
                try:
                    item = pending.get_nowait()
                    if pending is self.tts_jobs:
                        pending.task_done()
                    elif isinstance(item, tuple) and item and isinstance(item[0], str):
                        Path(item[0]).unlink(missing_ok=True)
                except queue.Empty:
                    break

    def poll(self):
        try:
            return self.result_queue.get_nowait()
        except queue.Empty:
            return None

    def poll_tactic(self):
        latest = None
        while True:
            try:
                latest = self.tactic_queue.get_nowait()
            except queue.Empty:
                return latest

    def start_listening(self, state=None, *, channel="enemy"):
        if self.offline:
            self.result_queue.put({"notice": "Microphone disabled during offline verification", "channel": channel})
            return False
        if self.listening:
            return True
        self.listening = True
        self.speech_state = "starting"
        self.last_stt_error = ""
        self.listen_stop.clear()
        def listen():
            capture_started = time.perf_counter()
            try:
                import speech_recognition as sr
                recognizer = sr.Recognizer()
                recognizer.dynamic_energy_threshold = True
                recognizer.pause_threshold = .9 if channel == "planning" else .65
                recognizer.non_speaking_duration = .35
                recognizer.phrase_threshold = .2
                with sr.Microphone(chunk_size=1024) as mic:
                    self.speech_state = "listening"
                    audio = recognizer.listen(mic, timeout=4, phrase_time_limit=12 if channel == "planning" else 5)
                self.speech_state = "transcribing"
                recognition_started = time.perf_counter()
                if self.stt_backend == "whisper":
                    try:
                        transcript = self._transcribe_local(recognizer, audio)
                    except Exception as local_error:
                        print(f"[voice] Local Whisper failed; using Google recognition: {local_error}", flush=True)
                        transcript = recognizer.recognize_google(audio)
                        self.last_stt_backend_used = "google-fallback"
                else:
                    transcript = recognizer.recognize_google(audio)
                    self.last_stt_backend_used = "google"
                self.last_stt_latency = time.perf_counter() - recognition_started
                total_latency = time.perf_counter() - capture_started
                if not transcript.strip():
                    self.last_stt_error = "No words recognized. Try a short, clear phrase."
                    self.result_queue.put({"notice": self.last_stt_error, "channel": channel,
                                           "total_latency": total_latency})
                    return
                self.last_stt_error = ""
                self.result_queue.put({"transcript": transcript.strip(), "channel": channel,
                                       "total_latency": total_latency})
            except Exception as exc:
                if type(exc).__name__ == "UnknownValueError":
                    self.last_stt_error = "Speech not recognized. Try a short, clear phrase."
                elif type(exc).__name__ == "WaitTimeoutError":
                    self.last_stt_error = "No speech heard. Press a talk key and try again."
                elif type(exc).__name__ == "RequestError":
                    self.last_stt_error = f"Speech service unavailable: {exc}"
                else:
                    self.last_stt_error = f"Microphone error: {exc}"
                self.last_error = self.last_stt_error
                self.result_queue.put({"notice": self.last_stt_error, "channel": channel,
                                       "total_latency": time.perf_counter() - capture_started})
            finally:
                self.listening = False
                self.speech_state = "idle"
        self.audio_thread = threading.Thread(target=listen, daemon=True)
        self.audio_thread.start()
        return True

    def end_listening(self):
        self.listening = False
        self.listen_stop.set()

    def close(self):
        self.cancel_dialogue()
        self.cancel_speech()
