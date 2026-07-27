"""Stage 6/7/8: neighbourhood stability, leave-one-year-out, structural increment."""
import pickle, os, numpy as np, json
from collections import defaultdict
exec(open("scripts/sequence_search.py").read().split("results = []")[0])

def occ_idx(mask):
    idx=np.flatnonzero(mask); ch=[];until=-1
    for i in idx:
        if ent[i]<until: continue
        ch.append(i); until=ext[i]
    return np.array(ch)
def stats(ci):
    if len(ci)<200: return None
    o={"trades":len(ci),"per_week":len(ci)/weeks_total}
    for cost in (0.0,1.0,2.0):
        r=(pts[ci]-cost)/rsk[ci]; pos=r[r>0].sum(); neg=-r[r<=0].sum()
        eq=np.cumsum(r); yv=defaultdict(float)
        for y,x in zip(yr[ci],r): yv[y]+=x
        t=f"{cost:g}"
        o[f"pf{t}"]=float(pos/neg) if neg>0 else 0.0
        o[f"net{t}"]=float(r.sum()); o[f"mdd{t}"]=float((eq-np.maximum.accumulate(eq)).min())
        o[f"posyr{t}"]=int(sum(1 for v in yv.values() if v>0))
        o[f"yr{t}"]={int(k):round(v,2) for k,v in sorted(yv.items())}
    return o
def M(s,a,st,extra=None):
    m=(sess==s)&band_mask(a,st,dirn)
    if extra is not None: m=m&extra
    return m
# ---- headline candidates ----
CANDS={
 "K1: NY_AM | inside 1sd of 09:30 VWAP | any structure": M("NY_AM","CASH_0930","inside_1sd"),
 "K2: NY_AM | inside 1sd of 00:00 VWAP | px aligned EMA21(1m)": M("NY_AM","MIDNIGHT_0000","inside_1sd", np.where(dirn>0,px>FEAT["ema21_1"],px<FEAT["ema21_1"])),
 "K3: NY_AM | inside 1sd of 03:00 VWAP | px aligned EMA21(1m)": M("NY_AM","LONDON_0300","inside_1sd", np.where(dirn>0,px>FEAT["ema21_1"],px<FEAT["ema21_1"])),
}
print("=== HEADLINE CANDIDATES ===")
for k,m in CANDS.items():
    s=stats(occ_idx(m))
    print(f"{k}\n   n={s['trades']} /wk={s['per_week']:.1f} PF1={s['pf1']:.4f} PF2={s['pf2']:.4f} "
          f"net1={s['net1']:+.1f} net2={s['net2']:+.1f} MDD1={s['mdd1']:.1f} py1={s['posyr1']}/8 py2={s['posyr2']}/8")
    print(f"   yr@2pt: "+"  ".join(f"{y}:{v:+.1f}" for y,v in s['yr2'].items()))
# ---- Stage 6: neighbourhood of K1 (vary anchor and band state) ----
print("\n=== STAGE 6 NEIGHBOURHOOD: K1 (vary one parameter at a time) ===")
nb=[]
for a in ANCHORS:
    s=stats(occ_idx(M("NY_AM",a,"inside_1sd")))
    if s: nb.append(("anchor="+a,s)); print(f"   anchor {a:<16} n={s['trades']:>5} /wk={s['per_week']:>4.1f} PF1={s['pf1']:.4f} PF2={s['pf2']:.4f} py1={s['posyr1']}/8")
for st in BAND_STATES:
    s=stats(occ_idx(M("NY_AM","CASH_0930",st)))
    if s: nb.append(("band="+st,s)); print(f"   band   {st:<16} n={s['trades']:>5} /wk={s['per_week']:>4.1f} PF1={s['pf1']:.4f} PF2={s['pf2']:.4f} py1={s['posyr1']}/8")
for s_ in SESSIONS:
    s=stats(occ_idx(M(s_,"CASH_0930","inside_1sd")))
    if s: nb.append(("session="+s_,s)); print(f"   session {s_:<15} n={s['trades']:>5} /wk={s['per_week']:>4.1f} PF1={s['pf1']:.4f} PF2={s['pf2']:.4f} py1={s['posyr1']}/8")
pfs=[s["pf1"] for _,s in nb]
k1=stats(occ_idx(CANDS["K1: NY_AM | inside 1sd of 09:30 VWAP | any structure"]))["pf1"]
print(f"\n   neighbourhood n={len(nb)} meanPF1={np.mean(pfs):.4f} medianPF1={np.median(pfs):.4f} sd={np.std(pfs):.4f}")
print(f"   K1 PF1={k1:.4f}  -> within 1 sd of mean: {k1 <= np.mean(pfs)+np.std(pfs)}")
print(f"   %% neighbours profitable @1pt: {100*np.mean([p>1 for p in pfs]):.0f}%")
print(f"   %% neighbours >=6/8 positive yrs: {100*np.mean([s['posyr1']>=6 for _,s in nb]):.0f}%")
# ---- Stage 8: structural incremental value ----
print("\n=== STAGE 8: STRUCTURAL INCREMENTAL VALUE (NY_AM) ===")
vwap_only=M("NY_AM","CASH_0930","inside_1sd")
struct_only=(sess=="NY_AM")
for lab,m in [("VWAP state + any structure (K1)",vwap_only),
              ("structure only, no VWAP state",struct_only),
              ("VWAP state, structural variants restricted to Option3 set",
               vwap_only & np.isin(evar,["ENTRY_ON_IMMEDIATE_DISPLACEMENT","ENTRY_ON_MINIMAL_WICK_REJECTION","ENTRY_ON_STRONG_REJECTION","ENTRY_ON_FIRST_CLOSE_OUTSIDE","ENTRY_ON_NEW_FVG"]))]:
    s=stats(occ_idx(m))
    print(f"   {lab:<58} n={s['trades']:>5} /wk={s['per_week']:>4.1f} PF1={s['pf1']:.4f} PF2={s['pf2']:.4f} py1={s['posyr1']}/8")
# ---- Stage 7: LOYO on K1 (rule is fixed; verify each held-out year) ----
print("\n=== STAGE 7: K1 LEAVE-ONE-YEAR-OUT (rule fixed, evaluated on held-out year) ===")
ci=occ_idx(CANDS["K1: NY_AM | inside 1sd of 09:30 VWAP | any structure"])
for y in range(2018,2026):
    sel=ci[yr[ci]==y]
    r1=(pts[sel]-1.0)/rsk[sel]; r2=(pts[sel]-2.0)/rsk[sel]
    p1=r1[r1>0].sum()/max(1e-9,-r1[r1<=0].sum()); p2=r2[r2>0].sum()/max(1e-9,-r2[r2<=0].sum())
    print(f"   {y}  n={len(sel):>4}  PF@1={p1:.4f} net@1={r1.sum():+7.1f}  PF@2={p2:.4f} net@2={r2.sum():+7.1f}")
