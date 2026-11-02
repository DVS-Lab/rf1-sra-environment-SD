#!/usr/bin/env python3
"""Stop only an unbuilt moderation preflight; never signal predictors or native jobs."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import sys
import time


def processes(project, proc=Path("/proc")):
    coordinators, wrappers = [], []
    for path in proc.iterdir():
        if not path.name.isdigit():
            continue
        try:
            if path.stat().st_uid != os.getuid():
                continue
            argv = [v.decode() for v in (path / "cmdline").read_bytes().split(b"\0") if v]
        except (FileNotFoundError, ProcessLookupError):
            continue
        if not argv:
            continue
        if Path(argv[0]).name.startswith("python") and any(Path(a).name == "run_financial_moderation.py" for a in argv):
            if "--project" not in argv or argv.index("--project") + 1 == len(argv):
                raise RuntimeError("Unrecognized moderation coordinator; refusing to signal anything")
            if Path(argv[argv.index("--project") + 1]).resolve() == project:
                coordinators.append((int(path.name), argv))
        for i, arg in enumerate(argv[:-1]):
            if Path(arg).name == "run_financial_moderation.sh" and Path(argv[i + 1]).resolve() == project:
                wrappers.append(int(path.name))
    return coordinators, wrappers


def stop_preflight(pid, expected, project):
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise RuntimeError("Linux pidfd support required for a race-safe stop; no process signalled")
    try:
        descriptor = os.pidfd_open(pid)
    except ProcessLookupError:
        return
    try:
        current, _ = processes(project)
        if (pid, expected) not in current:
            raise RuntimeError("Preflight changed during inspection; no process signalled")
        # The pidfd pins the inspected process, avoiding PID-reuse signalling.
        signal.pidfd_send_signal(descriptor, signal.SIGTERM)
        print(f"TERM sent only to queued moderation preflight PID {pid}; predictors untouched.", flush=True)
    finally:
        os.close(descriptor)


def memory_available_kib():
    fields = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return int(fields["MemAvailable"].split()[0])


def unqueue(project, timeout=180):
    output = project / "derivatives/fsl/randomise/katie-financial-moderation-v1"
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("Moderation outputs already exist; preserve them and resume their recorded release, not this switch")
    if memory_available_kib() < 16 * 1024 * 1024:
        raise RuntimeError("Less than 16 GiB available; no processes changed")
    current, _ = processes(project)
    if len(current) > 1 or any("--prepare-only" not in argv for _, argv in current):
        raise RuntimeError("Moderation is already running or has multiple coordinators; no processes changed")
    for pid, argv in current:
        stop_preflight(pid, argv, project)
    deadline = time.monotonic() + timeout
    while True:
        current, wrappers = processes(project)
        if not current and not wrappers:
            break
        if any("--prepare-only" not in argv for _, argv in current):
            raise RuntimeError("Moderation advanced to inference; leaving it untouched, no replacement launched")
        if time.monotonic() >= deadline:
            raise RuntimeError("Old preflight/wrapper still exiting; no forced kill or replacement launch")
        print("Waiting for the old preflight and its log-publishing wrapper to exit...", flush=True)
        time.sleep(2)
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("Preflight produced outputs during stop; preserved, no replacement launched")
    print("CHECK PASSED: no moderation outputs changed; old preflight exited; predictor jobs never signalled.", flush=True)


def main():
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    unqueue(args.project.resolve())


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print(f"STOPPED ({type(exc).__name__}): {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
