import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import build_katie_results_ready as report


class ResultsReady(unittest.TestCase):
    def test_corrected_inventory_and_failed_support_sensitivity_are_retained(self):
        summary,inventory,sources=report.verified_inputs()
        self.assertEqual(len(inventory),1328)
        self.assertEqual(sum(r['source_status']=='corrected_MSPSS' for r in inventory),384)
        self.assertEqual(sum(int(r['significant_clusters'])>0 for r in inventory),71)
        adjusted=[r for r in summary['vs_support_sensitivity']['maps'] if r['adjustment']=='add_mspss']
        self.assertEqual(len(adjusted),4)
        self.assertTrue(all(int(r['significant_clusters'])==0 for r in adjusted))
        self.assertIn('results/review/mspss-corrected-v1/maps.tsv',sources)

    def test_changed_corrected_scores_cannot_enter_report(self):
        _,_,sources=report.verified_inputs()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in sources:
                destination=root/name;destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(report.ROOT/name,destination)
            # Change a real corrected-score cell while retaining its roster and receipt.
            path=root/'data/derived/mspss-correction-v1/screener_scores.tsv'
            lines=path.read_text().splitlines();parts=lines[1].split('\t')
            parts[1]='1.12345';lines[1]='\t'.join(parts);path.write_text('\n'.join(lines)+'\n')
            with self.assertRaisesRegex(ValueError,'Corrected score seal'):
                report.verified_inputs(root)

    def test_descriptive_correlations_use_corrected_not_historical_support(self):
        import numpy as np
        import run_behavioral_moderation as behavior
        _,values=behavior.inputs(report.ROOT)
        rows,_=report.corrected_correlations()
        result=next(r for r in rows if (r['variable_1'],r['variable_2'])==('fevs','mspss'))
        self.assertEqual(len(rows),15)
        self.assertAlmostEqual(result['pearson_r'],-.2869015705012261)
        self.assertGreater(abs(result['pearson_r']-np.corrcoef(values['fevs'],values['mspss'])[0,1]),.03)
        self.assertTrue(all(r['n']==97 and r['mspss_administration']=='corrected_island_screener' for r in rows))

    def test_final_pdf_pages_conclusions_and_privacy(self):
        import fitz
        doc=fitz.open(report.PDF);record=report.load(report.PACKAGE/'analysis-record.json')
        self.assertEqual(len(doc),record['report_pages'])
        texts=[' '.join(p.get_text().split()) for p in doc];all_text=' '.join(texts)
        for section in report.SECTIONS:self.assertIn(section,all_text)
        for needle in ('Holm p=.000509','.0751','.1021','87 voxels','protective buffering','1,328','384'):
            self.assertIn(needle,all_text)
        self.assertNotIn('More Consistent Across Adjustments',all_text)
        self.assertNotIn('-.802238',all_text)
        for page,text in zip(doc,texts):
            self.assertIn('N=97',text);self.assertIn('EXPLORATORY',text)
            for block in page.get_text('dict')['blocks']:
                if 'lines' not in block:continue
                for line in block['lines']:
                    for span in line['spans']:
                        x0,y0,x1,y1=span['bbox']
                        self.assertGreaterEqual(x0,35)
                        self.assertLessEqual(x1,756)
                        self.assertGreaterEqual(y0,26)
                        self.assertLessEqual(y1,598)
        import re
        ids=[r['subject'] for r in report.old.rows(report.ROOT/'data/derived/katie-cohort-v1/subjects.tsv')]
        for subject in ids:self.assertIsNone(re.search(r'\b'+re.escape(subject)+r'\b',all_text))
        self.assertGreaterEqual(len(doc.get_toc()),6)
        doc.close()

    def test_delivered_package_seals_and_complete_null_tables(self):
        manifest=report.load(report.PACKAGE/'report-manifest.json')
        self.assertEqual(manifest['n'],97)
        for name,sha in manifest['outputs'].items():self.assertEqual(report.old.digest(report.ROOT/name),sha,name)
        for name,sha in manifest['source_files'].items():self.assertEqual(report.old.digest(report.ROOT/name),sha,name)
        groups=report.old.rows(report.PACKAGE/'model-null-inventory.tsv')
        self.assertEqual(len(groups),134)
        self.assertEqual(sum(int(r['maps']) for r in groups),1328)
        self.assertTrue(any(int(r['maps_with_clusters'])==0 for r in groups))
        allowed={'.md','.json','.png','.tsv'}
        self.assertTrue(all(p.suffix in allowed for p in report.PACKAGE.iterdir()))
        self.assertTrue(all('subject' not in report.old.rows(p)[0] for p in report.PACKAGE.glob('*.tsv')))


if __name__=='__main__':unittest.main()
