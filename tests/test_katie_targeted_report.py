"""Use aggregate fixtures to check reporting without Linux2 or statistical software."""
from itertools import combinations
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfReader

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"code"))
import build_katie_targeted_report as report


def fixture():
    """Use published counts for a realistic layout; simulated overlaps are not results."""
    import csv
    b=report.read(report.REVIEW/"katie-targeted-behavior-v1/behavior.json")
    fixed=report.read(report.REVIEW/"fevs-vs-fixed-roi-mspss-v1/summary.json")
    alt = report.REVIEW/"katie-results-ready-v1"
    with (alt/"scientific_clusters.tsv").open() as stream:
        rows=[r for r in csv.DictReader(stream,delimiter="\t") if r["term"]=="adixecog" and r["family"]=="connectivity"]
    clusters = [dict(id=f"C{i+1:02d}",outcome=r["outcome"],z=float(r["z"]),direction=r["direction"],
        peak=[float(r[f"peak_{a}_mm"]) for a in "xyz"], voxels=int(r["voxels"]),p=float(r["cluster_fwe_p_min"]),
        atlas=[dict(peak_label="Synthetic layout-only label")],max_cooks_d=.41,loo_beta_min=-.4,loo_beta_max=-.12)
        for i,r in enumerate(rows)]
    map_overlap=[dict(outcome_a=a[0],z_a=a[1],outcome_b=b[0],z_b=b[1],shared_voxels=0,voxels_a=250,voxels_b=50,dice=.0)
                 for a,b in combinations([(o,z) for o in report.LABELS for z in (2.6,3.1)],2)]
    fits=[dict(component=name,beta=val,hc3_lower=val-.1,hc3_upper=val+.1,max_cooks_d=.4,
               n_cooks_above_4_over_n=4,loo_beta_min=val-.03,loo_beta_max=val+.03)
          for name,val in (("socialdoors",.107),("doors",-.264),("difference",.371))]
    group=[dict(z=z,direction=s,shared_voxels=0,dice=0.) for z in (2.6,3.1) for s in ("positive","negative","either")]
    n=dict(activation=dict(fits=fits,support=b["tails"],group_overlap=group),
           vs=dict(clusters=clusters,map_overlap=map_overlap))
    figs = dict(behavior=report.REVIEW/"katie-targeted-behavior-v1/behavior.png",
        activation=alt/"figure-3-adi-support-conditional.png",
        activation_brain=alt/"figure-3-adi-support-brain.png",
        overlap=alt/"adi-support-influence.png")
    return b,n,fixed,figs


class Report(unittest.TestCase):
    def test_four_question_pages_without_manuscript_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"SYNTHETIC_LAYOUT_TEST.pdf"
            report.make_pdf(path,*fixture())
            pages=PdfReader(path).pages
            self.assertEqual(len(pages),4)
            for i,key in enumerate(("high-support reversal","ADI-by-support contrast","same locations recur","move into the paper")):
                self.assertIn(key,pages[i].extract_text())
            self.assertIn("No manuscript Results text is drafted",pages[-1].extract_text())
            self.assertIn("does not rescue",pages[-1].extract_text())

    def test_missing_native_evidence_never_becomes_a_result(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(report,"REVIEW",Path(tmp)):
            with self.assertRaises(FileNotFoundError):
                report.load_evidence()

    def test_contrasts_and_signs_not_collapsed_in_interpretation(self):
        _,n,_,_=fixture()
        self.assertIn("Opposite signs",report.activation_conclusion(n["activation"]["fits"]))
        self.assertIn("no corrected voxels",report.vs_conclusion(n["vs"]))
        matched=next(r for r in n["vs"]["map_overlap"] if {r["outcome_a"],r["outcome_b"]}=={"social_specific","loss_only"} and r["z_a"]==r["z_b"])
        matched["shared_voxels"]=10
        matched["dice"]=.0667
        self.assertIn("threshold-dependent",report.vs_conclusion(n["vs"]))


if __name__=="__main__":
    unittest.main()
