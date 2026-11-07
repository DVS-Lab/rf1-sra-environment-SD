#!/usr/bin/env python3
"""Publish only the explicitly sealed closeout source files through an isolated HTTPS clone."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

REMOTE='https://github.com/DVS-Lab/rf1-sra-environment-SD.git'
MANIFEST='config/katie_closeout_source_manifest_v1.json'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def publish(project,release):
    manifest=json.loads((release/MANIFEST).read_text())
    files=list(manifest['files'])+[MANIFEST]
    for name in files:
        path=Path(name)
        if (path.is_absolute() or '..' in path.parts or len(path.parts)<2 or path.parts[0] not in ('code','tests','config','docs')
                or path.suffix not in ('.py','.sh','.json','.md') or (release/path).is_symlink()
                or not (release/path).resolve().is_relative_to(release.resolve())):
            raise ValueError('Unapproved source payload path')
        if name!=MANIFEST and sha(release/path)!=manifest['files'][name]['sha256']:
            raise ValueError('Source payload seal differs: '+name)
    workspace=Path(tempfile.mkdtemp(prefix='publish-katie-closeout-source-',dir=project/'work'));workspace.chmod(0o777)
    clone=workspace/'repo'
    def git(*args,cwd=clone,check=True):
        r=subprocess.run(['git',*args],cwd=cwd,text=True,capture_output=True,env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GIT_EDITOR='true'))
        if check and r.returncode:raise RuntimeError('Git source publication stopped: '+r.stderr[-2500:])
        return r
    try:
        git('clone','--no-checkout','--single-branch','--branch','main',REMOTE,str(clone),cwd=project)
        git('checkout','--detach','FETCH_HEAD') if (clone/'.git/FETCH_HEAD').is_file() else git('checkout','--detach','origin/main')
        changed=[]
        for name in files:
            destination=clone/name;new=(release/name).read_bytes()
            if destination.is_file() and destination.read_bytes()==new:continue
            expected=manifest['files'].get(name,{}).get('previous_sha256')
            if destination.exists() and (not destination.is_file() or sha(destination)!=expected):
                raise ValueError('Remote source changed concurrently; no overwrite: '+name)
            if not destination.exists() and expected is not None:raise ValueError('Expected previous source missing')
            destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(new);changed.append(name)
        if not changed:
            print('SOURCE ALREADY PUBLISHED; frozen release and live checkout preserved.');shutil.rmtree(workspace);return
        for key in ('user.name','user.email'):
            value=git('config','--get',key,cwd=project).stdout.strip()
            if not value:raise ValueError('Missing Git author identity in analysis checkout')
            git('config',key,value)
        git('add','--',*changed);git('commit','-m','Add bounded Katie results closeout: two support-sensitivity jobs and descriptive follow-ups')
        for _ in range(3):
            r=git('push','origin','HEAD:main',check=False)
            if r.returncode==0:break
            if 'fetch first' not in r.stderr and 'non-fast-forward' not in r.stderr:raise RuntimeError(r.stderr)
            git('fetch','origin','main');git('rebase','FETCH_HEAD')
        else:raise RuntimeError('Remote kept advancing; publication clone preserved')
        print('SOURCE PUBLISHED: '+git('rev-parse','HEAD').stdout.strip())
        print('Live branch/index, source data, original results and exclusions unchanged.')
        shutil.rmtree(workspace)
    except BaseException:
        print('Publication workspace preserved: '+str(workspace));raise


if __name__=='__main__':
    os.umask(0);p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,required=True);p.add_argument('--release',type=Path,required=True);a=p.parse_args();publish(a.project.resolve(),a.release.resolve())
