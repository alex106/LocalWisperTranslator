# Wisper — Fully-Local Offline Dictation & Translation (Wispr-style)

A background system-tray app that turns speech into text **entirely offline**.
Hold a global hotkey, speak, release — and the transcription (optionally
translated to another language) is typed at your cursor in whatever app has
focus. Powered by [faster-whisper] (`large-v3`) on your GPU and
[NLLB-200] (CTranslate2) on the CPU.

- **Push-to-talk:** hold `Ctrl+Alt+Space` (configurable), release to transcribe.
- **Waveform overlay:** while recording, a panel with a live waveform appears at
  the bottom of the screen and takes keyboard focus (stray keystrokes can't reach
  your document); on release it disappears and focus returns to your window.
- **Auto-type at cursor:** works in any app (browser, editor, chat) via clipboard paste.
- **Multilingual:** English, Russian, auto-detect, and ~99 other Whisper languages.
- **Translation:** optional speech-to-translated-text into English, Russian,
  German, French, Spanish, Ukrainian (extendable) via a local NLLB-200 model.
- **Runs offline:** after one-time model downloads, no internet is used.

## Requirements

- Windows 11, Python 3.11–3.13 (verified on 3.13).
- NVIDIA GPU with a recent driver (verified: RTX 3050 Ti Laptop, 4 GB VRAM).
  CUDA/cuDNN libraries come from pip wheels — no CUDA Toolkit install needed
  (`src/cuda_setup.py` registers their DLL folders at startup).

> **4 GB VRAM note:** the default `compute_type` is `int8_float16`, which fits
> `large-v3` in ~2 GB. Plain `float16` would need ~4.7 GB and fail to load.
> The NLLB translator deliberately runs on **CPU int8** (~600 MB RAM) so it
> never competes with Whisper for VRAM.

> **CPU vs GPU:** set `device: "cpu"` if no CUDA GPU is available, but expect
> it to be noticeably slower — `large-v3` on CPU can run 5–15×+ slower than
> the GPU path above. If you need a CPU fallback, pair it with a smaller
> model (`small` or `base`) rather than `large-v3`: CPU int8 on those sizes
> gets close to realtime, at the cost of more transcription errors (more so
> on accented speech, background noise, or less common languages). Default
> to `cuda` whenever a GPU is available.

## Setup

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies (includes NVIDIA cuBLAS/cuDNN wheels, ~1.3 GB)
pip install -r requirements.txt

# 3. One-time model downloads for offline use
python scripts\download_model.py     # Whisper large-v3  -> .\models\large-v3   (~3 GB)
python scripts\download_nllb.py      # NLLB-200 600M     -> .\models\nllb-200-600m (~2.4 GB)
```

Then point `config.json` at the local weights (already done in this checkout):

```json
{
  "model_dir": "C:\\WorkFolder\\Wisper\\models\\large-v3",
  "local_files_only": true
}
```

After this the app never contacts the network — verify by disabling your
connection and dictating.

## Run

```powershell
python src\app.py        # or double-click Wisper.bat (no console window)
```

**Auto-start:** a shortcut in the Windows Startup folder
(`shell:startup` → `Wisper.lnk`) launches Wisper at every login via
`pythonw.exe`. Delete the shortcut (or disable it in Task Manager → Startup
apps) to turn auto-start off.

A microphone icon appears in the system tray:

| Icon color | Meaning |
|-----------|---------|
| grey  | loading model (~15 s after launch) |
| green | ready (idle) |
| red   | recording |
| amber | transcribing |

**Use it:** focus any text field, hold `Ctrl+Alt+Space`, speak (the waveform
panel appears and pulses with your voice), release — the text is pasted at
your cursor.

## Tray menu

Right-click the tray icon:

- **Language** — what you *speak*: Auto-detect / English / Russian / German /
  French / Spanish. Auto-detect is recommended when translation is on.
- **Translation** — what gets *pasted*: Off (paste as spoken) or a target
  language (English / Russian / German / French / Spanish / Ukrainian).
  Speech is transcribed, then translated locally by NLLB-200 before pasting.
  If you already spoke the target language, the text passes through unchanged.
- **Model** — large-v3 (best quality) / medium / small (faster, less VRAM).
- **Check for model updates…** — the app's **only** online action, and it runs
  only when you click it: compares your local model revisions against Hugging
  Face and re-downloads only if a newer revision exists (these models change
  rarely). Result appears as a notification; restart Wisper after an update.
  At all other times the app is locked offline (`HF_HUB_OFFLINE=1`).
- **Edit config file…** — opens `config.json`.
- **Quit** — stops the app.

## Configuration (`config.json`)

| Key | Default | Notes |
|-----|---------|-------|
| `hotkey` | `ctrl+alt+space` | Any `keyboard`-library combo, held for push-to-talk |
| `language` | `auto` | Spoken language: `auto`, `en`, `ru`, or any Whisper code |
| `model` | `large-v3` | `large-v3` / `medium` / `small` |
| `device` | `cuda` | `cuda` or `cpu` |
| `compute_type` | `int8_float16` | `int8`/`float16` on GPU (float16 needs >4 GB); `int8` on CPU |
| `model_dir` | `null` | Local Whisper weights dir for offline use |
| `local_files_only` | `false` | `true` = never download |
| `output_mode` | `paste` | `paste` (clipboard+Ctrl+V) or `type` (keystrokes) |
| `mic_device` | `null` | sounddevice input index; `null` = system default |
| `min_audio_seconds` | `0.3` | Ignore shorter recordings |
| `beep_on_record` | `true` | Start/stop beeps |
| `restore_clipboard` | `true` | Restore prior clipboard after paste |
| `show_overlay` | `true` | Waveform panel while recording |
| `translate` | `false` | Translate transcript before pasting |
| `translate_to` | `en` | Target language (ISO code, see below) |
| `translator_dir` | `null` | NLLB weights dir; `null` = `.\models\nllb-200-600m` |

**Adding languages — edit `languages.json`** (project root, created on first
run; restart the app afterwards):

- `spoken` — entries of the tray **Language** menu (what you speak).
- `translate_targets` — entries of the tray **Translation** menu.
- `flores_codes` — ISO→FLORES-200 codes for the NLLB translator; a translation
  target only works if its ISO code is listed here (e.g. `"ja": "jpn_Jpan"`).

Example — adding Italian as both a spoken language and a translation target:

```json
{
  "spoken":            [ ..., {"label": "Italian", "code": "it"} ],
  "translate_targets": [ ..., {"label": "Italian", "code": "it"} ],
  "flores_codes":      { ..., "it": "ita_Latn" }
}
```

## Project layout

```
Wisper/
  Wisper.bat               # console-less manual launcher
  config.json              # user settings (created/updated at runtime)
  languages.json           # editable menu languages + FLORES codes
  wisper.log               # runtime log (model load, recordings, errors)
  requirements.txt
  models/
    large-v3/              # Whisper CT2 weights (download_model.py)
    nllb-200-600m/         # NLLB CT2 weights (download_nllb.py)
  scripts/
    download_model.py      # one-time Whisper download
    download_nllb.py       # one-time NLLB download
  src/
    app.py                 # entrypoint: tray, state machine, pipeline
    overlay.py             # waveform panel + focus steal/restore
    audio.py               # mic capture (sounddevice, 16 kHz mono)
    transcriber.py         # faster-whisper wrapper (returns text + language)
    translator.py          # NLLB-200 translation (CPU int8)
    languages.py           # loads languages.json (creates defaults)
    output.py              # clipboard-paste delivery
    hotkey.py              # global push-to-talk hook
    config.py              # settings load/save
    cuda_setup.py          # registers pip-installed CUDA DLLs (import first)
```

## Notes & troubleshooting

- **Log file:** `wisper.log` records every model load, recording, transcription,
  translation, and error — check it first when something misbehaves.
- **Global hotkeys / typing into elevated apps:** the `keyboard` library may need
  the app to run **as Administrator** to send keystrokes into elevated windows.
- **Cyrillic/emoji:** use the default `paste` output mode — per-character typing
  can garble non-Latin text.
- **CUDA "cublas64_12.dll not found":** the NVIDIA pip wheels supply this DLL and
  `src/cuda_setup.py` registers it; make sure `transcriber.py` imports
  `cuda_setup` *before* `faster_whisper`, and that `nvidia-cublas-cu12` /
  `nvidia-cudnn-cu12` are installed.
- **CUDA out of memory:** ensure `compute_type` is `int8_float16` and no other
  process is using the GPU; or switch `model` to `medium`.
- **First syllable clipped:** recording starts before the beep plays, so this
  shouldn't happen — if it does, check `wisper.log` for delayed
  `recording started` timestamps.
- **Switching `model` in the tray does nothing if `model_dir` is pinned:**
  when `model_dir` is set (as in this checkout, to `models\large-v3`), that
  exact folder is always loaded regardless of which size you pick in the
  tray. To actually switch sizes, download the weights for that size first
  (`scripts\download_model.py medium`, etc.) and either clear `model_dir` in
  `config.json` (falls back to the Hugging Face cache) or repoint it at the
  new folder.

[faster-whisper]: https://github.com/SYSTRAN/faster-whisper
[NLLB-200]: https://huggingface.co/entai2965/nllb-200-distilled-600M-ctranslate2
