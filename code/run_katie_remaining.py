#!/usr/bin/env python3
"""Run isolated task activation, conditional effects and compatible VS PPI, capped at 48 workers."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import fcntl
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

import nibabel as nib
import numpy as np
from scipy.stats import norm, t

import audit_katie_outcome as outcome
import run_katie_main_effects as conditional
import run_katie_randomise as base
import summarize_katie_randomise as summary


def paths_from_fsf(path):
    text = path.read_text()
    result = outcome.settings(path)
    for key in ("feat_files(1)", "confoundev_files(1)"):
        matches = re.findall(r"^set\s+" + re.escape(key) + r"\s+(.+)$", text, re.M)
        if len(matches) != 1:
            raise ValueError("Missing/ambiguous FSF input: " + str(path) + " " + key)
        result[key] = shlex.split(matches[0])[0]
    return result


def matrix(path):
    return np.loadtxt(io.StringIO(path.read_text().split("/Matrix", 1)[1]), ndmin=2)


def load_checked(path):
    plan = base.load_plan(path)
    for name, digest in plan["outputs"].items():
        if base.cohort.digest(path / name) != digest:
            raise ValueError("Frozen generated file changed: " + str(path / name))
    return plan


def seal(staging, destination, plan, files):
    for name, text in files.items():
        path = staging / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    plan["outputs"] = {str(p.relative_to(staging)): base.cohort.digest(p)
                       for p in staging.rglob("*") if p.is_file()}
    base.write_json(staging / "plan.json", plan)
    (staging / "plan.sha256").write_text(base.cohort.digest(staging / "plan.json") + "\n")
    if base.STOP:
        raise InterruptedError("Stopped; staging preserved: " + str(staging))
    staging.rename(destination)
    return load_checked(destination)


def stage_for(destination):
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Nonempty unrecognized destination; refusing overwrite: " + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="." + destination.name + "-build-", dir=destination.parent))
    staging.chmod(0o777)
    return staging


def group_specs(baseline, pairs, output):
    jobs, files = [], {}
    lookup = base.cohort.unique(pairs, ("subject", "contrast"))
    for name in ("socialdoors", "doors", "average", "social_specific"):
        reference = Path(next(j["design"] for j in baseline["jobs"]
                              if j["outcome"] == ("social_specific" if name == "social_specific" else "average")))
        headers, rows = base.cohort.read_table(reference.with_suffix(".tsv"))
        names = headers[1:8]
        x = np.array([[float(r[n]) for n in names] for r in rows])
        if name in ("socialdoors", "doors"):
            for index, metric in ((1, "fd_mean"), (2, "tsnr")):
                x[:, index] = base.review.center([float(lookup[(r["subject"], "4")][name + "_" + metric]) for r in rows])
            names = [names[0], name + "_fd_mean", name + "_tsnr", *names[3:]]
        if x.shape != (97, 7) or np.linalg.matrix_rank(x) != 7 or not np.allclose(x[:, 1:].mean(axis=0), 0, atol=1e-10):
            raise ValueError("Invalid centered group-average design")
        folder = Path("designs") / name
        files[str(folder / "design.mat")] = base.vest_matrix(x)
        files[str(folder / "design.con")] = base.vest_contrasts(names, "ones")
        files[str(folder / "design.tsv")] = base.review.tsv([dict(subject=r["subject"], **dict(zip(names, v))) for r, v in zip(rows, x)])
        for z in (2.6, 3.1):
            jobs.append(dict(key=name + "/group_mean/z-" + str(z).replace(".", "p"), outcome=name, model="group_mean",
                             z=z, t_cutoff=float(t.isf(norm.sf(z), 90)), residual_dof=90,
                             design=str(output / folder / "design.mat"), contrast=str(output / folder / "design.con"),
                             permutations=10000, seed=20261101))
    return files, jobs


def build_group(args, baseline, pairs):
    destination = args.output / "activation"
    if (destination / "plan.json").exists():
        return load_checked(destination)
    staging = stage_for(destination)
    _, roster = base.cohort.read_table(args.baseline / "subjects.tsv")
    ids = [r["subject"] for r in roster]
    lookup = base.cohort.unique(pairs, ("subject", "contrast"))
    mask = nib.load(baseline["mask"])
    support = mask.get_fdata() > 0
    images = dict(baseline["images"])
    for task in ("socialdoors", "doors"):
        data = np.zeros(mask.shape + (97,), dtype=np.float32)
        for index, sub in enumerate(ids):
            image = nib.load(lookup[(sub, "4")][task + "_cope"])
            base.grid(mask, image)
            values = image.get_fdata()[support]
            if not np.isfinite(values).all():
                raise ValueError("Nonfinite original COPE")
            data[..., index][support] = values
        base.save_image(staging / f"inputs/{task}.nii.gz", data, mask)
        images[task] = str(destination / f"inputs/{task}.nii.gz")
    files, jobs = group_specs(baseline, pairs, destination)
    files["subjects.tsv"] = (args.baseline / "subjects.tsv").read_text()
    sources = [*baseline["sources"], *[base.fingerprint(args.baseline / p) for p in baseline["outputs"]],
               base.fingerprint(args.baseline / "plan.json"), base.fingerprint(Path(__file__))]
    plan = dict(n=97, jobs=jobs, images=images, mask=baseline["mask"], randomise=baseline["randomise"], sources=sources,
                meaning="Group win-loss response; centered task/pair QC, scanner era, age and gender; one image per participant",
                sign_flipping_required=True)
    return seal(staging, destination, plan, files)


def ppi_definitions(args, pairs):
    jobs = []
    source_files = [args.task_project / f for f in ("code/L1stats.sh", "code/project_config.sh", "masks/seed-VS.nii.gz",
                       "templates/L1_task-socialdoors_model-1_type-ppi.fsf", "templates/L1_task-doors_model-1_type-ppi.fsf")]
    for pair in pairs:
        if pair["contrast"] != "4":
            continue
        for task in ("socialdoors", "doors"):
            feat = Path(pair[task + "_feat_dir"])
            settings = paths_from_fsf(feat / "design.fsf")
            evroot = Path(settings["custom1"]).parents[3]
            expected = evroot / f"sub-{pair['subject']}/ses-01/{task}/run-1_win.txt"
            if expected.resolve() != Path(settings["custom1"]).resolve():
                raise ValueError("Noncanonical EV root; inspect rather than guess")
            old = args.task_project / f"derivatives/fsl/sub-{pair['subject']}/ses-01/L1_task-{task}_ses-01_model-1_type-ppi_seed-VS_run-1_sm-5.feat"
            jobs.append(dict(key=f"sub-{pair['subject']}_ses-01_task-{task}_run-1", subject=pair["subject"], task=task,
                             activation=str(feat), bold=settings["feat_files(1)"], confounds=settings["confoundev_files(1)"],
                             evroot=str(evroot), old=str(old), files=[str(p) for p in source_files],
                             act_settings=settings))
    if len(jobs) != 194 or len({j["key"] for j in jobs}) != 194:
        raise ValueError("Expected 194 VS-PPI L1 units")
    return jobs


def verify_ppi(feat, job):
    settings = paths_from_fsf(feat / "design.fsf")
    for key, source in (("feat_files(1)", job["bold"]), ("confoundev_files(1)", job["confounds"])):
        path = Path(settings[key])
        if path.resolve() != Path(source).resolve() and base.cohort.digest(path) != base.cohort.digest(Path(source)):
            raise ValueError("PPI BOLD/confounds differs from approved no-TEDANA activation: " + key)
    if [settings.get(f"evtitle{i}") for i in range(1, 10)] != ["win", "loss", "decision", "miss", "phys", "ppi-win", "ppi-loss", "ppi-dec", "ppi-miss"]:
        raise ValueError("Unexpected VS-PPI EV order")
    if settings.get("evs_real") != "9" or any(settings.get(f"deriv_yn{i}") != "0" for i in range(1, 10)):
        raise ValueError("Unexpected expanded PPI task-EV design")
    for key in ("smooth", "temphp_yn", "templp_yn", "motionevs"):
        if settings.get(key) != job["act_settings"].get(key):
            raise ValueError("PPI preprocessing policy differs from approved activation: " + key)
    for index, psychological in ((6, 1), (7, 2), (8, 3), (9, 4)):
        partners = {int(k.rsplit(".", 1)[1]) for k, value in settings.items()
                    if k.startswith(f"interactions{index}.") and float(value) != 0}
        if partners != {psychological, 5}:
            raise ValueError("PPI interaction is not the expected task event x VS series")
    for i in range(1, 5):
        path, source = Path(settings[f"custom{i}"]), Path(job["act_settings"][f"custom{i}"])
        if i == 4 and settings.get("shape4") == "10" and job["act_settings"].get("shape4") == "10":
            continue
        if base.cohort.digest(path) != base.cohort.digest(source):
            raise ValueError("PPI task EV differs from approved activation")
    c, x = matrix(feat / "design.con"), matrix(feat / "design.mat")
    expected = np.zeros(c.shape[1]); expected[5:7] = [1, -1]
    if (c.shape[0] != 5 or c.shape[1] < 9 or not np.array_equal(c[3], expected)
            or x.shape[1] != c.shape[1] or not np.isfinite(x).all()
            or not np.allclose(c[3] @ np.linalg.pinv(x) @ x, c[3], rtol=1e-6, atol=1e-6)):
        raise ValueError("Invalid/unestimable outcome PPI-win minus PPI-loss contrast")
    dof = float((feat / "stats/dof").read_text().strip())
    if not np.isfinite(dof) or dof <= 0:
        raise ValueError("PPI has no valid residual degrees of freedom")
    bold = nib.load(job["bold"])
    series = np.loadtxt(settings["custom5"], ndmin=1)
    if series.shape != (bold.shape[3],) or x.shape[0] != bold.shape[3] or not np.isfinite(series).all():
        raise ValueError("VS seed/design row count differs from BOLD")
    mask = nib.load(feat / "mask.nii.gz")
    base.grid(bold, mask)
    for name in ("stats/cope4.nii.gz", "stats/varcope4.nii.gz"):
        image = nib.load(feat / name)
        base.grid(mask, image)
        if not np.isfinite(image.get_fdata()[mask.get_fdata() > 0]).all():
            raise ValueError("Invalid PPI estimate")
    names = ["design.fsf", "design.con", "design.mat", "mask.nii.gz", "stats/cope4.nii.gz", "stats/varcope4.nii.gz", "stats/dof"]
    return [base.fingerprint(feat / name) for name in names] + [base.fingerprint(Path(settings["custom5"]))]


def child(call, log_path, environment=None):
    with log_path.open("w") as stream:
        process = subprocess.Popen(call, stdout=stream, stderr=subprocess.STDOUT, env=environment, start_new_session=True,
                                   pass_fds=() if base.LEASE_FD is None else (base.LEASE_FD,))
        while process.poll() is None:
            if base.STOP:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait()
                raise InterruptedError("Stopped; partial attempt preserved")
            time.sleep(.5)
    if process.returncode:
        ending = "\n".join(log_path.read_text(errors="replace").splitlines()[-25:])
        raise RuntimeError(f"Command failed ({process.returncode}): {log_path}\n{ending}")


def ppi_unit(args, job):
    folder = args.output / "ppi-l1" / job["key"]
    folder.mkdir(parents=True, exist_ok=True)
    receipt = folder / "success.json"
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        if saved["job"] != job:
            raise ValueError("Completed PPI source specification changed")
        base.verify_sources(saved["sources"] + saved["outputs"])
        return "REUSED_PPI"
    if base.STOP:
        return "NOT_STARTED"
    attempts = folder / "attempts"; attempts.mkdir(exist_ok=True)
    number = 1
    while (attempts / f"attempt-{number:04d}").exists():
        number += 1
    attempt = attempts / f"attempt-{number:04d}"; attempt.mkdir()
    files = [Path(p) for p in job["files"]] + [Path(job["bold"]), Path(job["confounds"]), Path(job["activation"]) / "design.fsf"]
    files += [Path(job["act_settings"][f"custom{i}"]) for i in range(1, 5) if Path(job["act_settings"][f"custom{i}"]).is_file()]
    sources = [base.fingerprint(p) for p in sorted(set(files))]
    base.write_json(attempt / "inputs.json", dict(job=job, sources=sources))
    old = Path(job["old"])
    reused = False
    reason = "No complete compatible existing PPI"
    try:
        products = verify_ppi(old, job)
        # An existing physiological series must match a fresh extraction using
        # the actual frozen VS mask, not merely have the right filename/length.
        check_seed = attempt / "seed-check.txt"
        child(["fslmeants", "-i", job["bold"], "-m", job["files"][2], "-o", str(check_seed)], attempt / "seed-check.log")
        current_series = np.loadtxt(paths_from_fsf(old / "design.fsf")["custom5"])
        if not np.allclose(current_series, np.loadtxt(check_seed), rtol=1e-6, atol=1e-6):
            raise ValueError("Existing VS series differs from current seed extraction")
        feat, reused = old, True
    except (ValueError, OSError, KeyError) as exc:
        reason = str(exc)
    if not reused:
        print("BUILD_NO_TEDANA_PPI " + job["key"] + ": " + reason, flush=True)
        project = attempt / "project"
        for source_name in job["files"]:
            source = Path(source_name)
            if source.parent.name == "code":
                relative = Path("code") / source.name
            elif source.parent.name == "masks":
                relative = Path("masks") / source.name
            else:
                relative = Path("templates") / source.name
            target = project / relative; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target); target.chmod(0o666)
        derivatives = project / "derivatives/fsl"
        parent = derivatives / f"sub-{job['subject']}/ses-01"; parent.mkdir(parents=True)
        activation_link = parent / Path(job["activation"]).name
        activation_link.symlink_to(job["activation"], target_is_directory=True)
        environment = dict(os.environ, FSL_DERIVATIVES_ROOT=str(derivatives), EV_FILES_ROOT=job["evroot"], FSLSUB_PARALLEL="1")
        call = ["bash", str(project / "code/L1stats.sh"), job["subject"], "1", "VS", job["task"],
                "--session", "01", "--bold", job["bold"], "--confounds", job["confounds"]]
        child(call, attempt / "feat.log", environment)
        feat = parent / f"L1_task-{job['task']}_ses-01_model-1_type-ppi_seed-VS_run-1_sm-5.feat"
        products = verify_ppi(feat, job)
    base.verify_sources(sources)
    base.write_json(receipt, dict(job=job, sources=sources, outputs=products, feat=str(feat), reused_original=reused,
                                 rebuild_reason="" if reused else reason, completed=datetime.now(timezone.utc).isoformat()))
    return "REUSED_COMPATIBLE_PPI" if reused else "COMPLETED_NO_TEDANA_PPI"


def build_ppi_group(args, baseline, units):
    destination = args.output / "connectivity"
    if (destination / "plan.json").exists():
        return load_checked(destination)
    staging = stage_for(destination)
    reference = nib.load(baseline["mask"])
    mask = reference.get_fdata() > 0
    receipts = {}
    sources = [*baseline["sources"], base.fingerprint(args.baseline / "plan.json"), base.fingerprint(Path(__file__))]
    for unit in units:
        path = args.output / "ppi-l1" / unit["key"] / "success.json"
        saved = json.loads(path.read_text())
        if saved["job"] != unit:
            raise ValueError("PPI source receipt differs")
        base.verify_sources(saved["sources"] + saved["outputs"])
        sources += saved["outputs"] + [base.fingerprint(path)]
        receipts[(unit["subject"], unit["task"])] = saved
        image = nib.load(Path(saved["feat"]) / "mask.nii.gz"); base.grid(reference, image)
        variance = nib.load(Path(saved["feat"]) / "stats/varcope4.nii.gz")
        base.grid(reference, variance)
        mask &= (image.get_fdata() > 0) & (variance.get_fdata() > 0)
    if not mask.any():
        raise ValueError("No common PPI support; no participants excluded")
    _, roster = base.cohort.read_table(args.baseline / "subjects.tsv")
    difference = np.zeros(mask.shape + (97,), dtype=np.float32)
    average = difference.copy()
    for index, row in enumerate(roster):
        values = {}
        for task in ("socialdoors", "doors"):
            image = nib.load(Path(receipts[(row["subject"], task)]["feat"]) / "stats/cope4.nii.gz")
            base.grid(reference, image); values[task] = image.get_fdata()[mask]
        difference[..., index][mask] = values["socialdoors"] - values["doors"]
        average[..., index][mask] = (values["socialdoors"] + values["doors"]) / 2
    for name, data in (("social_specific", difference), ("average", average), ("mask", mask.astype(np.uint8))):
        base.save_image(staging / f"inputs/{name}.nii.gz", data, reference)
    jobs = [dict(job) for job in baseline["jobs"]]
    for job in jobs:
        for path in (job["design"], job["contrast"]):
            sources.append(base.fingerprint(Path(path)))
    files = {"subjects.tsv": (args.baseline / "subjects.tsv").read_text()}
    plan = dict(n=97, jobs=jobs, images={n: str(destination / f"inputs/{n}.nii.gz") for n in ("average", "social_specific")},
                mask=str(destination / "inputs/mask.nii.gz"), randomise=baseline["randomise"], sources=sources,
                meaning="VS PPI-win minus PPI-loss, paired mean/difference; no-TEDANA BOLD/confound/seed lineage verified",
                common_voxels=int(mask.sum()))
    return seal(staging, destination, plan, files)


def report_batch(plan, destination, report):
    mask = nib.load(plan["mask"])
    digest = base.cohort.digest(destination / "plan.json")
    maps, clusters = [], []
    for job in plan["jobs"]:
        saved = json.loads((destination / "jobs" / job["key"] / "success.json").read_text())
        if saved["job"] != job or saved["plan_sha256"] != digest or saved["smoke"]:
            raise ValueError("Final randomise receipt differs")
        base.verify_sources(saved["outputs"])
        for index, direction in ((1, "positive"), (2, "negative")):
            prefix = Path(saved["attempt"]) / "randomise"
            row, found = summary.map_summary(job, direction, nib.load(str(prefix) + f"_tstat{index}.nii.gz"),
                                             nib.load(str(prefix) + f"_clustere_corrp_tstat{index}.nii.gz"), mask)
            maps.append(row); clusters.extend(found)
    files = summary.report_files(maps, clusters, dict(n=97, jobs=len(plan["jobs"]), maps=len(maps),
                  plan_sha256=digest, meaning=plan["meaning"], cross_analysis_correction="none; exploratory per-map FWE"))
    # The shared renderer's original-batch introduction is intentionally replaced.
    files["README.md"] = (f"# Katie {destination.name}: N=97\n\n{plan['meaning']}\n\n"
        f"All {len(plan['jobs'])} jobs / {len(maps)} directional maps verified. See maps.tsv for all results, "
        "including nulls. Cluster-FWE p<0.05 per map; no additional family correction. "
        "No original results or exclusions changed.\n")
    for name, text in files.items():
        path = report / name
        if path.exists() and path.read_text() != text:
            raise ValueError("Existing report differs; do not overwrite: " + str(path))
    report.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = report / name
        if not path.exists(): path.write_text(text)
    for row in maps:
        print(f"RESULT {destination.name} {row['job']} {row['direction']}: min cluster-FWE p={row['min_cluster_fwe_p']:.4f}; voxels={row['significant_voxels']}", flush=True)


def run(args):
    baseline = base.check(SimpleNamespace(output=args.baseline, upstream=args.upstream))
    _, audit = outcome.audit(args.baseline)
    if audit["failures"]:
        raise ValueError("Outcome-phase audit failed; no inference started")
    cargs = SimpleNamespace(baseline=args.baseline, upstream=args.upstream,
                           output=base.ROOT / "derivatives/fsl/randomise/katie-main-effects-v1",
                           report=base.ROOT / "results/randomise/katie-main-effects-v1", jobs=min(16, args.jobs))
    cargs.output.parent.mkdir(parents=True, exist_ok=True)
    conditional.build(cargs)
    main_plan = conditional.check(cargs)
    _, pairs = base.cohort.read_table(base.ROOT / "data/derived/katie-cohort-v1/selected_pairs.tsv")
    activation = build_group(args, baseline, pairs)
    units = ppi_definitions(args, pairs)
    frozen = args.output / "source-plan.json"
    source_plan = dict(baseline=base.fingerprint(args.baseline / "plan.json"), code=base.fingerprint(Path(__file__)), units=units,
                       task_code=[base.fingerprint(Path(p)) for p in units[0]["files"]], jobs_cap=args.jobs)
    if frozen.exists():
        saved = json.loads(frozen.read_text())
        if {k: v for k, v in saved.items() if k != "jobs_cap"} != {k: v for k, v in source_plan.items() if k != "jobs_cap"}:
            raise ValueError("Saved remaining-analysis inputs/code changed")
    else:
        base.write_json(frozen, source_plan)
    if getattr(args, "prepare_only", False):
        print("CHECK PASSED: N=97; 16 conditional and 8 activation jobs prepared; 194 existing VS-PPI units inventoried "
              "for compatible reuse or isolated no-TEDANA rebuild, followed by 24 connectivity jobs. No inference started.", flush=True)
        return
    # Native smoke gates run before expensive inference; the task intercept must
    # use sign flips, never permutations of an invariant group mean.
    conditional.execute(main_plan, main_plan["jobs"][0], cargs.output / "smoke", base.cohort.digest(cargs.output / "plan.json"), smoke=True)
    group_root = args.output / "activation"
    base.execute(activation, next(j for j in activation["jobs"] if j["outcome"] == "average"), group_root / "smoke",
                 base.cohort.digest(group_root / "plan.json"), smoke=True)
    smoke_receipt = json.loads((group_root / "smoke/success.json").read_text())
    smoke_text = (Path(smoke_receipt["attempt"]) / "console.log").read_text().lower()
    if "sign-flipping" not in smoke_text and "sign flipping" not in smoke_text:
        raise ValueError("Group-mean smoke did not confirm sign flipping; no full jobs launched")
    print(f"SMOKE PASSED: conditional effects and covariate-adjusted group mean; sign flipping confirmed. MAX WORKERS={args.jobs}", flush=True)
    outcomes, failures, ppi_done = {}, {}, 0
    connectivity = None
    state_path = args.output / "status.json"
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {}
        def submit(kind, key, function, *arguments):
            futures[pool.submit(function, *arguments)] = (kind, key)
        for job in main_plan["jobs"]:
            submit("conditional", job["key"], conditional.execute, main_plan, job, cargs.output / "jobs" / job["key"],
                   base.cohort.digest(cargs.output / "plan.json"))
        for job in activation["jobs"]:
            submit("activation", job["key"], base.execute, activation, job, group_root / "jobs" / job["key"],
                   base.cohort.digest(group_root / "plan.json"))
        for unit in units:
            submit("ppi_l1", unit["key"], ppi_unit, args, unit)
        print("STARTED: 16 conditional + 8 activation randomise jobs; 194 PPI units queued for reuse or isolated no-TEDANA rebuild.", flush=True)
        while futures:
            done, _ = wait(futures, timeout=60, return_when=FIRST_COMPLETED)
            if not done:
                print(f"HEARTBEAT finished={len(outcomes)} pending_or_running={len(futures)} PPI_units={ppi_done}/194", flush=True)
            for future in done:
                kind, key = futures.pop(future)
                label = kind + "/" + key
                try:
                    result = future.result()
                    if result == "NOT_STARTED": raise InterruptedError("Stopped before launch")
                    outcomes[label] = result
                except Exception as exc:
                    failures[label] = str(exc); outcomes[label] = "FAILED"
                if kind == "ppi_l1": ppi_done += 1
                print(f"{outcomes[label]} {label}" + (": " + failures[label] if label in failures else ""), flush=True)
            if ppi_done == 194 and connectivity is None and not any(k.startswith("ppi_l1/") for k in failures) and not base.STOP:
                try:
                    connectivity = build_ppi_group(args, baseline, units)
                    root = args.output / "connectivity"
                    base.execute(connectivity, connectivity["jobs"][0], root / "smoke", base.cohort.digest(root / "plan.json"), smoke=True)
                    print("PPI SMOKE PASSED: 24 connectivity randomise jobs now queued, same 97-person order.", flush=True)
                    for job in connectivity["jobs"]:
                        submit("connectivity", job["key"], base.execute, connectivity, job, root / "jobs" / job["key"], base.cohort.digest(root / "plan.json"))
                except Exception as exc:
                    failures["connectivity/preparation"] = str(exc)
                    print("FAILED connectivity/preparation: " + str(exc), flush=True)
                    connectivity = False
            base.write_json(state_path, dict(status="running", max_workers=args.jobs, n=97,
                            outcomes=outcomes, failures=failures, ppi_units_finished=ppi_done,
                            randomise_total_expected=48, original_24_jobs_repeated=False))
    # Independent branches are reported even if another branch needs a retry.
    for kind, plan, root, report in (("activation", activation, group_root, args.report / "activation"),
                                    ("connectivity", connectivity, args.output / "connectivity", args.report / "connectivity")):
        if plan and not any(k.startswith(kind + "/") for k in failures):
            try: report_batch(plan, root, report)
            except Exception as exc: failures[kind + "/verification"] = str(exc)
    if not any(k.startswith("conditional/") for k in failures):
        try: conditional.check_results(cargs)
        except Exception as exc: failures["conditional/verification"] = str(exc)
    if base.STOP:
        failures["coordinator/stop"] = "Stopped; completed outputs and partial attempts preserved"
    completed_randomise = sum(label.split("/", 1)[0] in ("conditional", "activation", "connectivity")
                             and result in ("COMPLETED", "REUSED") for label, result in outcomes.items())
    if not failures and completed_randomise != 48:
        failures["coordinator/count"] = f"Expected 48 verified randomise jobs, found {completed_randomise}"
    try:
        base.verify_sources(baseline["sources"] + [source_plan["code"], source_plan["baseline"], *source_plan["task_code"]])
    except Exception as exc:
        failures["coordinator/source_checks"] = str(exc)
    base.write_json(state_path, dict(status="failed" if failures else "complete", max_workers=args.jobs, n=97,
                    outcomes=outcomes, failures=failures, ppi_units_finished=ppi_done, randomise_total_expected=48))
    if failures or base.STOP:
        raise RuntimeError("Some branches need attention; completed outputs preserved. See " + str(state_path))
    print("CHECK PASSED: 48 additional randomise jobs verified (16 conditional, 8 group activation, 24 VS PPI); "
          "N=97; original results/exclusions unchanged; no-TEDANA PPI lineage verified.", flush=True)


def main():
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=base.ROOT / "derivatives/fsl/randomise/katie-v1")
    parser.add_argument("--output", type=Path, default=base.ROOT / "derivatives/fsl/randomise/katie-remaining-v1")
    parser.add_argument("--report", type=Path, default=base.ROOT / "results/randomise/katie-remaining-v1")
    parser.add_argument("--upstream", type=Path, default=Path("/ZPOOL/data/projects/rf1-sra-linux2"))
    parser.add_argument("--task-project", type=Path, default=Path("/ZPOOL/data/projects/rf1-sra-socdoors"))
    parser.add_argument("--jobs", type=int, default=48)
    parser.add_argument("--prepare-only", action="store_true", help="Freeze/check inputs without running FSL or randomise")
    args = parser.parse_args()
    for name in ("baseline", "output", "report", "upstream", "task_project"):
        setattr(args, name, getattr(args, name).resolve())
    if not 1 <= args.jobs <= 48: parser.error("--jobs must be 1..48")
    if args.output == args.baseline or args.baseline in args.output.parents or args.output in args.baseline.parents:
        parser.error("Use an isolated output root")
    args.output.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, base.stop); signal.signal(signal.SIGINT, base.stop)
    locks = []
    try:
        # Same locks as standalone runners, plus the overall remaining-work lock.
        for path in (args.output.parent / ".katie-remaining-v1.lock", args.output.parent / ".katie-main-effects-v1.lock",
                     args.baseline.parent / ".katie-v1.lock"):
            lock = path.open("a"); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); locks.append(lock)
        base.LEASE_FD = locks[0].fileno()
        run(args)
    finally:
        for lock in locks: lock.close()


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print(f"FAILED ({type(exc).__name__}): {exc}", file=sys.stderr, flush=True); sys.exit(1)
