# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Wisper is a fully-offline push-to-talk dictation tray app for Windows: hold a global
hotkey → mic audio → Whisper large-v3 (GPU) → optional NLLB translation (CPU) → text
pasted at the cursor of the focused window. There is no build step, no test suite, and
no linter configured; verification is done by running the app and E2E scripts (below).

## Commands

```powershell
# Run (dev, with console output):
.\.venv\Scripts\python.exe src\app.py

# Run (production, no console — what the Startup shortcut uses):
.\.venv\Scripts\pythonw.exe src\app.py     # or Wisper.bat

# Stop a running instance: tray icon → Quit, or:
Get-Process python,pythonw | Where-Object { $_.Path -like '*Wisper*' } | Stop-Process -Force

# Dependencies (venv already exists at .venv, Python 3.13):
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# One-time model downloads (only online steps besides the update check):
.\.venv\Scripts\python.exe scripts\download_model.py   # Whisper -> models\large-v3
.\.venv\Scripts\python.exe scripts\download_nllb.py    # NLLB    -> models\nllb-200-600m

# Check for model updates (compares .revision files against HF):
.\.venv\Scripts\python.exe scripts\update_models.py
```

Runtime behavior is observed via `wisper.log` (project root): model load, each recording,
transcription text, translation, focus transitions, errors. When testing, poll the log
rather than stdout — the app prints nothing.

When printing Cyrillic/Hebrew in test scripts, set `PYTHONIOENCODING=utf-8` first
(Windows console default cp1252 raises UnicodeEncodeError; the app itself is unaffected).

## Hard constraints (violating these breaks the app)

- **4 GB VRAM GPU (RTX 3050 Ti).** Whisper must load with `compute_type=int8_float16`
  (~2 GB). `float16` needs ~4.7 GB and OOMs. The NLLB translator deliberately runs on
  **CPU int8** — do not move it to CUDA.
- **`import cuda_setup` must precede `from faster_whisper import ...`**
  (see src/transcriber.py). It registers the pip-installed NVIDIA DLL dirs
  (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`); without it CTranslate2 dies at inference
  with "cublas64_12.dll not found" (load succeeds, transcribe fails).
- **Offline is a feature.** src/app.py sets `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`,
  `HF_HUB_DISABLE_TELEMETRY=1` before HF imports. The only sanctioned online path is
  scripts/update_models.py (user-triggered from the tray), which strips those vars in a
  subprocess. Don't add network calls anywhere else.
- **Threading model:** the Tk overlay owns the **main thread** (`overlay.run()` blocks);
  pystray runs via `icon.run_detached()`; hotkey callbacks fire on the keyboard hook
  thread; transcription runs on a worker thread. Tk objects must only be touched on the
  main thread — other threads talk to the overlay through its command queue
  (`overlay.show()/hide()/quit()` are queue-backed and thread-safe). Never block the
  hook thread (e.g. beeps are async for this reason).

## Architecture / data flow

```
hotkey down (hotkey.py, chord state on global hook, debounced)
  -> recorder.start()  [audio.py: sounddevice 16kHz mono float32 — Whisper's native format,
                        no ffmpeg/resampling anywhere]
  -> overlay.show()    [overlay.py: waveform panel; saves GetForegroundWindow(), steals
                        focus with SetForegroundWindow + ALT-key trick so stray keys
                        don't reach the user's document]
hotkey up
  -> recorder.stop() -> np.float32 array
  -> overlay.hide()    [restores focus to the saved hwnd — must happen before paste]
  -> worker thread: transcriber.transcribe(audio) -> (text, detected_lang_iso)
  -> if cfg.translate: translator.translate(text, detected_lang, cfg.translate_to)
                       [NLLB lazy-loads on first use; FLORES-200 codes via languages.py]
  -> output.deliver()  [clipboard-paste strategy: save clipboard, copy, Ctrl+V, restore.
                        Chosen over keystroke simulation for Unicode (Cyrillic/RTL Hebrew)]
```

State machine in app.py: `loading → idle → recording → transcribing → idle`, reflected
in tray icon color (grey/green/red/amber).

## Editable-config split (three files, different owners)

- `config.json` — runtime settings, **written by the app** (tray menu selections persist
  here via `Config.set`). Merged over `DEFAULTS` in config.py; unknown keys are dropped.
- `languages.json` — human-edited menu content: `spoken` (Language menu),
  `translate_targets` (Translation menu), `flores_codes` (ISO→FLORES for NLLB).
  A translation target only works if its ISO code exists in `flores_codes`.
  Loaded once at import by languages.py; app restart required after edits.
- `models/*/.revision` — HF commit SHA baselines written by update_models.py.

## Testing pattern (no pytest — E2E by design)

Real-speech tests use Windows SAPI TTS to synthesize WAVs (voices: Microsoft Zira=EN,
David=EN, Irina=RU), load them as 16 kHz mono float32, and feed the actual Transcriber/
Translator classes. Paste-path tests use a tkinter window forced to the Win32 foreground
(same ALT trick). Hotkey-path tests inject the chord with the `keyboard` library and
assert on `wisper.log` lines. Historical scripts live in the session scratchpad, not the
repo — recreate as needed.

## Gotchas

- The `keyboard` lib may need the app elevated to paste into elevated windows.
- pystray menu `checked=`/dynamic-text callables are evaluated on `icon.update_menu()`;
  language/translation menu items mutate `cfg` and rely on that refresh.
- `Config.__getattr__` raises AttributeError for unknown keys — new settings must be
  added to `DEFAULTS` in config.py or they're silently stripped from config.json.
- Windows clipboard history (Win+V) / cloud clipboard sync can retain pasted transcripts;
  relevant to any privacy work on output.py.
