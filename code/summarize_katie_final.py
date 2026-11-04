"""Reconcile published aggregate results; never read or modify native images."""

import argparse
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess


LOG_REF = "6df2ff91"
STATUS_LOG = "logs/records/20261103-201516_reward-extension-status-20261103-201516.md"
RESULTS_LOG = "logs/records/20261103-201516_reward-extension-status-20261103-201516-results.md"
EXPECTED = {
    ("activation", "social_specific"): (168, 0),
    ("activation", "average"): (160, 3),
    ("activation", "win_only"): (168, 5),
    ("activation", "loss_only"): (168, 4),
    ("connectivity", "social_specific"): (168, 17),
    ("connectivity", "average"): (160, 19),
    ("connectivity", "win_only"): (168, 7),
    ("connectivity", "loss_only"): (168, 14),
}
LABELS = {
    "social_specific": "(Social win-loss) - (Doors win-loss)",
    "average": "Average win-loss across domains",
    "win_only": "Social win - Doors win",
    "loss_only": "Social loss - Doors loss",
}
FIELDS = ("family", "outcome", "model", "term", "direction", "z", "n",
          "min_cluster_fwe_p", "significant_voxels", "significant_clusters", "source")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_after(text, marker):
    tail = text.split(marker, 1)[1].lstrip()
    return json.JSONDecoder().raw_decode(tail)[0]


def token(row):
    return tuple(str(row[k]) for k in ("family", "outcome", "model", "term", "direction")) + (float(row["z"]),)


def reconcile(old_maps, preview, snapshot, catalog):
    if (preview["n"], preview["completed_jobs"], preview["pending_jobs"],
            preview["verified_completed_maps"], preview["preliminary"]) != (97, 220, 0, 996, False):
        raise ValueError("Final extension preview is incomplete")
    if (snapshot["recorded_status"] != "complete" or not snapshot["recorded_validated"]
            or snapshot["recorded_failures"] or snapshot["invalid_job_keys"]
            or snapshot["outcome_counts"] != {"COMPLETED": 220}):
        raise ValueError("Final state has unresolved jobs or failed validation")
    validation = snapshot["recorded_final_validation"]
    if (validation["directional_tests"] != 1328 or validation["n"] != 97
            or validation["original_results_changed"] or validation["exclusions_changed"]):
        raise ValueError("Frozen cohort or result catalog changed")
    totals = {(r["family"], r["outcome"]): r["total_maps"] for r in catalog["summary"]}
    if catalog["rows"] != 1328 or totals != {key: value[0] for key, value in EXPECTED.items()}:
        raise ValueError("Final catalog coverage differs")

    rows = []
    for source, source_rows in (("retained_review", old_maps), ("extension_preview", preview["corrected_findings"])):
        for row in source_rows:
            if source == "retained_review" and row["batch"] == "group_activation":
                continue
            if float(row["min_cluster_fwe_p"]) >= .05:
                continue
            if int(row["n"]) != 97 or int(row["significant_voxels"]) <= 0:
                raise ValueError("Invalid corrected map")
            cleaned = {field: row[field] for field in FIELDS if field != "source"}
            cleaned["z"] = float(cleaned["z"])
            cleaned["source"] = source
            rows.append(cleaned)
    if len({token(row) for row in rows}) != len(rows):
        raise ValueError("Duplicate scientific map")
    observed = Counter((r["family"], r["outcome"]) for r in rows)
    if any(observed[key] != value[1] for key, value in EXPECTED.items()) or len(rows) != 69:
        raise ValueError("Corrected map counts do not reconcile")
    if {token(r) for r in catalog["new_corrected_findings"]} != {token(r) for r in preview["corrected_findings"]}:
        raise ValueError("Snapshot and hash-verified preview disagree")
    return sorted(rows, key=lambda r: (r["family"], r["outcome"], r["model"], r["term"], r["z"], r["direction"]))


def verify_reports(project):
    records = {}
    for name in ("katie-review-v1", "fevs-win-v1", "fevs-vs-v1", "reward-followup-v1"):
        root = project / "results/review" / name
        manifest = json.loads((root / "review_manifest.json").read_text())
        if manifest["n"] != 97 or manifest["exclusions_changed"]:
            raise ValueError("Curated report changed cohort")
        for relative, expected in manifest["outputs"].items():
            path = root / relative
            actual = digest(path.read_bytes())
            if actual != expected:
                raise ValueError(f"Report fingerprint differs: {path}")
            records[str(path.relative_to(project))] = actual
        records[str((root / "review_manifest.json").relative_to(project))] = digest((root / "review_manifest.json").read_bytes())
    return records


def plot_counts(path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    outcomes = list(LABELS)
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.8), sharex=True, sharey=True)
    for axis, family, title, color in zip(axes, ("activation", "connectivity"),
                                         ("Activation", "VS task-modulated connectivity"),
                                         ("#007f85", "#a73958")):
        values = [EXPECTED[(family, outcome)][1] for outcome in outcomes]
        axis.barh(range(4), values, color=color, height=.58)
        axis.set_yticks(range(4), [LABELS[outcome] for outcome in outcomes], fontsize=10)
        for i, (outcome, value) in enumerate(zip(outcomes, values)):
            axis.text(value + .3, i, f"{value} / {EXPECTED[(family, outcome)][0]}", va="center", fontsize=11)
        axis.set_xlim(0, 23)
        axis.set_title(title, fontsize=13)
        axis.set_xlabel("Maps with at least one cluster-FWE p < .05 cluster")
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(axis="x", alpha=.15)
        axis.set_axisbelow(True)
    axes[0].invert_yaxis()
    fig.suptitle("Final N=97 catalog: 1,328 maps; not 1,328 independent tests", fontsize=15)
    fig.text(.5, .025, "Counts include both directions and CDTs. Per-map correction only; overlapping results are not independent discoveries.",
             ha="center", fontsize=10)
    fig.tight_layout(rect=(0, .07, 1, .93))
    fig.savefig(path, dpi=160)
    plt.close(fig)


def build(project, logs_repo, ref, output):
    revision = subprocess.check_output(["git", "rev-parse", f"{ref}^{{commit}}"], cwd=logs_repo, text=True).strip()
    logs = {name: subprocess.check_output(["git", "show", f"{revision}:{name}"], cwd=logs_repo) for name in (STATUS_LOG, RESULTS_LOG)}
    if any(b"- Command exit: 0\n" not in data for data in logs.values()):
        raise ValueError("Published extraction did not succeed")
    status = logs[STATUS_LOG].decode()
    start = logs[RESULTS_LOG].decode().index('{\n  "available"')
    preview = json.JSONDecoder().raw_decode(logs[RESULTS_LOG].decode()[start:])[0]
    snapshot = json_after(status, "=== katie-reward-extension-v1 ===")
    catalog = json_after(status, "=== Final result-table summary ===")
    source = project / "results/review/katie-review-v1/maps.tsv"
    with source.open() as stream:
        old = list(csv.DictReader(stream, delimiter="\t"))
    rows = reconcile(old, preview, snapshot, catalog)
    fingerprints = verify_reports(project)
    fingerprints[str(source.relative_to(project))] = digest(source.read_bytes())
    output.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    (output / "corrected_maps.tsv").write_text(stream.getvalue())
    plot_counts(output / "map_counts.png")
    provenance = dict(n=97, extension_jobs=220, catalog_maps=1328, corrected_maps=69,
                      source_log_commit=revision, logs={p: digest(b) for p, b in logs.items()},
                      curated_report_fingerprints=fingerprints, exclusions_changed=False,
                      new_inference=False, native_images_inspected=False,
                      scope="Published aggregate reconciliation, not a new Linux2 native-image integrity audit",
                      builder_sha256=digest(Path(__file__).read_bytes()))
    provenance["outputs"] = {name: digest((output / name).read_bytes()) for name in ("corrected_maps.tsv", "map_counts.png")}
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    print("VERIFIED: 69 corrected maps reconcile across all eight final categories; curated report hashes match. No analyses changed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--logs-repo", type=Path, required=True)
    parser.add_argument("--log-ref", default=LOG_REF)
    args = parser.parse_args()
    build(args.project, args.logs_repo, args.log_ref, args.project / "results/review/final-summary-v1")


if __name__ == "__main__":
    main()
