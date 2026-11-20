"""Export figure sources from completed Linux2 receipts. No FSL jobs or new inference."""
from pathlib import Path
import json
import os
import sys
import tempfile

import nibabel as nib
import numpy as np
from scipy.ndimage import label
from scipy.stats import t
import statsmodels.api as sm

KIT=Path(__file__).resolve().parent
ROOT=KIT.parents[1]
sys.path.insert(0,str(ROOT/"code"))
import review_katie_targeted as old
import render

must,one,prior = old.require,old.one,old.prior
sha=old.base.cohort.digest
read=prior.read
CAT=ROOT/"results/review/katie-results-ready-v1/scientific_clusters.tsv"
OUT=ROOT/"work/katie-figure-sources-v1"

def subset(labels,stat,prob,ref,row):
    region=labels==int(row["component"])
    must(region.any() and region.sum()==int(row["voxels"]),"Unexpected component size")
    ijk=np.argwhere(region)[stat[region].argmax()]
    xyz=nib.affines.apply_affine(ref.affine,ijk)
    must(np.allclose(xyz,[float(row["peak_"+a+"_mm"]) for a in "xyz"],rtol=0,atol=1e-5)
         and np.isclose(1-prob[region].max(),float(row["cluster_fwe_p_min"]),rtol=0,atol=1e-7),
         "Peak/cluster p differs from the published component")
    return region

def export_image(path,ref,values):
    # No participant/source headers, extensions, identifiers or absolute paths.
    image=nib.Nifti1Image(values,ref.affine)
    for which in ("qform","sform"):
        aff,code=getattr(ref,"get_"+which)(coded=True)
        getattr(image,"set_"+which)(aff,int(code))
    image.header.set_xyzt_units("mm")
    nib.save(image,path)
    saved=nib.load(path)
    old.base.grid(ref,saved)
    must(np.array_equal(np.asarray(saved.dataobj),values),"NIfTI write check failed")

def write_table(path,rows):
    path.write_text(old.base.review.tsv(rows))

def make(stage):
    pub=stage/"group-maps"; prv=stage/"extractions"; pub.mkdir(); prv.mkdir()
    source_hashes={}
    for fp in (ROOT/"work/katie-results-ready-v1/inputs-private.json",
               ROOT/"work/katie-targeted-native-v1/input_fingerprints_private.json"):
        for r in json.loads(fp.read_text())["sources"]:
            old.audit.add_record(source_hashes,r["path"],r["sha256"],r.get("size"))
    checked=set()
    def check(path):
        path=Path(path).resolve()
        if path not in checked:
            must(str(path) in source_hashes and sha(path)==source_hashes[str(path)]["sha256"],
                 "Unsealed or changed native source: "+str(path))
            checked.add(path)
        return path
    plans={}
    ids,v=old.values()
    for key in ("katie-reward-extension-v1","katie-mspss-corrected-v1","katie-remaining-v1/connectivity"):
        folder=ROOT/"derivatives/fsl/randomise"/key
        check(folder/"plan.json"); check(folder/"subjects.tsv")
        plan=prior.plan_and_receipts(folder,{},False)
        must(plan.get("project",str(ROOT))==str(ROOT) and [r["subject"] for r in read(folder/"subjects.tsv")]==ids,
             "Project or native volume order differs")
        plans[key]=(folder,plan)
    orig,correct,retain=plans.values()
    specs=[]
    for fig,owner,key,term,direction in (
        (2,orig,"connectivity/social_specific/fevsxpm25/z-3p1","fevs","negative"),
        (3,correct,"activation/win_only/adixmspss/z-3p1","adixmspss","positive")):
        job=one(j for j in owner[1]["jobs"] if j["key"]==key)
        index=one(k for k in job["contrasts"] if (k["term"],k["direction"])==(term,direction))["index"]
        specs.append((fig,owner,job,index,key.split("/")[1],term,direction))
    metadata=read(KIT/"sources/fig4/vs_clusters.tsv")
    for typ,z,direction in dict.fromkeys((r["outcome"],float(r["z"]),r["direction"]) for r in metadata):
        src=one(r for r in orig[1]["coverage"] if prior.key(r)==("connectivity",typ,"adixecog","adixecog",direction,z))["source"]
        if src["origin"]=="extension":
            owner=orig; job=one(j for j in orig[1]["jobs"] if j["key"]==src["job"])
        else:
            must(src["origin"]=="existing" and src["batch"]=="environment_connectivity","Unexpected retained batch")
            owner=retain; job=one(j for j in retain[1]["jobs"] if j==src["source_job"])
        specs.append((4,owner,job,src["index"],typ,"adixecog",direction))
    catalog=read(CAT); index_rows=[]; all_regions={}; vs_rows=[]
    for fig,(folder,plan),job,index,outcome,term,direction in specs:
        family="activation" if fig==3 else "connectivity"
        key=(family,outcome,job["model"],term,direction,float(job["z"]))
        expected=[r for r in catalog if prior.key(r)==key]
        success=check(folder/"jobs"/job["key"]/"success.json")
        prefix=Path(json.loads(success.read_text())["attempt"])/"randomise"
        for path in (str(prefix)+f"_tstat{index}.nii.gz",str(prefix)+f"_clustere_corrp_tstat{index}.nii.gz",
                     plan.get("mask") or plan["masks"][job["family"]],job["design"],job["contrast"],
                     Path(job["design"]).with_suffix(".tsv")):
            check(path)
        path=check(plan["images"][job["outcome"]])
        ref,stat,p,selected=old.load_map(folder,plan,job,index,dict(source_hashes))
        if fig!=2:
            names,x=old.checked_matrix(job,ids,v,outcome,term,direction,index)
        else:
            names,x=prior.checked_design(job,ids,v)
        labs,n=label(selected,structure=old.STRUCTURE)
        must(n==len(expected)>0,"Unexpected cluster count")
        vox=old.region_values(path,ref,selected)
        for r in expected:
            mask=subset(labs,stat,p,ref,r)
            means=vox[mask[selected]].mean(axis=0,dtype=np.float64)
            if fig==4:
                row=one(k for k in metadata if (k["outcome"],float(k["z"]),k["direction"],k["component"])==
                        (outcome,float(job["z"]),direction,r["component"]))
                stem="Fig4_"+row["id"]+"_ADIxECog_"+outcome+"_z"+row["z"].replace(".","p")+"_"+direction
                if all_regions: old.base.grid(first_ref,ref)
                else: first_ref=ref
                all_regions[row["id"]]=mask
                must(np.isclose((np.linalg.pinv(x)@means)[names.index(term)],float(row["beta"]),rtol=0,atol=1e-7),
                     "Extracted fixed-cluster slope differs")
                vs_rows.extend(dict(subject=s,cluster=row["id"],region_cope=float(y)) for s,y in zip(ids,means))
            elif fig==3:
                stem="Fig3_ADIxMSPSS_social_minus_nonsocial_win_z3p1_positive"
                order=check(orig[0]/"source_order.tsv")
                for sr in read(order):
                    if sr["family"]=="activation" and sr["cope"]=="1": check(sr["source"])
                parts=old.components(orig[0],source_hashes,ids,ref,mask,vox[mask[selected]])
                parts["difference"]=means
                for k,yy in parts.items():
                    summary=one(s for s in read(KIT/"sources/fig3/activation_components.tsv") if s["component"]==k)
                    must(np.isclose((np.linalg.pinv(x)@yy)[names.index(term)],float(summary["beta"]),rtol=0,atol=1e-7),
                         "Activation component differs")
                write_table(prv/"Fig3_winning_COPEs.tsv",[dict(subject=s,adi=v["adi"][i],mspss=v["mspss"][i],
                    **{k:float(y[i]) for k,y in parts.items()}) for i,s in enumerate(ids)])
            else:
                stem="Fig2_FEVS_at_mean_PM25_domain_by_valence_z3p1_negative"
                saved=read(ROOT/"work/katie-results-ready-v1/vs-components-participant-diagnostics.tsv")
                must(len(saved)==3*len(ids),"Incomplete original scatter extraction")
                pts=[]; bands=[]; fig2,axes=render.plt.subplots(1,3,sharex=True,sharey=True,figsize=(13,4),layout="constrained")
                ys={}
                for ax,comp,title in zip(axes,("socialdoors","doors","difference"),
                                          ("Social win − loss","Nonsocial win − loss","Social − nonsocial valence")):
                    rows=[a for a in saved if a["component"]==comp]
                    must([a["subject"] for a in rows]==ids,"FEVS extraction order differs")
                    yy=ys[comp]=np.array([float(a["region_estimate"]) for a in rows])
                    if comp=="difference":
                        must(np.allclose(yy,means,rtol=0,atol=1e-8),"FEVS original fixed region differs")
                    else:
                        for s,y in zip(ids,yy):
                            receipt=ROOT/"derivatives/fsl/randomise/katie-remaining-v1/ppi-l1"/f"sub-{s}_ses-01_task-{comp}_run-1"/"success.json"
                            l1=json.loads(check(receipt).read_text())
                            must((l1["job"]["subject"],l1["job"]["task"])==(s,comp),"Wrong PPI component")
                            image=nib.load(check(Path(l1["feat"])/"stats/cope4.nii.gz"))
                            old.base.grid(ref,image)
                            must(np.isclose(image.get_fdata()[mask].mean(),y,rtol=0,atol=1e-8),"Native VS extraction differs")
                    # Reconstruct the existing descriptive scatter adjustment and compare to its sealed estimates.
                    fit=sm.OLS(yy,x).fit().get_robustcov_results(cov_type="HC3",use_t=True)
                    j=names.index("fevs")
                    eff=one(a for a in read(KIT/"sources/fig2/vs_component_estimates.tsv") if a["component"]==comp)
                    must(np.allclose([fit.params[j],*fit.conf_int()[j]],[float(eff[k]) for k in
                         ("beta","hc3_lower","hc3_upper")],rtol=0,atol=1e-9),"Scatter fit differs")
                    adj=fit.resid+fit.params[0]+fit.params[j]*x[:,j]
                    xx=np.linspace(v["fevs"].min(),v["fevs"].max(),101)
                    vec=np.zeros((101,x.shape[1])); vec[:,0]=1; vec[:,j]=xx-v["fevs"].mean()
                    line=vec@fit.params; half=t.ppf(.975,fit.df_resid)*np.sqrt(np.einsum("ij,jk,ik->i",vec,fit.cov_params(),vec))
                    ax.scatter(v["fevs"],adj,s=15,alpha=.65,color=render.TEAL)
                    render.band(ax,xx,line,line-half,line+half,render.TEAL,None)
                    ax.set(title=title,xlabel="FEVS")
                    pts.extend(dict(subject=s,component=comp,fevs=float(f),raw_cope=float(a),adjusted_cope=float(b))
                               for s,f,a,b in zip(ids,v["fevs"],yy,adj))
                    bands.extend(dict(component=comp,fevs=f,estimate=a,hc3_lower=a-h,hc3_upper=a+h) for f,a,h in zip(xx,line,half))
                must(np.allclose(ys["socialdoors"]-ys["doors"],means,atol=1e-6,rtol=1e-6),"Component difference differs")
                axes[0].set_ylabel("Model-adjusted fixed-region COPE")
                write_table(prv/"Fig2_VS_PPI_components_and_adjusted_points.tsv",pts)
                write_table(prv/"Fig2_scatter_lines_and_bands.tsv",bands)
                for fmt in ("svg","pdf"): fig2.savefig(prv/("Fig2B_editable."+fmt))
                render.plt.close(fig2)
            export_image(pub/(stem+"_mask.nii.gz"),ref,mask.astype("uint8"))
            export_image(pub/(stem+"_signed-t.nii.gz"),ref,np.where(mask,stat*(1 if direction=="positive" else -1),0).astype("float32"))
            index_rows.append(dict(stem=stem,job=job["key"],tstat=index,direction=direction,voxels=r["voxels"],
                                   cluster_p=r["cluster_fwe_p_min"],peak_mni_mm=",".join(r["peak_"+a+"_mm"] for a in "xyz")))
    must(len(index_rows)==12 and len(vs_rows)==970,"Incomplete export")
    for row in read(KIT/"sources/fig4/vs_cluster_overlap.tsv"):
        ov=old.overlap(all_regions[row["a"]],all_regions[row["b"]])
        must(ov["shared_voxels"]==int(row["shared_voxels"]) and np.isclose(ov["dice"],float(row["dice"])),
             "Exported masks do not reproduce Figure 4")
    write_table(prv/"Fig4_VS_PPI_by_cluster.tsv",vs_rows)
    write_table(pub/"maps.tsv",index_rows)

def run():
    os.umask(0)
    OUT.parent.mkdir(exist_ok=True)
    if OUT.exists():
        seal=json.loads((OUT/"manifest.json").read_text())
        files={str(p.relative_to(OUT)):sha(p) for p in OUT.glob("*/*") if p.is_file()}
        must(files==seal and len(list((OUT/"group-maps").glob("*.nii.gz")))==24,"Saved figure export differs")
        print("Verified existing figure-source export:",OUT);return
    stage=Path(tempfile.mkdtemp(dir=OUT.parent,prefix=".katie-figure-sources-"))
    make(stage)
    files={str(p.relative_to(stage)):sha(p) for p in stage.glob("*/*") if p.is_file()}
    (stage/"manifest.json").write_text(json.dumps(files,sort_keys=True,indent=2)+"\n")
    stage.chmod(0o777)
    stage.rename(OUT)
    print("Verified 12 fixed regions, 24 native NIfTIs and N=97 extractions:",OUT)

if __name__=="__main__":
    run()
