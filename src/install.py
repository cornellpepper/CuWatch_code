#!/usr/bin/env python3
"""Install project files onto a MicroPython board on Windows.

This script mirrors the behaviour of ``install.sh`` using pure Python so it can be
run on Windows without relying on external shell commands. It requires the
``mpremote`` package to be installed in the active Python environment.
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
import tarfile
import textwrap
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Optional

try:
    from mpremote.pyboard import Pyboard  # type: ignore[attr-defined]
except ImportError:
    try:
        from mpremote import pyboard as _pyboard  # type: ignore[attr-defined]
    except ImportError:
        try:
            from pyboard import Pyboard  # type: ignore[import-not-found]
        except ImportError:
            try:
                import serial  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - informative exit when dependency missing
                print(
                    "Neither mpremote nor pyboard is available. Install one of them with `pip install mpremote` or install pyserial for the built-in fallback.",
                    file=sys.stderr,
                )
                raise SystemExit(1) from exc

            class Pyboard:  # type: ignore[too-few-public-methods]
                """Minimal Pyboard client using raw REPL over pyserial."""

                def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0):
                    self.serial = serial.Serial(port, baudrate=baudrate, timeout=timeout)
                    time.sleep(0.3)

                def close(self) -> None:
                    if self.serial.is_open:
                        self.serial.close()

                def flush_input(self) -> None:
                    self.serial.reset_input_buffer()
                    self.serial.reset_output_buffer()

                def _read_until(self, min_bytes: int, ending: bytes, timeout: float = 10.0) -> bytes:
                    data = bytearray()
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        if self.serial.in_waiting:
                            chunk = self.serial.read(1)
                            if chunk:
                                data.extend(chunk)
                                if len(data) >= min_bytes and data.endswith(ending):
                                    break
                        else:
                            time.sleep(0.001)
                    return bytes(data)

                def write(self, data: bytes) -> None:
                    self.serial.write(data)
                    self.serial.flush()

                def enter_raw_repl(self) -> None:
                    self.write(b"\r\x03\x03")
                    time.sleep(0.1)
                    self.flush_input()
                    self.write(b"\r\x01")
                    banner = self._read_until(1, b">", timeout=2.0)
                    if not banner.endswith(b">"):
                        raise RuntimeError("Failed to enter raw REPL")

                def exit_raw_repl(self) -> None:
                    self.write(b"\r\x02")
                    time.sleep(0.1)

                def exec_(self, command: str | bytes) -> bytes:
                    if isinstance(command, str):
                        payload = command.encode("utf-8")
                    else:
                        payload = command

                    if not payload.endswith(b"\n"):
                        payload += b"\n"

                    self.write(payload)
                    self.write(b"\x04")

                    data = self._read_until(1, b"\x04", timeout=5.0)
                    err = self._read_until(1, b"\x04", timeout=5.0)
                    status = self.serial.read(1)

                    if status == b"\x00":
                        self._read_until(0, b">", timeout=1.0)
                        return data[:-1]

                    if status == b"\x01":
                        err_text = err[:-1].decode("utf-8", errors="replace") if err else ""
                        raise RuntimeError(f"Execution failed: status {status!r} {err_text}")

                    # Some firmware revisions return textual prompts (e.g. 'OK\r\n>')
                    tail = status + self._read_until(0, b">", timeout=1.0)
                    prompt = tail.decode("utf-8", errors="replace").strip()
                    if prompt.endswith(">"):
                        return data[:-1]

                    err_text = err[:-1].decode("utf-8", errors="replace") if err else ""
                    raise RuntimeError(f"Execution failed: status {status!r} {err_text} {prompt}")

                def fs_put(self, src: str, dest: str) -> None:
                    data = Path(src).read_bytes()
                    first = True
                    for offset in range(0, len(data), 512):
                        chunk = data[offset : offset + 512]
                        payload = base64.b64encode(chunk).decode("ascii")
                        mode = "wb" if first else "ab"
                        first = False
                        self.exec_(
                            f"import ubinascii\nopen({dest!r}, '{mode}').write(ubinascii.a2b_base64('{payload}'))"
                        )

                    if first:
                        self.exec_(f"open({dest!r}, 'wb').close()")
    else:
        Pyboard = _pyboard.Pyboard  # type: ignore[attr-defined]

# Flag to detect rich filesystem helpers exposed by mpremote's Pyboard
HAS_FS_PUT = hasattr(globals().get("Pyboard"), "fs_put")  # type: ignore[arg-type]

PROJECT_ROOT = Path(__file__).resolve().parent
FILES_TO_COPY: tuple[Path, ...] = (
    PROJECT_ROOT / "styles.css",
    PROJECT_ROOT / "RingBuffer.mpy",
    PROJECT_ROOT / "boot.py",
    PROJECT_ROOT / "my_secrets.py",
)
MAIN_FILE = PROJECT_ROOT / "asynchio4.py"
MICRODOT_VERSION = "2.3.3"
MICRODOT_CACHE_DIR = PROJECT_ROOT / f"microdot-{MICRODOT_VERSION}"
MICRODOT_TARBALL = PROJECT_ROOT / f"v{MICRODOT_VERSION}.tar.gz"
MICRODOT_FILES: tuple[str, ...] = ("microdot.py", "__init__.py")


@contextmanager
def board_connection(port: str, baudrate: int = 115200):
    """Context manager that opens a pyboard connection and enters raw REPL."""

    connection = Pyboard(port, baudrate=baudrate)
    try:
        connection.enter_raw_repl()
        yield connection
    finally:
        try:
            connection.exit_raw_repl()
        finally:
            connection.close()


def detect_active_conda_env() -> Optional[str]:
    """Return the name of the currently active Conda environment if any."""

    name = os.environ.get("CONDA_DEFAULT_ENV")
    if name:
        return name

    prefix = os.environ.get("CONDA_PREFIX")
    if prefix:
        return Path(prefix).name

    return None


def ensure_environment(expected: Optional[str]) -> None:
    """Abort if the expected conda environment is not active."""

    if expected is None:
        return

    active_env = detect_active_conda_env()
    if active_env == expected:
        return

    if active_env:
        message = (
            f"This script expected the `{expected}` Conda environment but `{active_env}` is active.\n"
            "Activate the correct environment (e.g. `conda activate rpico`) before running."
        )
        raise SystemExit(message)

    message = (
        "This script expected the `rpico` Conda environment to be active but no Conda"
        " environment was detected. Activate it before running or pass --skip-env-check."
    )
    raise SystemExit(message)


def ensure_microdot_sources(cache_dir: Path, tarball: Path) -> Path:
    """Download and extract the Microdot sources if needed."""

    if cache_dir.exists():
        return cache_dir

    url = f"https://github.com/miguelgrinberg/microdot/archive/refs/tags/v{MICRODOT_VERSION}.tar.gz"
    print(f"Downloading Microdot {MICRODOT_VERSION} from {url}...")
    urllib.request.urlretrieve(url, tarball)

    with tarfile.open(tarball, "r:gz") as archive:
        archive.extractall(PROJECT_ROOT)

    return cache_dir


def maybe_compile_with_mpy_cross(source: Path) -> Path:
    """Compile ``source`` to .mpy if the mpy-cross Python bindings are available."""

    try:
        import mpy_cross  # type: ignore
    except ImportError:
        return source

    target = source.with_suffix(".mpy")
    run_fn = None
    for candidate in ("run", "compile", "mpy_cross"):
        run_fn = getattr(mpy_cross, candidate, None)
        if callable(run_fn):
            break

    if run_fn is None:
        return source

    print(f"Compiling {source.name} -> {target.name} with mpy-cross")
    run_fn(str(source), str(target))
    return target if target.exists() else source


def wipe_board(connection: Pyboard) -> None:
    """Recursively delete every file from the board."""

    script = textwrap.dedent(
        """
        import os

        def _rm(path):
            try:
                mode = os.stat(path)[0]
            except OSError:
                return
            is_dir = bool(mode & 0x4000)
            if is_dir:
                for child in os.listdir(path):
                    _rm(path + '/' + child)
                try:
                    os.rmdir(path)
                except OSError:
                    pass
            else:
                try:
                    os.remove(path)
                except OSError:
                    pass

        for entry in os.listdir():
            _rm(entry)
        """
    ).strip()

    connection.exec_(script)


def install_mip_packages(connection: Pyboard, packages: Iterable[str]) -> None:
    """Run micropython mip.install for each package name."""

    for package in packages:
        print(f"Installing {package} via mip...")
        command = f"import mip\nmip.install('{package}')\n"
        connection.exec_(command)


def _ensure_chunk_writer(connection: Pyboard) -> None:
    marker = "__cuwatch_write_chunk__"
    script = textwrap.dedent(
        """
        import ubinascii

        def __cuwatch_write_chunk__(path, data_b64, mode):
            data = ubinascii.a2b_base64(data_b64)
            with open(path, mode) as fp:
                fp.write(data)
        """
    ).strip()

    # The helper might already exist if we reused the connection.
    exists = connection.exec_(f"print('{marker}' in globals())").strip() == b"True"
    if not exists:
        connection.exec_(script)


def put_file(connection: Pyboard, source: Path, destination: str) -> None:
    """Copy a file from the host to the MicroPython filesystem."""

    print(f"Copying {source.name} -> {destination}")

    if HAS_FS_PUT:
        connection.fs_put(str(source), destination)
        return

    _ensure_chunk_writer(connection)

    data = source.read_bytes()
    first = True
    for offset in range(0, len(data), 512):
        chunk = data[offset : offset + 512]
        payload = base64.b64encode(chunk).decode("ascii")
        mode = "wb" if first else "ab"
        first = False
        connection.exec_(
            f"__cuwatch_write_chunk__({destination!r}, '{payload}', '{mode}')"
        )

    if first:  # empty file case
        connection.exec_(f"open({destination!r}, 'wb').close()")



def list_remote_tree(connection: Pyboard) -> str:
    """Return a tree representation of the board filesystem."""

    script = textwrap.dedent(
        """
        import os

        def tree(path='', prefix=''):
            try:
                entries = sorted(os.listdir(path or '.'))
            except OSError:
                return
            total = len(entries)
            for index, name in enumerate(entries):
                full = (path + '/' + name) if path else name
                try:
                    stat = os.stat(full)
                except OSError:
                    stat = (0,) * 7
                is_dir = bool(stat[0] & 0x4000)
                size = stat[6] if len(stat) > 6 else 0
                branch = '|-- ' if index < total - 1 else '`-- '
                print(f"{prefix}{branch}{name} ({size} bytes)")
                if is_dir:
                    extension = '|   ' if index < total - 1 else '    '
                    tree(full, prefix + extension)

        tree()
        """
    ).strip()

    return connection.exec_(script).decode("utf-8", errors="replace").strip()


def upload_project(connection: Pyboard) -> None:
    """Send project files to the board."""

    wipe_board(connection)
    install_mip_packages(connection, ("sdcard", "ntptime"))

    for path in FILES_TO_COPY:
        put_file(connection, path, f"/{path.name}")

    put_file(connection, MAIN_FILE, "/main.py")

    microdot_source_dir = ensure_microdot_sources(MICRODOT_CACHE_DIR, MICRODOT_TARBALL)
    microdot_dir = microdot_source_dir / "src" / "microdot"

    for filename in MICRODOT_FILES:
        source = microdot_dir / filename
        staged = maybe_compile_with_mpy_cross(source)
        destination = f"/{staged.name}"
        put_file(connection, staged, destination)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install project files onto a MicroPython board using mpremote APIs.",
    )
    parser.add_argument("--port", required=True, help="Serial port of the MicroPython board (e.g. COM3)")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baudrate (default: 115200)")
    parser.add_argument(
        "--skip-env-check",
        action="store_true",
        help="Skip checking that the rpico Conda environment is active.",
    )
    parser.add_argument(
        "--expected-env",
        default="rpico",
        help="Name of the Conda environment expected to be active (default: rpico).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    expected_env = None if args.skip_env_check else args.expected_env
    ensure_environment(expected_env)

    with board_connection(args.port, args.baud) as connection:
        upload_project(connection)
        tree_output = list_remote_tree(connection)

    if tree_output:
        print("Remote filesystem contents:")
        print(tree_output)


if __name__ == "__main__":  # pragma: no cover
    main()
