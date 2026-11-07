#!/usr/bin/env python3
"""Build the final evidence report from sealed corrected outputs; never run inference.

Uses the existing report builders' digest/table helpers and landscape evidence
layout. Deliberately does not invoke their historical MSPSS verification gates.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
from xml.sax.saxutils import escape

import build_fevs_results_pdf as old

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / 'results/review'
EVIDENCE = REVIEW / 'katie-closeout-analysis-v1'
PACKAGE = REVIEW / 'katie-results-ready-v1'
PDF = ROOT / 'output/pdf/FEVS_Results_Ready_2026-11-07.pdf'
DATE = 'November 7, 2026'
SECTIONS = (
    '1. Environmental stressors, social support, and financial vulnerability',
    '2. Financial vulnerability and neural reward processing',
    '3. Environmental stressors and neural reward processing',
)
CORRECTED_SHA = 'ac5a9599d21ff1b86626a6d44824867f0b43fd1728d7377d991cadb9e1686889'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    return json.loads(Path(path).read_text())


def tsv(path, rows, fields=None):
    import csv
    rows = list(rows)
    with Path(path).open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]), delimiter='\t', lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False)+'\n')


def catalog_key(row):
    return tuple(row[k].split('/')[-1] if k == 'outcome' else str(float(row[k])) if k == 'z' else row[k]
                 for k in ('family', 'outcome', 'model', 'term', 'direction', 'z'))


def verified_inputs(root=ROOT):
    review = root / 'results/review'
    sources = {}
    def record(path):
        sources[str(path.relative_to(root))] = old.digest(path)
    for name in ('katie-closeout-analysis-v1', 'behavioral-mspss-corrected-provisional-v1',
                 'fevs-win-v1', 'fevs-vs-v1', 'fevs-imaging-adjustments-provisional-v1',
                 'fevs-adjustment-maps-v1', 'katie-evidence-v1', 'reward-followup-v1'):
        folder = review / name
        manifest = load(folder / 'review_manifest.json')
        require(manifest['n'] == 97 and not manifest.get('exclusions_changed', False), 'Cohort/exclusions changed')
        record(folder / 'review_manifest.json')
        for name, expected in manifest['outputs'].items():
            path = folder / name
            require(not Path(name).is_absolute() and '..' not in Path(name).parts and
                    not path.is_symlink() and old.digest(path) == expected, 'Published evidence changed: '+str(path))
            record(path)
    for relative in ('config/analysis_decisions.json', 'config/katie_results_closeout_v1.json',
                     'data/derived/mspss-correction-v1/provenance.json', 'data/derived/mspss-correction-v1/screener_scores.tsv',
                     'results/review/mspss-corrected-v1/provenance.json', 'results/review/mspss-corrected-v1/maps.tsv',
                     'results/review/mspss-corrected-v1/clusters.tsv', 'results/review/katie-review-v1/region_fits.json',
                     'results/review/katie-review-v1/clusters.tsv', 'results/review/katie-review-v1/vs_group_response.tsv',
                     'results/review/task-event-audit-summary-8bd32f07632e/summary.json',
                     'results/review/final-summary-v1/provenance.json', 'results/review/final-summary-v1/corrected_maps.tsv'):
        record(root / relative)
    correction = load(root / 'data/derived/mspss-correction-v1/provenance.json')
    require(correction['scores_sha256'] == CORRECTED_SHA == old.digest(root / 'data/derived/mspss-correction-v1/screener_scores.tsv'), 'Corrected score seal differs')
    summary = load(review / 'katie-closeout-analysis-v1/summary.json')
    require(summary['n'] == 97 and not summary['cohort_changed'] and not summary['exclusions_changed'], 'Closeout cohort differs')
    require(summary['vs_support_sensitivity']['new_jobs'] == 2 and summary['new_sensitivity_maps'] == 4, 'New inference scope differs')
    inventory = old.rows(review / 'katie-closeout-analysis-v1/scientific_inventory.tsv')
    require(len(inventory) == len({catalog_key(r) for r in inventory}) == 1328, 'Canonical coverage differs')
    require(sum(int(r['significant_clusters']) > 0 for r in inventory) == 71, 'Corrected passing-map count differs')
    historical = {catalog_key(r): r for r in old.rows(review / 'final-summary-v1/corrected_maps.tsv')}
    corrected = {catalog_key(r): r for r in old.rows(review / 'mspss-corrected-v1/maps.tsv')}
    require(len(historical) == 69 and len(corrected) == 384, 'Source catalogs incomplete')
    require({catalog_key(r) for r in inventory if 'mspss' not in r['model'] and int(r['significant_clusters'])} ==
            {key for key, r in historical.items() if 'mspss' not in r['model']}, 'Retained passing-map coverage differs')
    for row in inventory:
        key = catalog_key(row)
        require((row['source_status'] == 'corrected_MSPSS') == ('mspss' in row['model']), 'Historical support result substituted')
        if 'mspss' not in row['model'] and key not in historical:
            continue  # Null-map preservation is established by the sealed Linux2 native audit.
        source = corrected[key] if 'mspss' in row['model'] else historical[key]
        for field in ('min_cluster_fwe_p', 'significant_voxels', 'significant_clusters'):
            require(float(row[field]) == float(source[field]), 'Canonical replacement differs: '+field)
    target = summary['behavior']['published_interaction']
    require(abs(float(target['interaction_beta']) + .9888250699391419) < 1e-12, 'Historical behavioral estimate substituted')
    require(abs(float(target['holm_family_p']) - .0005090391850966116) < 1e-12, 'Corrected Holm value differs')
    maps = summary['vs_support_sensitivity']['maps']
    require(len(maps) == 8 and sum(r['adjustment'] == 'add_mspss' for r in maps) == 4, 'Sensitivity inventory incomplete')
    require(all(int(r['n']) == 97 for r in maps), 'Sensitivity N differs')
    require(all(int(r['significant_clusters']) == 0 for r in maps if r['adjustment'] == 'add_mspss'), 'Sensitivity conclusion requires revision')
    for z, expected in ((2.6, .1021), (3.1, .0751)):
        row = next(r for r in maps if r['adjustment'] == 'add_mspss' and r['direction'] == 'negative' and float(r['z']) == z)
        require(abs(float(row['min_cluster_fwe_p'])-expected) < 1e-6, 'Adjusted result differs')
    require(summary['adi_support']['cluster']['voxels'] == 87 and summary['vs_components']['cluster']['voxels'] == 44, 'Selected regions differ')
    fits = summary['vs_components']['fits']
    require(abs(fits['socialdoors']['beta']-fits['doors']['beta']-fits['difference']['beta']) < 1e-7, 'Component decomposition differs')
    return summary, inventory, sources


def corrected_correlations(root=ROOT):
    """Descriptive Pearson/Spearman only; no tests or new regression specifications."""
    import numpy as np
    from scipy.stats import rankdata
    import run_behavioral_moderation as behavior
    ids, values = behavior.inputs(root)
    rows = old.rows(root / 'data/derived/mspss-correction-v1/screener_scores.tsv')
    require([r['subject'] for r in rows] == ids, 'Corrected support row order differs')
    values['mspss'] = np.array([float(r['mspss']) for r in rows])
    require(values['mspss'].shape == (97,) and np.isfinite(values['mspss']).all() and
            values['mspss'].min() >= 1 and values['mspss'].max() <= 7, 'Corrected range differs')
    names = ['fevs', 'oafem', 'adi', 'pm25', 'mspss', 'ecog']
    result = []
    for i, a in enumerate(names):
        for b in names[i+1:]:
            result.append(dict(variable_1=a, variable_2=b, n=97,
                pearson_r=float(np.corrcoef(values[a], values[b])[0,1]),
                spearman_rho=float(np.corrcoef(rankdata(values[a]), rankdata(values[b]))[0,1]),
                mspss_administration='corrected_island_screener'))
    sources = {p: old.digest(root/p) for p in (behavior.SCORE_FILE, behavior.ROSTER, behavior.VARIABLES,
               behavior.SOURCE_RECEIPT, behavior.POLICY, 'code/run_behavioral_moderation.py', 'code/freeze_katie_cohort.py')}
    return result, sources


def p(value): return f'{float(value):.4f}'
def f(value): return f'{float(value):.3f}'
def interval(row, prefix='hc3_'): return f"[{f(row[prefix+'lower'])}, {f(row[prefix+'upper'])}]"
def coord(row): return ', '.join(f'{float(row[k]):.1f}' for k in ('peak_x_mm','peak_y_mm','peak_z_mm'))
def model_label(value):
    return value.replace('pm25_ecog_additive', 'PM2.5 + ECog').replace('mspss','MSPSS').replace('oafem','OAFEM').replace('fevs','FEVS').replace('pm25','PM2.5').replace('ecog','ECog').replace('adi','ADI').replace('x',' × ')
OUTCOMES = {'win_only':'Winning', 'loss_only':'Losing', 'social_specific':'Domain × valence', 'average':'Task mean'}


def principal_evidence(summary, inventory):
    def neural(family, outcome, model, term, direction, z=3.1):
        return next(r for r in inventory if (r['family'],r['outcome'],r['model'],r['term'],r['direction'],float(r['z'])) == (family,outcome,model,term,direction,z))
    act = neural('activation','win_only','fevsxpm25','fevs','positive')
    adi = summary['adi_support']['cluster']; vs = summary['vs_components']['cluster']
    rows = [
      dict(question=1, outcome='FEVS', coefficient='PM2.5 × corrected MSPSS', direction='negative', estimate=f(summary['behavior']['beta']),
           location='Behavioral; not applicable', corrected_p=p(summary['behavior']['published_interaction']['holm_family_p']), correction='Holm, two primary tests', sensitivity='HC3 b=-0.989; +ADI -0.990; +ECog -0.883; +both -0.879; all CIs exclude zero'),
      dict(question=2, outcome='Social win − nonsocial win activation',coefficient='FEVS at mean PM2.5',direction='positive',estimate='67 voxels',
           location='MNI (-31.6, 49.5, -3.7); atlas white-matter overlap',corrected_p=p(act['min_cluster_fwe_p']),correction='Cluster-FWE per map, CDT 3.1',sensitivity='+ECog p=.0505; +both .0477; standalone +ECog .0666'),
      dict(question=2,outcome='VS PPI domain-by-valence',coefficient='FEVS at mean PM2.5',direction='negative',estimate=f"{vs['voxels']} voxels",
           location='Left frontal target; MNI (-20.8, 57.6, 11.2)',corrected_p=p(vs['cluster_fwe_p']),correction='Cluster-FWE per map, CDT 3.1',sensitivity='+ADI .0320; +ECog .0349; +both .0353; +corrected MSPSS .0751 (no cluster)'),
      dict(question=3,outcome='Social win − nonsocial win activation',coefficient='ADI × corrected MSPSS',direction='positive',estimate=f"{adi['voxels']} voxels",
           location='Right posterior temporal vicinity; MNI (54.8, -31.5, 8.2)',corrected_p=p(adi['cluster_fwe_p']),correction='Cluster-FWE per map, CDT 3.1',sensitivity='Also CDT 2.6: p=.0482; LOO interaction 1.160 to 1.335; selected-region descriptive'),
      dict(question=3,outcome='VS PPI domain-by-valence',coefficient='ADI × ECog',direction='positive',estimate='48 voxels',
           location='MNI (-20.8, -72.0, -18.5)',corrected_p=p(neural('connectivity','social_specific','adixecog','adixecog','positive')['min_cluster_fwe_p']),correction='Cluster-FWE per map, CDT 3.1',sensitivity='CDT 2.6 p=.0383; influence limitations; not an activation interaction'),
      dict(question=3,outcome='VS PPI domain-by-valence',coefficient='PM2.5 × ECog',direction='positive / negative at separate targets',estimate='131 / 145 voxels',
           location='Multiple targets; coordinates in supplementary cluster table',corrected_p='.0194 / .0167',correction='Minimum cluster-FWE per sign, CDT 3.1',sensitivity='Influential observations; one negative-cluster HC3 interval includes zero'),
    ]
    return rows


def results_summary(summary):
    b = summary['behavior']; a = summary['adi_support']; fits = summary['vs_components']['fits']
    return f'''# Katie: Results-ready evidence, {DATE}

Frozen N=97; exploratory and not preregistered. This is an evidence report, not a draft manuscript Results section.

## 1. Environmental stressors, social support, and financial vulnerability

The corrected PM2.5 × MSPSS interaction predicts FEVS: b={f(b['beta'])}, HC3 95% CI {interval(b)}, Holm p=.000509 across two primary tests. It persists with additive ADI, ECog, or both. At observed support percentiles 16/50/84 (3.417/5.833/6.917), the conditional PM2.5 slopes are 2.369/−0.020/−1.091. None of the other seven moderation tests survives its prespecified within-family Holm correction. OAFEM remains a distinct secondary financial measure. Marginal correlations involving support were recomputed with the corrected screener means, without significance testing.

## 2. Financial vulnerability and neural reward processing

The original negative FEVS coefficient at mean PM2.5 in the domain-by-valence VS-PPI model passes at CDT3.1 (44 voxels, p=.0303; frontal peak −20.8,57.6,11.2). Earlier additive ADI/ECog checks pass, but **adding corrected MSPSS does not**: negative-direction map minimum p=.0751 at CDT3.1 and .1021 at CDT2.6; no corrected clusters in either direction. This limits any claim that the original finding is robust to perceived support. No surviving adjusted location can be reported; aggregate outputs do not establish persistence of the unthresholded frontal peak or fixed-ROI coefficient after this adjustment.

Within the original selected 44-voxel region, original-model component slopes are social b={f(fits['socialdoors']['beta'])} (HC3 {interval(fits['socialdoors'])}), nonsocial b={f(fits['doors']['beta'])} ({interval(fits['doors'])}), and their difference b={f(fits['difference']['beta'])} ({interval(fits['difference'])}). These describe relative task-modulated coupling and are not independent confirmation or evidence of causality. Social-winning activation remains secondary: it loses corrected significance with ECog in the standalone model and substantially overlaps atlas-labeled white matter.

## 3. Environmental stressors and neural reward processing

Corrected ADI × MSPSS predicts social-minus-nonsocial winning activation (87 voxels; p=.0255; peak 54.8,−31.5,8.2). The selected-cluster ADI slope rises from negative at lower support to positive at higher support. All single-case-omission interaction estimates remain positive ({f(a['fit']['loo_beta_min'])} to {f(a['fit']['loo_beta_max'])}); this is descriptive, does not retest whole-brain correction, and does not establish protective buffering. The region is chiefly posterior temporal cortex in the atlas, with 23% white-matter labels and a white-matter-labeled peak in the subcortical atlas. ADI × ECog and PM2.5 × ECog findings concern VS connectivity, with influence limitations; their activation counterparts do not pass. Corrected PM2.5 × MSPSS and FEVS × MSPSS neural models have no surviving coefficients at either threshold.

## Reuse, new work, and remaining limitations

Exactly two new 10,000-permutation VS-PPI jobs (four signed/CDT maps), seed20261101, df86, added centered corrected MSPSS and tested only the FEVS coefficient. Original maps/masks/order/covariates and the cohort were retained. Corrected support replaces exactly 384 historical maps within the 1,328-map inventory; 71 maps have clusters, versus 69 historically. These are overlapping mapwise results, not independent findings; no global correction across exploratory models was performed.

Linux2 completed source/output fingerprint checks; the local report independently verifies published artifact hashes and the corrected-catalog replacement. Selected-region diagnostics and figures remain descriptive. Questionnaire versions, scoring keys/rules, and financial assessment provenance still need documentation; the supplied totals are unchanged and provisional. Cognitive assessment recovery is deferred. Historical PDFs are preserved. See analysis-record.json, principal-evidence.tsv, the complete supplementary inventories, and the new versioned PDF.
'''


def build(source_revision, output=PDF, package=PACKAGE):
    summary, inventory, sources = verified_inputs()
    correlations, extra = corrected_correlations(); sources.update(extra)
    package.mkdir(parents=True, exist_ok=True); output.parent.mkdir(parents=True, exist_ok=True)
    native=load(package/'native-check-records.json')
    require(native['all_commands_passed'] and native['test_total']==24 and native['descriptive_native_integrity_checked'],
            'Verified Linux2 completion receipt required')
    tsv(package/'corrected-descriptive-correlations.tsv', correlations)
    evidence = principal_evidence(summary, inventory); tsv(package/'principal-evidence.tsv', evidence)
    (package/'results-summary.md').write_text(results_summary(summary))
    for name in ('scientific_inventory.tsv','scientific_clusters.tsv','vs_support_sensitivity_maps.tsv',
                 'behavioral_conditional_slopes.tsv','adi_conditional_slopes.tsv','vs_component_estimates.tsv'):
        shutil.copyfile(EVIDENCE/name, package/name)
    for name in ('figure-1-behavior.png','figure-2-vs-original-brain.png','figure-2-vs-support-brain.png',
                 'figure-2-vs-components.png','figure-3-adi-support-brain.png','figure-3-adi-support-conditional.png','adi-support-influence.png'):
        shutil.copyfile(EVIDENCE/name, package/name)
    grouped = defaultdict(list)
    for row in inventory: grouped[(row['family'],row['model'],row['outcome'])].append(row)
    groups = [dict(family=k[0],model=k[1],outcome=k[2],maps=len(v),maps_with_clusters=sum(int(r['significant_clusters'])>0 for r in v),
                   minimum_map_p=min(float(r['min_cluster_fwe_p']) for r in v),source_status=v[0]['source_status']) for k,v in sorted(grouped.items())]
    tsv(package/'model-null-inventory.tsv',groups)
    behavioral = old.rows(REVIEW/'behavioral-mspss-corrected-provisional-v1/interactions.tsv')
    adjustments = old.rows(REVIEW/'behavioral-mspss-corrected-provisional-v1/adjustments.tsv')
    imaging = old.rows(REVIEW/'fevs-imaging-adjustments-provisional-v1/maps.tsv')
    clusters = old.rows(EVIDENCE/'scientific_clusters.tsv')
    region_fits = load(REVIEW/'katie-review-v1/region_fits.json')
    followup = load(REVIEW/'reward-followup-v1/summary.json')
    pages = pdf_pages(summary,inventory,correlations,evidence,behavioral,adjustments,imaging,clusters,groups,region_fits,followup)
    render(output,pages)
    for name in ('code/build_katie_results_ready.py','code/build_fevs_results_pdf.py','code/requirements-results-ready.txt',
                 'tests/test_katie_results_ready.py','docs/katie-results-ready.md'):
        sources[name]=old.digest(ROOT/name)
    write_json(package/'analysis-record.json',dict(n=97,source_revision=source_revision,date=DATE,
        corrected_mspss_sha256=CORRECTED_SHA,canonical_maps=1328,corrected_support_replacements=384,canonical_maps_with_clusters=71,
        new_scientific_jobs=2,new_directional_maps=4,permutations=10000,seed=20261101,adjusted_rank=11,adjusted_df=86,
        reused='Completed original and corrected inference; earlier ADI/ECog sensitivities; task/event validation',
        descriptive='Observed-percentile slopes, selected-cluster influence/LOO, fixed-original-region PPI component decomposition; marginal correlations updated with corrected support',
        native_integrity='Linux2 completed source/mask/image/cohort/output fingerprint checks; native inputs are not present on this Mac',
        native_checks_receipt='native-check-records.json',native_tests_passed=24,native_fingerprints_checked=9671,
        local_integrity='Published output manifests, all 384 corrected replacements, and all retained historical passing maps independently verified; historical nulls rely on the sealed Linux2 inventory audit',
        exclusions_changed=False,scores_modified=False,historical_reports_overwritten=False,financial_scoring_provisional=True,
        cognitive_recovery_deferred=True,manuscript_results_drafted=False,
        support_adjustment_spatial_limit='No surviving adjusted clusters. Unthresholded adjusted peak/ROI direction and overlap cannot be established from this aggregate payload.',
        packages={n:importlib.metadata.version(n) for n in ('reportlab','Pillow','numpy','scipy','matplotlib')},python=sys.version.split()[0],
        report_pages=len(pages),source_files=sources))
    (package/'README.md').write_text('# Katie Results-ready Evidence\n\n'+
        '[Versioned PDF](../../../output/pdf/FEVS_Results_Ready_2026-11-07.pdf) | [Supported conclusions](results-summary.md) | [Principal evidence](principal-evidence.tsv) | [Reuse, new work, checks](analysis-record.json)\n\n'+
        'Three scientific questions; corrected Island screener MSPSS throughout. Frozen N=97. The new additive-support VS-PPI sensitivity has no corrected clusters; selected-cluster component and ADI/support figures are descriptive. Financial scoring remains provisional. No manuscript Results section was drafted.\n\n'+
        'scientific_inventory.tsv enumerates every canonical signed/CDT map, including nulls; scientific_clusters.tsv retains every passing cluster and coordinate. model-null-inventory.tsv summarizes all 134 family/model/outcome combinations; minimum p values there describe map minima, not additional corrected tests. vs_support_sensitivity_maps.tsv includes all four new maps and four reused baseline maps. Historical artifacts remain unchanged.\n')
    outputs = {str(p.relative_to(ROOT)):old.digest(p) for p in package.iterdir() if p.is_file() and p.name!='report-manifest.json'}
    outputs[str(output.relative_to(ROOT))] = old.digest(output)
    write_json(package/'report-manifest.json',dict(n=97,source_revision=source_revision,outputs=outputs,source_files=sources))
    return len(pages)


def pdf_pages(s,inv,corr,evidence,behavioral,adjustments,imaging,clusters,groups,region_fits,followup):
    """Explicit pages make overflow an error; no hidden shrinking or raster cropping."""
    pages=[]
    def page(section,title,*blocks): pages.append(dict(section=section,title=title,blocks=blocks))
    def text(t):return ('text',t)
    def small(t):return ('small',t)
    def table(headers,rows,widths):return ('table',headers,rows,widths)
    def image(path,width=690,height=300):return ('image',str(path),width,height)
    def context(t):return text('<b>Context.</b> '+t)
    def conclusion(t):return text('<b>Conclusion.</b> '+t)
    def href(label,path):return f'<link href="https://github.com/DVS-Lab/rf1-sra-environment-SD/blob/main/{path}" color="#126a70">{label}</link>'
    first,second,third=SECTIONS; app='Appendix: methods, sensitivity, and complete evidence'
    page('Evidence report','Environmental stressors, financial vulnerability, and social reward',
         text(f'<b>Katie Social Doors | Results-ready evidence | {DATE}</b>'),
         text('Frozen N=97. Exploratory, not preregistered. Financial-score documentation remains provisional. This report organizes evidence for manuscript planning; it is not a draft Results section.'),
         table(['Scientific question','Supported finding','Interpretive boundary'],[
             ['1. Environment, support, and financial vulnerability','Corrected PM2.5 × MSPSS predicts FEVS and persists across ADI/ECog checks.','Conditional association; OAFEM is distinct; no mediation or causal inference.'],
             ['2. Financial vulnerability and neural reward','Original FEVS–VS PPI association has opposing social/nonsocial components.','Adding corrected MSPSS yields no corrected cluster. Activation is also sensitive to adjustment.'],
             ['3. Environment and neural reward','Corrected ADI × MSPSS predicts social-minus-nonsocial winning activation.','Crossover in a selected temporal region; protective buffering is not established.']], [180,270,246]),
         text('<b>What changed in the final pass?</b> Two new whole-brain jobs add corrected MSPSS to the existing VS model. Their negative-direction map minima are .1021 (CDT2.6) and .0751 (CDT3.1), so the original corrected connectivity finding cannot be described as robust to support adjustment.'),
         small('Three principal figure candidates accompany the report: behavioral conditional slopes; original VS target plus component estimates and support sensitivity; corrected ADI × support activation plus conditional slopes. Full signed/CDT inventories are in the supplementary TSV files.'))
    page('Principal evidence','A compact map of findings and sensitivity',
         table(['Q','Outcome / coefficient','Direction / location','Corrected evidence','Sensitivity / qualification'],[
             [r['question'],r['outcome']+'<br/>'+r['coefficient'],r['direction']+'<br/>'+r['location'],r['estimate']+'<br/>p='+r['corrected_p']+'<br/>'+r['correction'],r['sensitivity']] for r in evidence], [18,168,173,124,213]),
         small('Neural p values are cluster-FWE within an individual map at the stated cluster-forming threshold, not correction across exploratory models, signs, outcomes, or thresholds. Minimum p across several clusters describes that map; it does not apply to every cluster. Full precision and every cluster are retained in the supplementary tables.'))
    page(first,'Marginal relationships provide context, not model selection',
         context('Describe the financial and environmental measures in the same 97-person cohort before interpreting moderation. Every support correlation below uses the corrected Island screener MSPSS mean.'),
         table(['Pair','Pearson r','Spearman ρ','Pair','Pearson r','Spearman ρ'],[
             [model_label(a['variable_1'])+' / '+model_label(a['variable_2']),f(a['pearson_r']),f(a['spearman_rho']),
              model_label(b['variable_1'])+' / '+model_label(b['variable_2']) if b else '',f(b['pearson_r']) if b else '',f(b['spearman_rho']) if b else ''] for a,b in zip(corr[:8],corr[8:]+[None])], [200,73,75,200,73,75]),
         small('N=97 for each pair. Correlations are unadjusted descriptions with no significance tests or multiplicity claims. ADI/PM2.5 are exposures, MSPSS and ECog are moderators or covariates, and FEVS and OAFEM remain distinct financial measures.'),
         conclusion('Weak marginal exposure–financial correlations do not exclude a conditional association. Shared variation among support, ECog, and financial scores does not identify a causal pathway.'))
    b=s['behavior']
    page(first,'Figure 1. The PM2.5–FEVS slope varies across observed support',
         context('Does corrected perceived support modify the PM2.5–FEVS association in the existing age- and gender-adjusted model?'),
         image(PACKAGE/'figure-1-behavior.png',690,280),
         text(f"<b>Content.</b> Interaction b={f(b['beta'])}; HC3 95% CI {interval(b)}; two-sided p=.000255; Holm p=.000509 across the two primary behavioral tests. The curve is a slope, not a predicted FEVS score. Bands are pointwise, not simultaneous; the rug shows observed corrected support."),
         conclusion('The PM2.5 association is positive at lower support and becomes less positive, then negative, as support increases. This observational pattern is consistent with moderation; it does not demonstrate that support prevents financial vulnerability.'))
    page(first,'Observed support levels and existing sensitivity checks',
         table(['Observed percentile','Corrected MSPSS','PM2.5 slope','HC3 95% CI'],[
             [r['percentile'],f(r['moderator']),f(r['slope']),interval(r)] for r in b['conditional_slopes']], [150,150,150,246]),
         small('Nearest empirical 16th/50th/84th percentiles ensure each reported moderator value is observed. Slopes use the unchanged behavioral model and its HC3 covariance, with t-based pointwise intervals (df91).'),
         table(['Added covariates','Interaction b','HC3 95% CI','HC3 p'],[
             [r['adjustment'],f(r['interaction_beta']),f"[{f(r['ci_lower'])}, {f(r['ci_upper'])}]",f"{float(r['hc3_p']):.6f}"] for r in adjustments], [150,150,246,150]),
         text('All fits retain N=97, PM2.5, corrected MSPSS, their interaction, age, and gender. ADI and ECog enter only additively. Sensitivity p values are not corrected across these related adjustment checks.'),
         conclusion('The negative behavioral interaction persists after each specified adjustment. The supplied financial totals remain unchanged; stability of these fits does not validate the instrument version, scoring key, or assessment timing.'))
    page(first,'All eight behavioral tests, including secondary nulls',
         table(['Outcome','Exposure × moderator','Family','Interaction b','HC3 95% CI','Holm p'],[
             [r['outcome'].upper(),model_label(r['exposure'])+' × '+model_label(r['moderator']),r['family'],f(r['interaction_beta']),f"[{f(r['ci_lower'])}, {f(r['ci_upper'])}]",f"{float(r['holm_family_p']):.6f}"] for r in behavioral], [64,184,65,90,182,111]),
         text('Two primary tests: FEVS with ADI × MSPSS and PM2.5 × MSPSS. Six secondary tests: the two FEVS–ECog interactions and all four OAFEM interactions. Holm adjustment is separate within these original families.'),
         conclusion('Only PM2.5 × corrected MSPSS predicting FEVS survives its family correction. ADI × support predicting OAFEM has a nominal interaction but Holm p=.213; it is not an equivalent supported financial outcome.'),
         small('Financial scoring documentation remains unresolved: administered questionnaire versions, scoring rules/keys, and source/timepoint provenance. Complete exported totals exist for all 97. No rescoring, exclusions, psychometric expansion, or cognitive-measure substitution was performed.'))
    page(second,'Task validation and neural contrasts must remain distinct',
         context('The tasks should elicit ordinary reward responses before individual differences are interpreted. Existing corrected activation maps show bilateral striatal win–loss responses in both tasks.'),
         table(['Quantity','Definition','Role'],[
             ['Social winning','Social win − nonsocial win','FEVS activation and corrected ADI × support activation'],
             ['Domain-by-valence','(Social win − social loss) − (nonsocial win − nonsocial loss)','FEVS VS-PPI and environmental × ECog connectivity'],
             ['Task mean','Mean of social and nonsocial win−loss','Shared reward response; not social specificity']], [144,330,222]),
         text('Existing anatomical bilateral VS means are 60.98 COPE units for social win–loss (descriptive 95% CI 45.02–76.94) and 72.28 for nonsocial win–loss (55.77–88.78). These anatomical summaries are descriptive checks, not new whole-brain inference.'),
         text('The existing group-average domain-by-valence activation maps have no corrected clusters at either threshold or sign (best mapwise p=.2081 at CDT3.1). That null does not invalidate an individual-difference association with a different outcome or model.'),
         conclusion('Reward response is present in both tasks. Social-winning activation and domain-by-valence VS coupling address different questions and should not be used interchangeably.'))
    page(second,'FEVS winning activation remains secondary and qualified',
         context('FEVS has a positive association with social-minus-nonsocial winning activation in the original analysis. Compare the standalone coefficient with FEVS evaluated at mean PM2.5.'),
         table(['FEVS coefficient','Baseline','+ADI','+ECog','+both'],[
             ['Standalone','p=.0411; 56 vox','p=.0458','p=.0666; no cluster','p=.0709; no cluster'],
             ['At mean PM2.5','p=.0315; 67 vox','p=.0323','p=.0505; no cluster','p=.0477; 53 vox']], [180,129,129,129,129]),
         text('All values are positive-direction map minima at CDT3.1. Neither original coefficient passes at CDT2.6. The FEVS main coefficient at mean PM2.5 is not the FEVS × PM2.5 interaction.'),
         text('Original peaks are approximately (−31.6,49.5,−6.7) standalone and (−31.6,49.5,−3.7) conditional. Harvard–Oxford subcortical atlas labels assign 79% and 66% of these clusters, respectively, to white matter; both peaks are white-matter-labeled. Atlas labels are not native tissue segmentation.'),
         conclusion('Describe this as a qualified left anterior/ventral frontal association, with coordinates and adjustment sensitivity. The evidence does not support a precise cortical vmPFC/OFC claim. Secondary brain figures appear in the appendix.'))
    page(second,'Figure 2A. The original VS target does not survive support adjustment',
         image(PACKAGE/'figure-2-vs-original-brain.png',590,245),
         text('Original negative FEVS coefficient at mean PM2.5: 44-voxel left frontal target, peak (−20.8,57.6,11.2), p=.0303 at CDT3.1. The VS is the seed; the displayed frontal cluster is its task-modulated coupling target.'),
         table(['Covariates added to original model','Negative map, CDT2.6','Negative map, CDT3.1','Corrected clusters at CDT3.1'],[
             ['None','.0504','.0303','1 (44 voxels)'],['Corrected MSPSS only','.1021','.0751','0']], [285,130,130,151]),
         conclusion('The original whole-brain association is sensitive to perceived-support adjustment. Earlier ADI/ECog checks passed (.0320/.0349/.0353), but no cluster survives the new support sensitivity in either direction or at either threshold.'))
    fits=s['vs_components']['fits']
    page(second,'Figure 2B. Both task components contribute to the domain difference',
         context('Use the original 44-voxel region as a fixed descriptive target. Fit each task component with the same original FEVS + PM2.5 + interaction and common covariates.'),
         image(PACKAGE/'figure-2-vs-components.png',696,245),
         table(['Component','FEVS slope','HC3 95% CI'],[[label,f(fits[key]['beta']),interval(fits[key])] for key,label in
             [('socialdoors','Social win−loss VS PPI'),('doors','Nonsocial win−loss VS PPI'),('difference','Social − nonsocial difference')]], [300,150,246]),
         conclusion('The original negative difference reflects a negative social slope and a positive nonsocial slope. These selected-region estimates describe relative task-modulated coupling; their intervals do not independently confirm the selected whole-brain effect or establish a causal change in connectivity.'))
    a=s['adi_support']; fit=a['fit']
    page(third,'Figure 3A. Corrected ADI × support predicts winning activation',
         context('Does perceived support modify the association between neighborhood disadvantage and social-minus-nonsocial winning activation?'),
         image(PACKAGE/'figure-3-adi-support-brain.png',610,270),
         text('The positive ADI × corrected MSPSS interaction has 87 voxels at CDT3.1, cluster-FWE p=.0255, peak (54.8,−31.5,8.2). The same tested interaction also passes at CDT2.6 (215 voxels, p=.0482). This is winning activation, not domain-by-valence activation or VS connectivity.'),
         conclusion('The cluster lies near right posterior temporal cortex. Cortical atlas overlap is 62% posterior middle temporal gyrus, 21% posterior superior temporal gyrus, and 7% planum temporale. Subcortical atlas labels include 23% white matter and a white-matter-labeled peak; anatomical precision remains limited.'))
    page(third,'Figure 3B. The selected-region pattern is a crossover',
         image(PACKAGE/'figure-3-adi-support-conditional.png',590,270),
         table(['Observed percentile','Corrected MSPSS','ADI activation slope','HC3 95% CI'],[[r['percentile'],f(r['moderator']),f(r['slope']),interval(r)] for r in a['conditional_slopes']], [150,150,150,246]),
         conclusion('The selected-region ADI slope changes from negative at lower support to positive at higher support. A higher activation contrast has no established protective meaning here, so the result should not be characterized as demonstrated neural buffering.'),
         small('Original activation images, model covariates, and corrected screener scores; N=97. Pointwise HC3 intervals and the rug describe a region selected in the same data. They are not independent evidence for the cluster or simultaneous moderator-wide tests.'))
    page(third,'Environmental and cognitive moderation: preserve scope and nulls',
         table(['Finding','Outcome / coefficient','CDT3.1 mapwise p','Interpretation'],[
             ['ADI × ECog','VS-PPI domain-by-valence interaction, positive','.0473 (48 voxels)','Connectivity interaction; not the corrected ADI × support activation result.'],
             ['PM2.5 × ECog','VS-PPI domain-by-valence interaction, both signs','.0194 positive / .0167 negative','Multiple targets; substantial influence; one negative-cluster HC3 interval crosses zero.'],
             ['ADI × ECog','VS-PPI task-mean interaction, positive','.0238 (66 voxels)','Shared-task coupling; not social specificity.'],
             ['ADI × ECog','VS-PPI social−nonsocial loss interaction, negative','.0092 (3 clusters; 230 voxels)','Valence-specific follow-up; full cluster details retained.'],
             ['Corrected PM2.5 × MSPSS / FEVS × MSPSS','All coefficients, outcomes, signs, thresholds','No surviving coefficients','These corrected models yield no map with a corrected cluster.']], [125,257,125,189]),
         text('Activation ADI × ECog and PM2.5 × ECog interaction maps have no corrected clusters. ECog main effects within interaction models are conditional main coefficients; they are not evidence that the corresponding interaction is significant.'),
         conclusion('Retain the environmental–ECog connectivity findings as exploratory evidence with influence limitations. The corrected ADI × support winning-activation result is a separate finding; neither justifies a broad neural-buffering claim.'))
    page(app,'Selected-region influence does not require changing the cohort',
         image(PACKAGE/'adi-support-influence.png',680,240),
         text(f"Corrected ADI × support selected-region interaction b={f(fit['beta'])}, HC3 95% CI {interval(fit)}. All 97 single-case-omission coefficients remain positive, {f(fit['loo_beta_min'])} to {f(fit['loo_beta_max'])}. Maximum Cook’s D={f(fit['max_cooks_d'])}; maximum leverage={f(fit['max_leverage'])}; 9 observations exceed the 4/N Cook’s-D heuristic."),
         text('The region remains fixed during these diagnostic fits. No participant is removed from the actual analysis, no exclusion is revised, and leave-one-out coefficients do not establish that a whole-brain cluster would survive rerunning permutations after omission.'),
         small('Only aggregate diagnostic distributions and summaries are published. Participant identifiers, individual diagnostic rows, and source-image paths remain outside the report payload.'))
    page(app,'Secondary activation maps and influence limitations',
         image(REVIEW/'fevs-win-v1/fevsxpm25-brain.png',530,220),
         text('Original FEVS-at-mean-PM2.5 winning activation (67 voxels; p=.0315 at CDT3.1). The existing native map is reused; it is not recalculated by the PDF builder. Positive/negative colors follow the source legend.'),
         table(['Existing fixed original region','HC3 slope / interval','Single-case omission range','Max Cook’s D'],[
             ['FEVS standalone activation','9.790 [4.036, 15.544]','7.864 to 10.440','.206'],
             ['FEVS at mean PM2.5 activation','11.740 [4.309, 19.170]','9.703 to 12.661','.255'],
             ['FEVS original VS difference','−.110 [−.155, −.066]','−.114 to −.098','.200']], [220,210,170,96]),
         small('Selected-region slopes describe the original regions; they do not override whole-brain nulls after adjustment. The existing matched adjustment maps and their overlap/atlas tables remain linked in results/review/fevs-adjustment-maps-v1/.'))
    page(app,'Additional financial, ECog, and OAFEM findings remain secondary',
         table(['Existing coefficient / contrast','Cluster evidence','Selected-region influence'],[
             ['FEVS × PM2.5; social−nonsocial loss activation','Negative; CDT3.1 p=.0495; 90 voxels; peak (−26.2,−42.3,61.7)','HC3 interaction −22.742 [−34.577,−10.906]; max Cook’s D=.245; not the FEVS main coefficient during winning.'],
             ['ECog at mean PM2.5; social−nonsocial loss activation','Negative; CDT2.6 p=.0318; 290 voxels','HC3 interval [−352.088,24.003] includes zero; max Cook’s D=1.637. Main coefficient, not PM2.5 × ECog.'],
             ['ECog at mean OAFEM; social−nonsocial winning activation','Negative; CDT3.1 p=.0453; 61 voxels','Max Cook’s D=.665; one-case omissions change magnitude. Main coefficient, not OAFEM × ECog.'],
             ['Corrected OAFEM × MSPSS; social−nonsocial loss activation','Positive; CDT2.6 p=.0415; 273 voxels','Corrected interaction, secondary; no new selected-region refit performed here.'],
             ['Corrected OAFEM main coefficient at mean support; task-mean VS PPI','Negative; p=.0089/.0071 at CDT2.6/3.1','Distinct financial measure and common-task outcome, not FEVS social winning.'],
             ['Corrected OAFEM main coefficient at mean support; social−nonsocial loss VS PPI','Positive; p=.0035/.0123 at CDT2.6/3.1','4/2 clusters respectively; full coordinates and p values retained.'],
             ['Corrected OAFEM × MSPSS; task-mean VS PPI','Negative; CDT3.1 minimum p=.0349; 2 clusters, 119 voxels','Interaction distinct from the negative OAFEM main coefficient.']], [235,215,246]),
         small('The full map/cluster inventory retains OAFEM × ADI/PM2.5/ECog and all other tested coefficients, including nulls. Minimum p values do not imply every cluster has the same p. No weak threshold-specific result is promoted to a principal figure.'))
    selected=[r for r in region_fits if 'selected' in r['selection'].lower() and any(x in r['title'] for x in ('adixecog','pm25xecog'))]
    page(app,'Environmental × ECog influence summaries',
         table(['Existing selected region','Coefficient','HC3 95% CI','LOO minimum / maximum','Max Cook’s D'],[
             [r['title'].replace('environment_connectivity | connectivity | ','').replace(' | ',' / '),f(r['estimate']),f"[{f(r['hc3_ci'][0])}, {f(r['hc3_ci'][1])}]",f(r['leave_one_out_estimate_min'])+' / '+f(r['leave_one_out_estimate_max']),f(r['max_cooks_d'])] for r in selected], [265,70,140,130,91]),
         small('These existing same-sample selected-region summaries are reused without participant exclusions. The PM2.5 × ECog clusters include Cook’s D values above 1; one negative cluster’s HC3 interval crosses zero. Stable single-case-omission signs are not evidence of independent validation, simultaneous-omission stability, or cluster-corrected survival after refitting.'))
    page(app,'Reproducibility, acquisition limits, and score provenance',
         text('<b>Reused inference.</b> Original canonical catalog: 1,328 signed/CDT maps. Exactly 384 historical support maps are replaced with 384 corrected maps; all other entries remain numerically identical. There are 71 maps with clusters, versus the historical 69. Overlapping thresholds, coefficients, and outcomes are not independent discoveries.'),
         text('<b>New inference only.</b> Two VS-PPI domain-by-valence randomise jobs; 10,000 permutations, seed20261101, both FEVS directions; CDTs Z2.6/3.1 converted to t using df86. Original ten columns are retained exactly and centered corrected MSPSS is the sole added column (rank11, N97). A two-permutation smoke test is a workflow check, not an additional scientific analysis.'),
         text('<b>Common covariates.</b> Neural models retain signed FD and tSNR task differences (pair means for task-mean outcomes), scanner-era indicators, age, and gender. FEVS sensitivity retains FEVS + PM2.5 + FEVS × PM2.5; no FEVS × support interaction is introduced. Behavioral models retain age and gender with their original two-primary/six-secondary correction families.'),
         text('<b>Corrected support.</b> Ryan’s November 5 revised export; the same Island screener records are preserved, including repeat screening after scan. These are not prescan retest values or averages across administrations. Corrected scores range 1–7; 82 changed and 15 were unchanged. No independent item-level rescore or prospective temporal ordering is claimed.'),
         text('<b>Integrity and publication.</b> Linux2 passed 24 tests and checked 9,671 source/completed-output fingerprints. This builder verifies published manifests, all 384 corrected replacements, retained historical passing maps, and component-slope reconciliation. Historical null preservation relies on the sealed Linux2 inventory audit. Participant rows are not published. Historical reports remain unchanged. Financial documentation and cognitive recovery remain unresolved/deferred.'),
         small('All neural correction is mapwise cluster-FWE. Pointwise HC3 selected-region intervals are descriptive and are not extra confirmatory tests. No new whole-brain component search, exclusion change, mediation model, or manuscript Results draft was produced.'))
    page(app,'Event-file audit and boundaries of the new support sensitivity',
         text('The published read-only task audit inspected all 97 task pairs. It found zero EV-versus-own-BIDS mismatches, zero BIDS-versus-resolved-source mismatches, zero shared consumed EV files, zero identical complete task-regressor sets, zero identical canonical four-EV timing sets, and no unresolved sources or inspection errors. Native PDF design screenshots matched the inspected native files.'),
         text('The tasks can look similar because their win/loss sequences and timing structure are similar. The event audit verifies recorded event provenance and consumption; it does not independently verify scanner/task acquisition identity. No native screenshot is relabeled or substituted in this report.'),
         table(['New sensitivity, all signs','CDT2.6 map minimum p','CDT3.1 map minimum p','Corrected clusters'],[
             ['Negative FEVS + corrected MSPSS','.1021','.0751','0 at both thresholds'],
             ['Positive FEVS + corrected MSPSS','.8368','.6146','0 at both thresholds']], [270,150,150,126]),
         text('There is no surviving adjusted location to compare with the original 44-voxel cluster. The published aggregate package contains corrected-map minima and thresholded figures, not the unthresholded adjusted map or an adjusted fixed-ROI coefficient. It therefore does not establish persistence of the original frontal peak, spatial pattern, or ROI slope after support adjustment. A null corrected map alone also does not establish a reversal of direction.'),
         small(href('Published event provenance audit','results/review/task-event-audit-summary-8bd32f07632e/summary.json')+' | '+href('All sensitivity maps','results/review/katie-results-ready-v1/vs_support_sensitivity_maps.tsv')))
    passing=[r for r in inv if int(r['significant_clusters'])]
    for start in range(0,len(passing),20):
        rows=passing[start:start+20]; data=[]
        for r in rows:
            matches=[c for c in clusters if catalog_key(c)==catalog_key(r)]
            peak=min(matches,key=lambda c:float(c['cluster_fwe_p_min']))
            data.append([r['family'],OUTCOMES[r['outcome']],model_label(r['model']),model_label(r['term']),r['direction'],r['z'],p(r['min_cluster_fwe_p']),r['significant_voxels'],coord(peak)])
        page(app,f'All maps with corrected clusters ({start+1}–{start+len(rows)} of {len(passing)})',
             table(['Family','Contrast','Model','Tested coefficient','Sign','CDT','Min p','Voxels','Peak MNI*'],data,[58,90,80,90,40,25,45,35,133]),
             small('*Peak from the cluster with the lowest corrected p in that map; voxel count is total across all its clusters. Every individual cluster, coordinate, and p is in scientific_clusters.tsv. MSPSS models use corrected scores; all other maps are retained. This table lists overlapping mapwise results, not independent discoveries.'))
    for start in range(0,len(groups),20):
        rows=groups[start:start+20]
        page(app,f'Complete model/null coverage ({start+1}–{start+len(rows)} of {len(groups)})',
             table(['Family','Model','Outcome','Signed/CDT maps','Maps with clusters','Minimum map p'],[
                 [r['family'],model_label(r['model']),OUTCOMES[r['outcome']],r['maps'],r['maps_with_clusters'],p(r['minimum_map_p'])] for r in rows],[75,170,145,100,110,96]),
             small('Each row retains an original family/model/outcome combination, including all-null models. Map counts include tested main coefficients and interactions, both signs, and both thresholds. The minimum is descriptive, not a new omnibus test. The complete 1,328-row table gives every tested coefficient and map, including null p values: '+href('scientific_inventory.tsv','results/review/katie-results-ready-v1/scientific_inventory.tsv')))
    return pages


def render(output,pages):
    from PIL import Image as PILImage
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Image,PageBreak,Table,TableStyle,KeepInFrame
    import matplotlib
    fonts=Path(matplotlib.get_data_path())/'fonts/ttf'
    for name,file in [('Evidence','DejaVuSans.ttf'),('EvidenceBold','DejaVuSans-Bold.ttf')]:
        pdfmetrics.registerFont(TTFont(name,str(fonts/file)))
    pdfmetrics.registerFontFamily('Evidence',normal='Evidence',bold='EvidenceBold',italic='Evidence',boldItalic='EvidenceBold')
    teal=colors.HexColor('#126a70');ink=colors.HexColor('#182329');muted=colors.HexColor('#4b5960')
    styles={
      'section':ParagraphStyle('section',fontName='EvidenceBold',fontSize=10,leading=13,textColor=teal,spaceAfter=5),
      'title':ParagraphStyle('title',fontName='EvidenceBold',fontSize=20,leading=24,textColor=ink,spaceAfter=10),
      'text':ParagraphStyle('body',fontName='Evidence',fontSize=10,leading=14,textColor=ink,spaceAfter=9),
      'small':ParagraphStyle('small',fontName='Evidence',fontSize=8,leading=11,textColor=muted,spaceAfter=7),
      'cell':ParagraphStyle('cell',fontName='Evidence',fontSize=8,leading=10.3,textColor=ink),
      'compact':ParagraphStyle('compact',fontName='Evidence',fontSize=7.2,leading=9.3,textColor=ink),
    }
    from reportlab.pdfgen import canvas as canvas_module
    import io
    probe=canvas_module.Canvas(io.BytesIO())
    story=[]; overflow=[]
    for index,page in enumerate(pages):
        content=[Paragraph(escape(page['section']),styles['section']),Paragraph(escape(page['title']),styles['title'])]
        for block in page['blocks']:
            if block[0] in ('text','small'):content.append(Paragraph(block[1],styles[block[0]]))
            elif block[0]=='image':
                _,name,w,h=block
                with PILImage.open(name) as im:iw,ih=im.size
                ratio=min(w/iw,h/ih);content.extend([Image(name,width=iw*ratio,height=ih*ratio),Spacer(1,7)])
            elif block[0]=='table':
                _,headers,rows,widths=block
                compact=page['title'].startswith('All maps with corrected clusters')
                style=styles['compact' if compact else 'cell']
                cells=[[Paragraph('<b>'+escape(str(v))+'</b>',style) for v in headers]]
                cells += [[Paragraph(str(v),style) for v in row] for row in rows]
                grid=Table(cells,colWidths=widths,hAlign='LEFT')
                grid.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#edf4f4')),('LINEBELOW',(0,0),(-1,0),.6,teal),
                    ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f7f9fa')]),('VALIGN',(0,0),(-1,-1),'TOP'),
                    ('TOPPADDING',(0,0),(-1,-1),3 if compact else 4),('BOTTOMPADDING',(0,0),(-1,-1),3 if compact else 4),('LEFTPADDING',(0,0),(-1,-1),4 if compact else 5),('RIGHTPADDING',(0,0),(-1,-1),4 if compact else 5)]))
                content.extend([grid,Spacer(1,9)])
        frame=KeepInFrame(696,526,content,mode='error')
        try: frame.wrapOn(probe,696,526)
        except Exception as exc: overflow.append(f"Page {index+1}: {page['title']}: {exc}")
        story.append(frame)
        if index<len(pages)-1:story.append(PageBreak())
    require(not overflow,'Page layout overflow: '+'\n'.join(overflow))
    def footer(canvas,document):
        canvas.saveState();canvas.setStrokeColor(teal);canvas.line(42,582,750,582)
        canvas.setFont('Evidence',7.5);canvas.setFillColor(muted)
        canvas.drawString(42,20,'EXPLORATORY | Frozen N=97 | Corrected MSPSS | Financial scoring provisional | '+DATE)
        canvas.drawRightString(750,20,f'{document.page} / {len(pages)}')
        idx=document.page-1
        if idx<len(pages):
            key='page-'+str(document.page);canvas.bookmarkPage(key)
            if idx==0 or pages[idx]['section']!=pages[idx-1]['section']:
                canvas.addOutlineEntry(pages[idx]['section'],key,level=0)
        canvas.restoreState()
    doc=SimpleDocTemplate(str(output),pagesize=(792,612),leftMargin=42,rightMargin=42,topMargin=38,bottomMargin=36,
        title='Katie: Environmental Stressors, Financial Vulnerability, and Social Reward — Results-ready Evidence',
        author='DVS-Lab',pageCompression=1)
    doc.build(story,onFirstPage=footer,onLaterPages=footer)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source-revision',required=True)
    args=parser.parse_args();print('BUILT',build(args.source_revision),'pages:',PDF)
