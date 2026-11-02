"""Desktop integration: the side-panel extension, the running-session file, the Dock app.

- The Chrome extension ships in `web/extension/`; at startup it is copied to `data/` with a
  `config.js` that points it at this server, then loaded into the controlled Chrome.
- `data/ui-session.json` (mode 600) records the running server's port and token, so a second
  launch (e.g. clicking the Dock icon again) brings the window back instead of starting twice.
- `install_app` writes `~/Applications/Job Radar.app`, a launcher that starts `job-radar ui`
  in the background and exits.
- `install_schedule` registers a LaunchAgent that runs `job-radar fetch` every day; launchd
  runs a missed run when the Mac wakes up.
"""

from __future__ import annotations

import json
import logging
import os
import plistlib
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "Job Radar"
BUNDLE_ID = "local.job-radar.launcher"
LAUNCHER = "job-radar-launcher"
FETCH_AGENT = "local.job-radar.fetch"


def prepare_extension(data_dir: Path, origin: str) -> Path:
    """Copy the side-panel extension next to the data and point it at `origin`."""
    target = data_dir / "browser-extension"
    target.mkdir(parents=True, exist_ok=True)
    source = resources.files("job_radar.web") / "extension"
    for item in source.iterdir():
        if item.is_file():
            (target / item.name).write_bytes(item.read_bytes())
    (target / "config.js").write_text(
        f"// 由 job-radar ui 啟動時產生\nconst JR_ORIGIN = {json.dumps(origin)};\n",
        encoding="utf-8",
    )
    return target


# --- running session ----------------------------------------------------------


@dataclass
class Session:
    port: int
    token: str
    pid: int


def session_path(data_dir: Path) -> Path:
    return data_dir / "ui-session.json"


def write_session(data_dir: Path, session: Session) -> None:
    path = session_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(session.__dict__, fh)
    path.chmod(0o600)


def read_session(data_dir: Path) -> Session | None:
    try:
        return Session(**json.loads(session_path(data_dir).read_text("utf-8")))
    except (OSError, ValueError, TypeError):
        return None


def remove_session(data_dir: Path, token: str) -> None:
    """Remove the file only if it still belongs to this server."""
    current = read_session(data_dir)
    if current and current.token == token:
        session_path(data_dir).unlink(missing_ok=True)


# --- Dock app -------------------------------------------------------------------


def launcher_script(root: Path, uv: Path) -> str:
    log_file = root / "data" / "logs" / "ui.log"
    return (
        "#!/bin/zsh\n"
        "# Job Radar 啟動器：在背景啟動申請助手；已在執行時把視窗叫回前面。\n"
        f"ROOT={shlex.quote(str(root))}\n"
        f"UV={shlex.quote(str(uv))}\n"
        f"LOG={shlex.quote(str(log_file))}\n"
        'mkdir -p "${LOG:h}"\n'
        'cd "$ROOT" || exit 1\n'
        'nohup "$UV" run job-radar ui >> "$LOG" 2>&1 &\n'
        "disown\n"
    )


def install_app(root: Path, uv: Path, applications: Path) -> Path:
    """Create (or replace) `<applications>/Job Radar.app`."""
    app = applications / f"{APP_NAME}.app"
    if app.exists():
        shutil.rmtree(app)
    macos = app / "Contents" / "MacOS"
    res = app / "Contents" / "Resources"
    macos.mkdir(parents=True)
    res.mkdir(parents=True)
    info = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": LAUNCHER,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "12.0",
    }
    if _make_icns(res / "AppIcon.icns"):
        info["CFBundleIconFile"] = "AppIcon"
    with (app / "Contents" / "Info.plist").open("wb") as fh:
        plistlib.dump(info, fh)
    script = macos / LAUNCHER
    script.write_text(launcher_script(root, uv), encoding="utf-8")
    script.chmod(0o755)
    return app


def _make_icns(out: Path) -> bool:
    """PNG → .icns with the macOS tools sips and iconutil; False when unavailable."""
    if not (shutil.which("sips") and shutil.which("iconutil")):
        return False
    png = resources.files("job_radar.web") / "assets" / "icon-1024.png"
    with tempfile.TemporaryDirectory() as tmp, resources.as_file(png) as src:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        try:
            for size in (16, 32, 128, 256, 512):
                for scale in (1, 2):
                    px = size * scale
                    name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                    subprocess.run(
                        ["sips", "-z", str(px), str(px), str(src), "--out", str(iconset / name)],
                        check=True,
                        capture_output=True,
                    )
            subprocess.run(
                ["iconutil", "-c", "icns", str(iconset), "-o", str(out)],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            log.warning("無法產生 App 圖示：%s", exc.stderr.decode(errors="replace").strip())
            return False
    return True


def add_to_dock(app: Path) -> bool:
    """Append the app to the Dock; False if it is already there."""
    url = app.resolve().as_uri() + "/"
    current = subprocess.run(
        ["defaults", "read", "com.apple.dock", "persistent-apps"],
        capture_output=True,
        text=True,
    ).stdout
    if url in current or str(app.resolve()) in current:
        return False
    tile = (
        "<dict><key>tile-data</key><dict><key>file-data</key><dict>"
        f"<key>_CFURLString</key><string>{url}</string>"
        "<key>_CFURLStringType</key><integer>15</integer>"
        "</dict></dict></dict>"
    )
    subprocess.run(
        ["defaults", "write", "com.apple.dock", "persistent-apps", "-array-add", tile],
        check=True,
    )
    subprocess.run(["killall", "Dock"], check=False)
    return True


# --- daily fetch ----------------------------------------------------------------


def fetch_agent_plist(root: Path, uv: Path, hour: int, minute: int) -> dict:
    log_file = str(root / "data" / "logs" / "fetch.log")
    return {
        "Label": FETCH_AGENT,
        "ProgramArguments": [str(uv), "run", "job-radar", "fetch", "--if-stale"],
        "WorkingDirectory": str(root),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        # launchd skips a run missed while the Mac was off; logging in makes it up.
        "RunAtLoad": True,
        "StandardOutPath": log_file,
        "StandardErrorPath": log_file,
    }


def install_schedule(root: Path, uv: Path, hour: int, minute: int, agents_dir: Path) -> Path:
    """Write the LaunchAgent and (re)load it with launchctl."""
    (root / "data" / "logs").mkdir(parents=True, exist_ok=True)
    agents_dir.mkdir(parents=True, exist_ok=True)
    plist = agents_dir / f"{FETCH_AGENT}.plist"
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(plist)], capture_output=True)
    with plist.open("wb") as fh:
        plistlib.dump(fetch_agent_plist(root, uv, hour, minute), fh)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True, capture_output=True)
    return plist


def scheduled_time(agents_dir: Path) -> tuple[int, int] | None:
    """(hour, minute) of the installed daily fetch, None if there is none."""
    plist = agents_dir / f"{FETCH_AGENT}.plist"
    try:
        slot = plistlib.loads(plist.read_bytes())["StartCalendarInterval"]
        return int(slot["Hour"]), int(slot.get("Minute", 0))
    except (OSError, KeyError, ValueError, TypeError, plistlib.InvalidFileException):
        return None


def remove_schedule(agents_dir: Path) -> bool:
    plist = agents_dir / f"{FETCH_AGENT}.plist"
    if not plist.exists():
        return False
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist)], capture_output=True)
    plist.unlink()
    return True
