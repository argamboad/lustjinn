"""Where the client keeps its own things: a per-user config file and the token, never the repo.

The config is TOML in the user's config directory (``%LOCALAPPDATA%\\lustjinn`` on Windows,
``~/.config/lustjinn`` elsewhere), written with its defaults the first time the client runs, so
the reader has a file to edit. The token lives beside it in ``token``, a file only the user can
read: the OS keyring was the alternative, and it would have meant a native backend per platform
for a secret the API will hand out again on the next sign-in. The server can also be given on
the command line (``--server``) or in ``LUSTJINN_SERVER``, which beats the file.

.NET readers: ``appsettings.json`` + ``IOptions<T>`` with a user-secrets store, minus the layering
machinery — one file, one reader, explicit overrides.
"""

from __future__ import annotations

import os
import stat
import sys
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from platformdirs import user_config_dir

APP_NAME: Final = "lustjinn"
DEFAULT_SERVER: Final = "http://127.0.0.1:8000"
SERVER_VARIABLE: Final = "LUSTJINN_SERVER"


def config_dir() -> Path:
    return Path(user_config_dir(APP_NAME, appauthor=False))


@dataclass(frozen=True, slots=True)
class Config:
    server: str = DEFAULT_SERVER
    keyboard: str = "standard"  # or "vim" (#53)
    transcript_width_percent: int = 60  # clamped to 30-100 when used
    mouse: bool = False
    export_directory: str = "exports"  # relative paths resolve against the config directory
    proxy: str = "system"  # or "none": connect directly, whatever HTTPS_PROXY says

    @property
    def badge(self) -> str:
        """The word in the masthead's badge: ``Local`` for a loopback server, else its host."""
        host = urlsplit(self.server).hostname or ""
        if host in {"127.0.0.1", "localhost", "::1"}:
            return "Local"
        return host

    def export_path(self) -> Path:
        path = Path(self.export_directory).expanduser()
        return path if path.is_absolute() else config_dir() / path


TEMPLATE: Final = """\
# Lustjinn's terminal client. Edit and restart; the token is kept next to this file.

# The API to talk to. `--server` on the command line or LUSTJINN_SERVER in the environment wins.
server = "{server}"

# "standard" or "vim" (h j k l, G, n/N, u — only while navigating; text fields always type).
keyboard = "{keyboard}"

# How much of the width the transcript takes on a wide screen, 30-100.
transcript_width_percent = {transcript_width_percent}

# Clicks, scrolling and the button row on a narrow screen.
mouse = {mouse}

# Where exports are written; a relative path is under this file's directory.
export_directory = "{export_directory}"

# "system" goes the way the machine's proxy settings say (HTTPS_PROXY); "none" connects straight
# to the server. Either way the server's certificate must come from a public authority, so a
# proxy that decrypts HTTPS is refused rather than trusted.
proxy = "{proxy}"
"""


def write_default(path: Path) -> None:
    """A commented config with the defaults, for the reader to edit. Never overwrites."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    defaults = Config()
    path.write_text(
        TEMPLATE.format(
            server=defaults.server,
            keyboard=defaults.keyboard,
            transcript_width_percent=defaults.transcript_width_percent,
            mouse="true" if defaults.mouse else "false",
            export_directory=defaults.export_directory,
            proxy=defaults.proxy,
        ),
        encoding="utf-8",
    )


def load(path: Path, *, server: str | None = None, environ: dict[str, str] | None = None) -> Config:
    """The file's values over the defaults, then the environment, then the command line."""
    config = Config()
    if path.exists():
        read = tomllib.loads(path.read_text(encoding="utf-8"))
        config = Config(
            server=str(read.get("server", config.server)),
            keyboard=str(read.get("keyboard", config.keyboard)).lower(),
            transcript_width_percent=int(
                read.get("transcript_width_percent", config.transcript_width_percent)
            ),
            mouse=bool(read.get("mouse", config.mouse)),
            export_directory=str(read.get("export_directory", config.export_directory)),
            proxy="none" if str(read.get("proxy", config.proxy)).lower() == "none" else "system",
        )
    env = os.environ if environ is None else environ
    if env.get(SERVER_VARIABLE):
        config = replace(config, server=env[SERVER_VARIABLE])
    if server:
        config = replace(config, server=server)
    return replace(config, server=config.server.rstrip("/"))


class TokenStore:
    """The bearer token on disk, readable by this user alone."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> str | None:
        try:
            token = self.path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        return token or None

    def write(self, token: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(token, encoding="utf-8")
        if sys.platform != "win32":  # the user's config directory is already theirs on Windows
            self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def forget(self) -> None:
        self.path.unlink(missing_ok=True)
