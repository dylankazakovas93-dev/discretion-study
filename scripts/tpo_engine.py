"""Causal TPO (time-at-price) profile engine. NOT volume profile.

Each completed 30-minute bracket marks every price bin between its low and high
exactly ONCE, regardless of volume or repeated touches. Developing profiles use
only brackets that have already closed at the decision timestamp.
Development years only.
"""
from __future__ import annotations
import numpy as np, pickle, os, json
from collections import defaultdict

DEV=(2018,2025); SEG="artifacts/multiyear_validation_v2/segcache"
FEAT="artifacts/broad_discovery"; OUT="artifacts/rb_refinement"
os.makedirs(OUT,exist_ok=True)

def brackets(ts,h,l,anchor_hh,anchor_mm):
    """(bracket_id, start_idx, end_idx) for completed 30m brackets, reset daily
    at the anchor."""
    n=len(ts); ids=np.empty(n,dtype=np.int64)
    for i,t in enumerate(ts):
        mins=t.hour*60+t.minute; a=anchor_hh*60+anchor_mm
        d=t.date().toordinal() if mins>=a else t.date().toordinal()-1
        off=(mins-a)%1440
        ids[i]=d*100+(off//30)
    out=[];cur=None;st=0
    for i in range(n):
        if ids[i]!=cur:
            if cur is not None: out.append((cur,st,i-1))
            cur=ids[i]; st=i
    out.append((cur,st,n-1))
    return out

def profile_stats(counts,bin_sz,price_bin):
    """POC (deterministic tie-break: lowest price bin), 70% TPO value area."""
    if not counts: return None
    bins=sorted(counts)
    vals=np.array([counts[b] for b in bins]); mx=vals.max()
    poc_candidates=[b for b in bins if counts[b]==mx]
    poc=poc_candidates[len(poc_candidates)//2]        # deterministic: median of ties
    total=vals.sum(); target=0.70*total
    lo=hi=bins.index(poc); acc=counts[poc]
    while acc<target and (lo>0 or hi<len(bins)-1):
        up=counts[bins[hi+1]] if hi<len(bins)-1 else -1
        dn=counts[bins[lo-1]] if lo>0 else -1
        if up>=dn and hi<len(bins)-1: hi+=1; acc+=up
        elif lo>0: lo-=1; acc+=dn
        else: break
    return {"poc":poc*bin_sz,"val":bins[lo]*bin_sz,"vah":bins[hi]*bin_sz,
            "hi":bins[-1]*bin_sz,"lo":bins[0]*bin_sz,
            "at_price":counts.get(price_bin,0),"max":int(mx)}

def build_tpo(ts,h,l,bin_sz,anchor=(9,30)):
    """Returns per-bar dict of causal developing-profile stats + prior-day stats."""
    br=brackets(ts,h,l,*anchor)
    n=len(ts)
    poc=np.full(n,np.nan); vah=np.full(n,np.nan); val=np.full(n,np.nan)
    ppoc=np.full(n,np.nan); pvah=np.full(n,np.nan); pval=np.full(n,np.nan)
    counts=defaultdict(int); day=None; prior=None
    for (bid,s,e) in br:
        d=bid//100
        if d!=day:
            if counts: prior=profile_stats(dict(counts),bin_sz,0)
            counts=defaultdict(int); day=d
        # stats visible DURING this bracket are from previously CLOSED brackets
        cur=profile_stats(dict(counts),bin_sz,0) if counts else None
        for i in range(s,e+1):
            if cur:
                poc[i]=cur["poc"]; vah[i]=cur["vah"]; val[i]=cur["val"]
            if prior:
                ppoc[i]=prior["poc"]; pvah[i]=prior["vah"]; pval[i]=prior["val"]
        blo=int(np.floor(l[s:e+1].min()/bin_sz)); bhi=int(np.floor(h[s:e+1].max()/bin_sz))
        for b in range(blo,bhi+1): counts[b]+=1      # each bin once per bracket
    return {"poc":poc,"vah":vah,"val":val,"ppoc":ppoc,"pvah":pvah,"pval":pval}

if __name__=="__main__":
    man=json.load(open(os.path.join(SEG,"manifest.json")))
    store={}
    for si in range(man["n_segments"]):
        fp=os.path.join(FEAT,f"feat_{si:03d}.pkl")
        if not os.path.exists(fp): continue
        D=pickle.load(open(fp,"rb"))
        if D.get("empty"): continue
        bars=pickle.load(open(os.path.join(SEG,f"seg{si:03d}.pkl"),"rb"))
        ts=[b.ts_et for b in bars]
        h=D["feat"]["high"].astype(float); l=D["feat"]["low"].astype(float)
        seg={}
        for bs in (1,2,4):
            T=build_tpo(ts,h,l,bs)
            seg[bs]={k:v.astype(np.float32) for k,v in T.items()}
        store[si]={"tpo":seg,"ts_index":D["ts_index"]}
        print(f"seg{si:03d} TPO built",flush=True)
    pickle.dump(store,open(os.path.join(OUT,"tpo_store.pkl"),"wb"))
    print("TPO engine complete",flush=True)
