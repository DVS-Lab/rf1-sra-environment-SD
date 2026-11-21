import csv
from hashlib import sha256
from pathlib import Path
import unittest
from xml.etree import ElementTree

import nibabel as nib
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
KIT=ROOT/"publication/manuscript-figures"
OLD=ROOT/"publication/figures-v1"

def table(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

class ManuscriptKit(unittest.TestCase):
    def test_matches_supplied_artwork(self):
        # SHA-256 of embedded images in the authors' November 17 Results and supplement.
        exact={
            "Figure-1":"560d45ab391f81150f417f23b23d550841d47a5187f3669c32961188f211087c",
            "Figure-2":"da10e327df78528d60ff57cb390c65e6e81432435256e94cc31d7c1b6dd98b0c",
            "supplement/Figure-S1":"cc14fe9a80da24d524f61b449ee608ae71da8fe51f8de297a105946c74bb3c99",
            "supplement/Figure-S3":"277a420223d25f246369b07fccbce300f60f81a76736d81911ad353201cb6707",
        }
        for folder,digest in exact.items():
            p=KIT/folder/(Path(folder).name+".png")
            self.assertEqual(sha256(p.read_bytes()).hexdigest(),digest)
        self.assertEqual(sorted(p.name for p in KIT.glob("Figure-*")),["Figure-1","Figure-2","Figure-3"])

    def test_plotted_estimands(self):
        linear=[r for r in table(OLD/"sources/fig1/behavior_curves.tsv") if r["model"]=="linear"]
        self.assertEqual(table(KIT/"Figure-1/plotted-values.tsv"),linear)
        curve=table(KIT/"Figure-2/plotted-values.tsv")
        self.assertEqual({r["component"] for r in curve},{"difference"})
        x=np.array([float(r["support"]) for r in curve])
        self.assertEqual(len(x),201)
        for r in table(KIT/"Figure-2/published-anchors.tsv"):
            for k in ("slope","hc3_lower","hc3_upper"):
                interp=np.interp(float(r["moderator"]),x,[float(s[k]) for s in curve])
                self.assertAlmostEqual(interp,float(r[k]),delta=.0002)
        row,=table(KIT/"Figure-3/plotted-values.tsv")
        self.assertEqual((row["component"],row["n"]),("difference","97"))
        np.testing.assert_allclose([float(row[k]) for k in ("beta","hc3_lower","hc3_upper")],
                                   [-.1102317465,-.1545528240,-.0659106691],atol=1e-8)
        self.assertFalse(list((KIT/"Figure-1").glob("*.nii.gz")))

    def test_maps_are_colocated_validated_native_images(self):
        for folder,old_prefix,size,sign in [("Figure-2","Fig3_",87,1),("Figure-3","Fig2_",44,-1),
                                            ("supplement/Figure-S3","Fig3_",87,1)]:
            p=KIT/folder
            row,=table(p/"map-index.tsv")
            files=[]
            for suffix in ("mask","signed-t"):
                fname=f"{row['stem']}_{suffix}.nii.gz"
                self.assertEqual((p/fname).read_bytes(), (OLD/"group-maps"/(old_prefix+fname)).read_bytes())
                files.append(nib.load(p/fname))
            mask,tmap=files
            np.testing.assert_array_equal(mask.affine,tmap.affine)
            region=mask.get_fdata()>0
            self.assertEqual(region.sum(),size)
            signed=tmap.get_fdata()*sign
            np.testing.assert_array_equal(signed>0,region)
            xyz=nib.affines.apply_affine(mask.affine,np.unravel_index(signed.argmax(),signed.shape))
            np.testing.assert_allclose(xyz,[float(n) for n in row["peak_mni_mm"].split(",")],atol=1e-5)

    def test_figure3_shows_sealed_adjusted_scatter_not_coefficient(self):
        f3=KIT/"Figure-3"
        validated=ROOT/"results/review/fevs-vs-v1/fevs-vs-cluster-1-scatter.png"
        self.assertEqual(sha256(validated.read_bytes()).hexdigest(),
                         "35ffad74513bd82c3a5212b4c90910b46f6de9fd9c237f5ab1873b9fe2a7d862")
        with Image.open(validated) as source, Image.open(f3/"adjusted-scatter.png") as panel:
            np.testing.assert_array_equal(source.convert("RGB").crop((744,128,1415,578)),panel)
        svg=ElementTree.parse(f3/"Figure-3.svg")
        self.assertEqual(len(svg.findall(".//{http://www.w3.org/2000/svg}image")),2)
        self.assertIn("Financial exploitation vulnerability (FEVS score)"," ".join(svg.getroot().itertext()))

if __name__=="__main__":
    unittest.main()
