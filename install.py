#!/usr/bin/env python3
"""Install Wisper for whichever OS this script is running on.

Windows: create .venv and pip install -r requirements.txt.
Linux: system packages, input-group access for hold-to-talk, a venv,
models, a desktop entry, and the ydotoold user service.

    python install.py                 # Linux also downloads models
    python install.py --skip-models   # Linux: skip the weight download
    python install.py --with-models   # Windows: also download weights
"""
from __future__ import annotations

import argparse
import grp
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

LINUX_PACKAGES = [
    "python3-venv",
    "python3-dev",
    "python3-gi",
    "python3-tk",
    "python3-evdev",
    "gir1.2-gtk-3.0",
    "gir1.2-ayatanaappindicator3-0.1",
    "libportaudio2",
    "wl-clipboard",
    "ydotool",
    "libcanberra-gtk3-0",
]

UINPUT_RULE = (
    'KERNEL=="uinput", GROUP="input", MODE="0660", '
    'OPTIONS+="static_node=uinput"\n'
)


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.check_call(cmd)


def sudo(cmd: list[str]) -> None:
    run(["sudo", *cmd])


def sudo_write(path: str, text: str) -> None:
    print(f"+ write {path}", flush=True)
    subprocess.run(["sudo", "tee", path], input=text, text=True, check=True,
                   stdout=subprocess.DEVNULL)


def venv_python(venv: Path) -> Path:
    if sys.platform.startswith("win"):
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def install_windows(args: argparse.Namespace) -> None:
    venv = ROOT / ".venv"
    if not venv.exists():
        run([sys.executable, "-m", "venv", str(venv)])
    py = venv_python(venv)
    run([str(py), "-m", "pip", "install", "-U", "pip"])
    run([str(py), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
    if args.with_models:
        run([str(py), str(ROOT / "scripts" / "download_model.py")])
        run([str(py), str(ROOT / "scripts" / "download_nllb.py")])
    print()
    print("Windows install finished. Start Wisper with:")
    print(f"  {py} {ROOT / 'src' / 'app.py'}")
    if not args.with_models:
        print("Models were not downloaded. Re-run with --with-models, or run")
        print("  scripts\\download_model.py and scripts\\download_nllb.py")


def _ydotoold_unit() -> tuple[str, str]:
    """Return (unit file text, socket path the client should use).

    ydotool 0.1.8 ignores arguments and always binds /tmp/.ydotool_socket.
    1.x accepts --socket-path. Probing `ydotoold --help` is unsafe on 0.1.8:
    that binary ignores --help and starts the daemon.
    """
    binary = shutil.which("ydotoold") or "/usr/bin/ydotoold"
    version = ""
    if shutil.which("dpkg-query"):
        try:
            version = subprocess.check_output(
                ["dpkg-query", "-W", "-f", "${Version}", "ydotool"],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
        except (subprocess.CalledProcessError, OSError):
            version = ""
    major = version.split(":", 1)[-1].split(".", 1)[0] if version else "0"
    v1 = major.isdigit() and int(major) >= 1
    if v1:
        runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        socket = str(Path(runtime) / ".ydotool_socket")
        exec_start = (
            f"{binary} --socket-path={socket} --socket-perm=0600"
        )
        extra = f"Environment=YDOTOOL_SOCKET={socket}\n"
    else:
        socket = "/tmp/.ydotool_socket"
        exec_start = binary
        extra = ""
    unit = (
        "[Unit]\n"
        "Description=ydotool virtual keyboard for Wisper\n"
        "\n"
        "[Service]\n"
        f"ExecStart={exec_start}\n"
        f"{extra}"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )
    return unit, socket


def _desktop_entry(py: Path, socket: str) -> str:
    # Do not resolve(): the venv interpreter is a symlink, and following it
    # would launch the system Python without the venv's packages.
    py = py if py.is_absolute() else py.absolute()
    app = ROOT / "linux" / "app.py"
    env_parts = [f"YDOTOOL_SOCKET={socket}"]
    site = py.parent.parent / "lib"
    lib_dirs = [str(p) for p in site.glob("python*/site-packages/nvidia/*/lib") if p.is_dir()] if site.is_dir() else []
    if lib_dirs:
        env_parts.insert(0, "LD_LIBRARY_PATH=" + os.pathsep.join(lib_dirs))
    prefix = "/usr/bin/env " + " ".join(env_parts) + " "
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Wisper\n"
        "Comment=Offline push-to-talk dictation\n"
        f"Exec={prefix}\"{py}\" \"{app}\"\n"
        f"Path={ROOT}\n"
        "Icon=audio-input-microphone\n"
        "Terminal=false\n"
        "Categories=Utility;Audio;\n"
        "StartupNotify=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def _in_input_group() -> bool:
    try:
        gid = grp.getgrnam("input").gr_gid
    except KeyError:
        return False
    return gid in os.getgroups()


def install_linux(args: argparse.Namespace) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        sys.exit("Run install.py as your user. It calls sudo for apt and udev itself.")

    sys.path.insert(0, str(ROOT / "linux"))
    from settings import nvidia_present, write_fresh_config, CONFIG_LINUX_PATH

    sudo(["apt-get", "update"])
    sudo(["apt-get", "install", "-y", *LINUX_PACKAGES])

    user = os.environ.get("USER") or os.environ.get("LOGNAME")
    if not user:
        sys.exit("Could not determine the user name for usermod.")
    sudo(["usermod", "-aG", "input", user])
    sudo_write("/etc/udev/rules.d/99-wisper-uinput.rules", UINPUT_RULE)
    sudo_write("/etc/modules-load.d/uinput.conf", "uinput\n")
    sudo(["modprobe", "uinput"])
    sudo(["udevadm", "control", "--reload-rules"])
    sudo(["udevadm", "trigger", "--name-match=uinput"])

    venv = ROOT / ".venv"
    if not (venv / "bin" / "python").exists():
        py3 = shutil.which("python3") or sys.executable
        run([py3, "-m", "venv", "--system-site-packages", str(venv)])
    py = venv_python(venv)
    run([str(py), "-m", "pip", "install", "-U", "pip"])
    run([str(py), "-m", "pip", "install", "-r", str(ROOT / "linux" / "requirements.txt")])
    cuda = nvidia_present()
    if cuda:
        run([str(py), "-m", "pip", "install", "nvidia-cublas-cu12", "nvidia-cudnn-cu12"])

    if not args.skip_models:
        model = "large-v3" if cuda else "small"
        run([str(py), str(ROOT / "scripts" / "download_model.py"), model])
        run([str(py), str(ROOT / "scripts" / "download_nllb.py")])

    if CONFIG_LINUX_PATH.exists():
        print(f"Keeping existing {CONFIG_LINUX_PATH}")
    else:
        write_fresh_config()
        print(f"Wrote {CONFIG_LINUX_PATH}")

    unit_text, socket = _ydotoold_unit()
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / "wisper-ydotoold.service"
    unit_path.write_text(unit_text, encoding="utf-8")
    try:
        run(["systemctl", "--user", "daemon-reload"])
        # enable only. --now would crash-loop: this login is not in the
        # input group yet, so ydotoold cannot open /dev/uinput until the
        # next session.
        run(["systemctl", "--user", "enable", "wisper-ydotoold.service"])
    except subprocess.CalledProcessError:
        print("Could not start the ydotoold user service in this session.")
        print(f"After you log in again it will start from {unit_path}")

    desktop = _desktop_entry(py, socket)
    app_dir = Path.home() / ".local" / "share" / "applications"
    auto_dir = Path.home() / ".config" / "autostart"
    app_dir.mkdir(parents=True, exist_ok=True)
    auto_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "wisper.desktop").write_text(desktop, encoding="utf-8")
    (auto_dir / "wisper.desktop").write_text(desktop, encoding="utf-8")

    print()
    print("Linux install finished.")
    print(f"  App menu:    {app_dir / 'wisper.desktop'}")
    print(f"  Autostart:   {auto_dir / 'wisper.desktop'}")
    print(f"  Config:      {CONFIG_LINUX_PATH}")
    print(f"  Run now:     {py} {ROOT / 'linux' / 'app.py'}")
    if args.skip_models:
        print("Models were skipped. Dictation will fail until you download them.")
    print()
    print("Log out and back in before holding the hotkey.")
    print("Hold-to-talk reads /dev/input, and membership of the input group")
    print("applies only in a new login. That group can read every keystroke")
    print("on this machine, which is what a global hold-key needs.")
    if _in_input_group():
        print("This session already has the input group; a new login is still")
        print("required if udev just changed /dev/uinput.")
    else:
        print("This session is not in the input group yet.")


def main():
    parser = argparse.ArgumentParser(description="Install Wisper for this OS.")
    parser.add_argument("--with-models", action="store_true",
                        help="Windows: also download Whisper and NLLB weights")
    parser.add_argument("--skip-models", action="store_true",
                        help="Linux: do not download model weights")
    args = parser.parse_args()
    if sys.platform.startswith("win"):
        install_windows(args)
    elif sys.platform.startswith("linux"):
        install_linux(args)
    else:
        sys.exit(f"Unsupported OS: {sys.platform}")


if __name__ == "__main__":
    main()
