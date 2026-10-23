"""Run ArcPy scripts in ArcGIS Pro inside a Parallels Windows VM.

The Mac home folder is visible in Windows as \\\\Mac\\Home, so scripts and
outputs live in this project folder and only the gdb scratch space is local
to Windows (file geodatabases on a network share are slow and fragile).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
RUNS = PROJECT / "runs"

VM = os.environ.get("PROVEIT_VM", "Windows 11")
PROPY = os.environ.get(
    "PROVEIT_PROPY", r"C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\propy.bat"
)
MAC_HOME = Path(os.environ.get("PROVEIT_MAC_HOME", str(Path.home())))
WIN_HOME = os.environ.get("PROVEIT_WIN_HOME", r"\\Mac\Home")
# Local Windows scratch for geodatabases; never on the shared folder.
WIN_WORK = os.environ.get("PROVEIT_WIN_WORK", r"C:\proveit_work")


def to_windows(path: Path | str) -> str:
    """Map a Mac path under the home folder to its Parallels share path."""
    p = Path(path).resolve()
    try:
        rel = p.relative_to(MAC_HOME)
    except ValueError as exc:
        raise ValueError(f"{p} is not under {MAC_HOME}; the VM cannot see it") from exc
    return WIN_HOME + "\\" + "\\".join(rel.parts)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class RunResult:
    script: str
    args: list[str]
    returncode: int
    seconds: float
    stdout: str
    stderr: str
    started: str
    script_sha256: str
    log: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _quote(arg: str) -> str:
    return f'"{arg}"' if (" " in arg or "&" in arg) else arg


def run_in_pro(script: Path | str, *args: str, timeout: int = 3600) -> RunResult:
    """Run `script` with ArcGIS Pro's Python in the VM and log the run.

    Arguments are passed through cmd.exe, so keep them simple (paths, names);
    put anything complicated in a JSON file and pass its path.
    """
    script = Path(script).resolve()
    win_args = [to_windows(a) if Path(a).is_absolute() else a for a in args]
    cmd_line = " ".join(
        [_quote(PROPY), _quote(to_windows(script))] + [_quote(a) for a in win_args]
    )
    cmd = ["prlctl", "exec", VM, "--current-user", "cmd", "/c", cmd_line]
    env_note = {"PROVEIT_WIN_WORK": WIN_WORK}

    started = dt.datetime.now().isoformat(timespec="seconds")
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        rc, out, err = -9, exc.stdout or "", f"timeout after {timeout}s"
        out = out.decode() if isinstance(out, bytes) else out

    result = RunResult(
        script=str(script.relative_to(PROJECT)) if script.is_relative_to(PROJECT) else str(script),
        args=list(args),
        returncode=rc,
        seconds=round(time.time() - t0, 1),
        stdout=out,
        stderr=err,
        started=started,
        script_sha256=sha256(script),
        extra={"vm": VM, "propy": PROPY, **env_note},
    )
    RUNS.mkdir(exist_ok=True)
    stamp = started.replace(":", "").replace("-", "")
    log = RUNS / f"{stamp}_{script.stem}.json"
    result.log = str(log.relative_to(PROJECT))
    log.write_text(json.dumps(asdict(result), indent=2))
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Run an ArcPy script in ArcGIS Pro (VM).")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("script")
    ap.add_argument("args", nargs=argparse.REMAINDER, help="passed to the script, e.g. --views")
    ns = ap.parse_args(argv)
    res = run_in_pro(ns.script, *ns.args, timeout=ns.timeout)
    print(res.stdout, end="")
    if res.stderr.strip():
        print(res.stderr, end="")
    print(f"\n[proveit] exit {res.returncode} in {res.seconds}s, log {res.log}")
    return res.returncode


if __name__ == "__main__":
    raise SystemExit(main())
