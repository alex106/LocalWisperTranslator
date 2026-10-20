"""Linux entry point. The Windows app in src/ stays unchanged.

Hold the hotkey to record, release to transcribe, then paste into the
window that already has focus. The overlay never takes focus.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

LINUX = Path(__file__).resolve().parent
ROOT = LINUX.parent
SRC = ROOT / "src"
# linux/ must win over src/ so hotkey, output, and overlay are the Linux ones.
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(LINUX))


def _reexec_with_input_group() -> None:
    """Reading the keyboard needs the input group.

    A GNOME login can keep the group list from the first time this user
    service started. Logging out does not refresh it when that service is
    still running. sg starts this same program with the group applied.
    """
    if os.environ.get("WISPER_INPUT_GROUP") == "1":
        return
    try:
        import grp
        info = grp.getgrnam("input")
    except KeyError:
        return
    if info.gr_gid in os.getgroups():
        os.environ["WISPER_INPUT_GROUP"] = "1"
        return
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    if user not in info.gr_mem or not shutil.which("sg"):
        return
    os.environ["WISPER_INPUT_GROUP"] = "1"
    os.execvp("sg", ["sg", "input", "-c", shlex.join([sys.executable, *sys.argv])])


_reexec_with_input_group()

from log_setup import configure_log

LOG_PATH = ROOT / "wisper-linux.log"
log = configure_log(LOG_PATH)

import app_info
from app_info import (
    about_lines, about_note, check_main_branch, describe_update, show_about,
    updates_menu_label,
)
from settings import LinuxConfig, open_linux_config, prepare_cuda_libraries

_cfg = LinuxConfig.load()
if _cfg.device == "cuda":
    prepare_cuda_libraries()

import pystray
from PIL import Image, ImageDraw


def _patch_tray_icon_suffix():
    """GNOME only loads a tray image whose path ends in .png.

    pystray writes a temporary file with no suffix, so the menu item is
    registered and invisible.
    """
    import os
    import tempfile
    from pystray._util import gtk as gtk_backend

    def _update_fs_icon(self):
        fd, path = tempfile.mkstemp(prefix="wisper-", suffix=".png")
        os.close(fd)
        self._icon_path = path
        with open(path, "wb") as handle:
            self.icon.save(handle, "PNG")
        self._icon_valid = True

    gtk_backend.GtkIcon._update_fs_icon = _update_fs_icon


def _patch_update_menu_color():
    """Paint the update item orange when main has commits this copy lacks.

    GNOME draws the tray menu from these GTK labels. A plain MenuItem has
    no color argument, so the label markup carries the color.
    """
    from gi.repository import GLib
    from pystray._util import gtk as gtk_backend

    original = gtk_backend.GtkIcon._create_menu_item

    def _create_menu_item(self, descriptor):
        item = original(self, descriptor)
        text = getattr(descriptor, "text", "") or ""
        if app_info.menu_update_alert and text.startswith("Check for updates"):
            label = item.get_children()[0]
            safe = GLib.markup_escape_text(text)
            label.set_markup(f'<span foreground="{app_info.UPDATE_ORANGE}">{safe}</span>')
        return item

    gtk_backend.GtkIcon._create_menu_item = _create_menu_item


_patch_tray_icon_suffix()
_patch_update_menu_color()

from audio import Recorder
from transcriber import Transcriber
from output import Output
from hotkey import PushToTalk
from overlay import WaveformOverlay
from translator import Translator
from languages import LANGUAGES, TRANSLATE_TARGETS

STATE_COLORS = {
    "loading": (120, 120, 120),
    "idle": (80, 160, 90),
    "recording": (210, 60, 60),
    "transcribing": (230, 170, 40),
}
UPDATE_COLOR = (214, 96, 20)

MODELS = ["large-v3", "medium", "small"]

_BEEP_NAMES = {
    880: "bell",
    560: "complete",
}


def _beep(freq: int, dur: int):  # noqa: ARG001 - duration is unused; the theme sound has its own length
    """Non-blocking beep. Never stall the evdev thread."""
    sound = _BEEP_NAMES.get(freq, "bell")

    def _play():
        try:
            subprocess.run(
                ["canberra-gtk-play", "-i", sound],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
            )
        except Exception:
            pass

    threading.Thread(target=_play, daemon=True).start()


def _make_icon(color) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 56, 56), fill=color)
    d.rounded_rectangle((27, 18, 37, 40), radius=5, fill=(255, 255, 255, 230))
    d.line((32, 40, 32, 48), fill=(255, 255, 255, 230), width=3)
    d.line((24, 48, 40, 48), fill=(255, 255, 255, 230), width=3)
    return img


class App:
    def __init__(self):
        self.cfg = _cfg
        self.state = "loading"
        self.recorder = Recorder(device=self.cfg.mic_device)
        self.output = Output(self.cfg)
        self.icon = pystray.Icon("wisper", _make_icon(STATE_COLORS["loading"]),
                                 "Wisper - loading model...")
        self.transcriber: Transcriber | None = None
        self.ptt: PushToTalk | None = None
        self.update_status: app_info.UpdateStatus | None = None
        self._busy = threading.Lock()
        self.overlay = WaveformOverlay(self.recorder)
        nllb_dir = self.cfg.translator_dir or (ROOT / "models" / "nllb-200-600m")
        self.translator = Translator(nllb_dir)

    def _set_state(self, state: str, tip: str | None = None):
        self.state = state
        color = STATE_COLORS.get(state, STATE_COLORS["idle"])
        if state == "idle" and self.update_status and self.update_status.update_available:
            color = UPDATE_COLOR
        self.icon.icon = _make_icon(color)
        self.icon.title = tip or f"Wisper - {state}"
        self.icon.update_menu()

    def on_press(self):
        if self.state != "idle":
            return
        self._set_state("recording", "Wisper - recording...")
        self.recorder.start()
        log.info("recording started")
        if self.cfg.show_overlay:
            self.overlay.show()
        if self.cfg.beep_on_record:
            _beep(880, 90)

    def on_release(self):
        if self.state != "recording":
            return
        audio = self.recorder.stop()
        log.info("recording stopped: %.2fs of audio", audio.size / 16000.0)
        if self.cfg.show_overlay:
            self.overlay.processing()
        if self.cfg.beep_on_record:
            _beep(560, 90)
        self._set_state("transcribing", "Wisper - transcribing...")
        threading.Thread(target=self._process, args=(audio,), daemon=True).start()

    def _process(self, audio):
        with self._busy:
            try:
                text, lang = self.transcriber.transcribe(audio)
                log.info("transcribed %d chars (lang=%s): %r",
                         len(text), lang, text[:120])
                if text and self.cfg.translate:
                    if self.cfg.show_overlay:
                        self.overlay.set_stage("translating")
                    translated = self.translator.translate(
                        text, lang, self.cfg.translate_to)
                    log.info("translated %s->%s: %r", lang,
                             self.cfg.translate_to, translated[:120])
                    text = translated
                if text:
                    self.output.deliver(text)
                    log.info("text delivered")
            except Exception as exc:
                log.exception("transcription failed")
                self.icon.notify(f"Transcription error: {exc}", "Wisper")
            finally:
                if self.cfg.show_overlay:
                    self.overlay.hide()
                self._set_state("idle", self._idle_tip())

    def _idle_tip(self) -> str:
        tr = f" -> {self.cfg.translate_to}" if self.cfg.translate else ""
        tip = f"Wisper - ready ({self.cfg.hotkey} | {self.cfg.language}{tr})"
        if self.update_status and self.update_status.update_available:
            tip += " | update available"
        return tip

    def _set_language(self, code):
        def handler(icon, item):  # noqa: ARG001
            self.cfg.set("language", code)
            self._set_state("idle", self._idle_tip())
        return handler

    def _lang_checked(self, code):
        return lambda item: self.cfg.language == code  # noqa: ARG005

    def _set_model(self, name):
        def handler(icon, item):  # noqa: ARG001
            if self.cfg.model == name:
                return
            self.cfg.set("model", name)
            self.cfg.set("model_dir", str(ROOT / "models" / name))
            self._set_state("loading", f"Wisper - loading {name}...")
            threading.Thread(target=self._reload_model, daemon=True).start()
        return handler

    def _model_checked(self, name):
        return lambda item: self.cfg.model == name  # noqa: ARG005

    def _set_translate(self, enabled, code=None):
        def handler(icon, item):  # noqa: ARG001
            self.cfg.set("translate", enabled)
            if code:
                self.cfg.set("translate_to", code)
            self._set_state(self.state, self._idle_tip()
                            if self.state == "idle" else None)
        return handler

    def _translate_checked(self, enabled, code=None):
        def checked(item):  # noqa: ARG001
            if not enabled:
                return not self.cfg.translate
            return self.cfg.translate and self.cfg.translate_to == code
        return checked

    def _reload_model(self):
        with self._busy:
            try:
                self.transcriber.cfg = self.cfg
                self.transcriber.load()
            except Exception as exc:
                self.icon.notify(f"Model load failed: {exc}", "Wisper")
            finally:
                self._set_state("idle", self._idle_tip())

    def _check_app_updates(self, icon, item):  # noqa: ARG002
        threading.Thread(target=self._watch_updates, args=(True,), daemon=True).start()

    def _watch_updates(self, notify: bool):
        if notify:
            self.icon.notify("Checking main for updates...", "Wisper")
        try:
            status = check_main_branch(ROOT)
            summary = describe_update(status)
        except Exception as exc:
            log.exception("app update check failed")
            status = None
            summary = f"Update check failed: {exc}"
        log.info("app update check: %s", summary.replace("\n", " | "))
        if status is not None:
            self.update_status = status
            app_info.menu_update_alert = status.update_available
        if self.state == "idle":
            self._set_state("idle", self._idle_tip())
        else:
            self.icon.update_menu()
        if notify:
            self.icon.notify(summary[:250], "Wisper")

    def _show_about(self, icon, item):  # noqa: ARG002
        text = about_lines(self.cfg)
        note = about_note(self.update_status)
        alert = bool(self.update_status and self.update_status.update_available)
        self.overlay.call(lambda: show_about(self.overlay.root, text, note, alert))

    def _check_updates(self, icon, item):  # noqa: ARG002
        threading.Thread(target=self._run_update_check, daemon=True).start()

    def _run_update_check(self):
        self.icon.notify("Checking Hugging Face for model updates...", "Wisper")
        script = ROOT / "scripts" / "update_models.py"
        env = {k: v for k, v in os.environ.items()
               if k not in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")}
        try:
            proc = subprocess.run(
                [sys.executable, str(script)], capture_output=True, text=True,
                timeout=3600, env=env,
            )
            out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
            log.info("update check:\n%s", out)
            lines = [ln for ln in out.splitlines() if ln.strip()]
            summary = "\n".join(lines[-4:]) or "no output"
            if "updated" in out:
                summary += "\nRestart Wisper to load the new models."
            self.icon.notify(summary[:250], "Wisper - model update check")
        except Exception as exc:
            log.exception("update check failed")
            self.icon.notify(f"Update check failed: {exc}", "Wisper")

    def _build_menu(self):
        lang_items = [
            pystray.MenuItem(label, self._set_language(code),
                             checked=self._lang_checked(code), radio=True)
            for label, code in LANGUAGES
        ]
        model_items = [
            pystray.MenuItem(name, self._set_model(name),
                             checked=self._model_checked(name), radio=True)
            for name in MODELS
        ]
        translate_items = [
            pystray.MenuItem("Off", self._set_translate(False),
                             checked=self._translate_checked(False), radio=True),
        ] + [
            pystray.MenuItem(label, self._set_translate(True, code),
                             checked=self._translate_checked(True, code),
                             radio=True)
            for label, code in TRANSLATE_TARGETS
        ]
        return pystray.Menu(
            pystray.MenuItem(lambda item: f"Hotkey: {self.cfg.hotkey}", None,
                             enabled=False),
            pystray.MenuItem("Language", pystray.Menu(*lang_items)),
            pystray.MenuItem("Translation", pystray.Menu(*translate_items)),
            pystray.MenuItem("Model", pystray.Menu(*model_items)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: updates_menu_label(self.update_status),
                             self._check_app_updates),
            pystray.MenuItem("Check for model updates...", self._check_updates),
            pystray.MenuItem("About", self._show_about),
            pystray.MenuItem("Edit config file...",
                             lambda icon, item: open_linux_config()),
            pystray.MenuItem("Reset", self._restart),
            pystray.MenuItem("Quit", self._quit),
        )

    def _restart(self, icon, item):
        """Start a new Wisper process, then leave so the tray and hotkey reload."""
        log.info("restart requested")
        if self.ptt:
            self.ptt.stop()
        _spawn_replacement()
        self._quit(icon, item)

    def _quit(self, icon, item):  # noqa: ARG002
        if self.ptt:
            self.ptt.stop()
        self.icon.stop()
        self.overlay.quit()

    def _startup(self):
        log.info("loading model %s (%s/%s)", self.cfg.model_dir or self.cfg.model,
                 self.cfg.device, self.cfg.compute_type)
        try:
            self.transcriber = Transcriber(self.cfg)
        except Exception as exc:
            log.exception("model load failed")
            self.icon.notify(f"Failed to load model: {exc}", "Wisper")
            self._set_state("loading", "Wisper - model load failed")
            return
        if self.cfg.translate and self.translator.available:
            try:
                self.translator._ensure_loaded()
            except Exception:
                log.exception("NLLB preload failed (non-fatal)")
        self.ptt = PushToTalk(self.cfg.hotkey, self.on_press, self.on_release)
        if not self.ptt.start():
            log.error("hotkey listener did not start")
            self.icon.notify(
                "Cannot read the keyboard. The input group is not active in this process.",
                "Wisper",
            )
            self._set_state("idle", "Wisper - keyboard not readable")
            return
        log.info("ready: hotkey=%s language=%s", self.cfg.hotkey, self.cfg.language)
        self._set_state("idle", self._idle_tip())

    def _pump_tray(self):
        """Run pending GTK events so the tray icon is actually registered.

        pystray on Linux only queues the icon update. The waveform window owns
        the main thread, so this timer has to drain the GTK queue or GNOME
        never shows the menu.
        """
        try:
            from gi.repository import GLib
            ctx = GLib.MainContext.default()
            for _ in range(20):
                if not ctx.pending():
                    break
                ctx.iteration(False)
        except Exception:
            log.exception("tray event loop stopped")
            return
        self.overlay.root.after(50, self._pump_tray)

    def run(self):
        self.icon.menu = self._build_menu()
        threading.Thread(target=self._startup, daemon=True).start()
        threading.Thread(target=self._watch_updates, args=(False,), daemon=True).start()
        self.icon.run_detached()
        self.overlay.root.after(50, self._pump_tray)
        self.overlay.run()
        self.icon.stop()


def _ensure_ydotoold() -> None:
    """Start ydotoold when this OS ships it as its own program.

    Ubuntu 22.04's ydotool 0.1.8 has no ydotoold binary. That client opens
    /dev/uinput itself, which works once this process is in the input group.
    """
    if not shutil.which("ydotoold"):
        log.info("ydotool client will open /dev/uinput directly")
        return
    socket = "/tmp/.ydotool_socket"
    if os.path.exists(socket):
        return
    log.info("starting ydotoold")
    subprocess.Popen(
        ["ydotoold"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(30):
        if os.path.exists(socket):
            log.info("ydotoold socket ready")
            return
        time.sleep(0.1)
    log.error("ydotoold did not create %s", socket)


def _spawn_replacement() -> None:
    """Relaunch this program after a short pause.

    The pause lets this process drop the tray icon and the keyboard
    devices before the new one claims them.
    """
    helper = (
        "import os, sys, time\n"
        "time.sleep(0.6)\n"
        "os.execv(sys.argv[1], sys.argv[1:])\n"
    )
    log.info("spawning replacement")
    subprocess.Popen(
        [sys.executable, "-c", helper, sys.executable, *sys.argv],
        cwd=str(ROOT),
        start_new_session=True,
    )


def main():
    _ensure_ydotoold()
    App().run()


if __name__ == "__main__":
    main()
