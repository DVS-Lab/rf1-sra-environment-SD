#!/usr/bin/env python3
"""Stop only an unbuilt moderation preflight; never signal predictors or native jobs."""
from __future__ import annotations

import argparse
import errno
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


def process_identity(pid, proc=Path("/proc")):
    path = proc / str(pid)
    uid = path.stat().st_uid
    first = (path / "stat").read_bytes()
    argv = tuple(os.fsdecode(v) for v in (path / "cmdline").read_bytes().split(b"\0") if v)
    last = (path / "stat").read_bytes()
    # Linux stat field 22 is starttime. comm may contain spaces and ')'.
    def started(data):
        prefix, separator, rest = data.rpartition(b")")
        fields = rest.split()
        if not separator or int(prefix.split(b" ", 1)[0]) != pid or len(fields) < 20:
            raise RuntimeError("Cannot establish preflight process identity; no process signalled")
        return int(fields[19])
    start = started(first)
    if uid != os.getuid() or started(last) != start:
        raise RuntimeError("Preflight owner/start time changed; no process signalled")
    return uid, start, argv


def stop_preflight(pid, expected, project):
    if "--prepare-only" not in expected:
        raise RuntimeError("Refusing to signal a full moderation runner")
    current, _ = processes(project)
    if (pid, expected) not in current:
        raise RuntimeError("Preflight changed during inspection; no process signalled")
    try:
        identity = process_identity(pid)
    except (FileNotFoundError, ProcessLookupError):
        return
    if identity[2] != tuple(expected):
        raise RuntimeError("Preflight command changed; no process signalled")
    unsupported = {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}
    opener = getattr(os, "pidfd_open", None)
    sender = getattr(signal, "pidfd_send_signal", None)
    if callable(opener) and callable(sender):
        descriptor = None
        try:
            descriptor = opener(pid)
            if process_identity(pid) != identity:
                raise RuntimeError("Preflight identity changed; no process signalled")
            sender(descriptor, signal.SIGTERM)
            print(f"TERM sent only to queued moderation preflight PID {pid} via pidfd; predictors untouched.", flush=True)
            return
        except (FileNotFoundError, ProcessLookupError):
            return
        except OSError as exc:
            if exc.errno not in unsupported:
                raise
        finally:
            if descriptor is not None:
                os.close(descriptor)
    # Compatibility path: tightly recheck UID, starttime and the entire argv.
    # Unlike pidfd this is not atomic with kill, so never use broad PID matches.
    try:
        if process_identity(pid) != identity:
            raise RuntimeError("Preflight identity changed; no process signalled")
        os.kill(pid, signal.SIGTERM)
    except (FileNotFoundError, ProcessLookupError):
        return
    print(f"TERM sent only to queued moderation preflight PID {pid} via UID/starttime/argv-checked compatibility path; predictors untouched.", flush=True)


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
