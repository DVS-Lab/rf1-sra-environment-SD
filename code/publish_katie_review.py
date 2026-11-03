#!/usr/bin/env python3
"""Publish only a sealed aggregate review through an isolated clone, never the live index."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import run_katie_randomise as base

REMOTE = "https://github.com/DVS-Lab/rf1-sra-environment-SD.git"
DESTINATION = Path("results/review/katie-review-v1")


def payload(report):
    manifest = json.loads((report / "review_manifest.json").read_text())
    files = ["review_manifest.json", *manifest["outputs"]]
    for name in files:
        path = report / name
        if Path(name).is_absolute() or ".." in Path(name).parts or path.is_symlink() or not path.resolve().is_relative_to(report.resolve()):
            raise ValueError("Unsafe review payload path")
        if path.suffix not in (".png",".tsv",".json",".md",".html"):
            raise ValueError("Only aggregate review tables/figures may be published")
        if name != "review_manifest.json" and base.cohort.digest(path) != manifest["outputs"][name]:
            raise ValueError("Sealed review changed before publication")
    return files


def publish(project, report, destination=None):
    target = DESTINATION if destination is None else Path(destination)
    if (target.is_absolute() or ".." in target.parts or len(target.parts) != 3
            or target.parts[:2] != ("results", "review")):
        raise ValueError("Use a versioned results/review/<name> destination")
    files = payload(report)
    workspace = Path(tempfile.mkdtemp(prefix="publish-review-",dir=project / "work")); workspace.chmod(0o777)
    clone = workspace / "repo"
    def git(*args, cwd=clone, check=True):
        result=subprocess.run(["git",*args],cwd=cwd,check=False,text=True,capture_output=True,
                              env=dict(os.environ,GIT_TERMINAL_PROMPT="0",GIT_EDITOR="true"))
        if check and result.returncode:raise RuntimeError("Git command failed: "+" ".join(args)+"\n"+result.stderr[-4000:])
        return result
    try:
        # Shared lab repositories may be owned by another account. Clone HTTPS,
        # not the live .git directory, without weakening Git ownership checks.
        git("clone","--no-checkout","--single-branch","--branch","main",REMOTE,str(clone),cwd=project)
        git("remote","set-url","origin",REMOTE)
        git("fetch","origin","main"); git("checkout","--detach","FETCH_HEAD")
        destination = clone / target
        if destination.exists():
            if any(not (destination/name).is_file() or base.cohort.digest(destination/name) != base.cohort.digest(report/name) for name in files):
                raise ValueError("An existing published review differs; preserve both and choose a versioned destination")
            print("ALREADY PUBLISHED: aggregate review identical; live checkout untouched."); shutil.rmtree(workspace); return
        for name in files:
            path = destination / name; path.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(report/name,path)
        for key in ("user.name","user.email"):
            value = git("config","--get",key,cwd=project).stdout.strip()
            if not value: raise ValueError("Missing source Git author identity")
            git("config",key,value)
        git("add","--",str(target)); git("commit","-m","Publish validated aggregate review: "+target.name)
        for attempt in range(3):
            pushed = git("push","origin","HEAD:main",check=False)
            if pushed.returncode == 0: break
            if "fetch first" not in pushed.stderr and "non-fast-forward" not in pushed.stderr:
                raise RuntimeError(pushed.stderr)
            git("fetch","origin","main"); git("rebase","FETCH_HEAD")
        else: raise RuntimeError("Remote kept advancing; staged review preserved for inspection")
        commit = git("rev-parse","HEAD").stdout.strip()
        print("PUBLISHED aggregate review at " + commit)
        print("https://github.com/DVS-Lab/rf1-sra-environment-SD/blob/main/"+str(target / "README.md"))
        print("Live branch, index, working files, completed inference and exclusions unchanged.")
        shutil.rmtree(workspace)
    except BaseException:
        print("Publication workspace preserved: "+str(workspace)); raise


if __name__ == "__main__":
    os.umask(0)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project",type=Path,required=True);parser.add_argument("--report",type=Path,required=True)
    parser.add_argument("--destination",type=Path)
    args=parser.parse_args();publish(args.project.resolve(),args.report.resolve(),args.destination)
