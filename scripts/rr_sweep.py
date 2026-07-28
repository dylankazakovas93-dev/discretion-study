"""RB-K1 target sweep: fixed kR targets vs the frozen structural target.
entry_price = open of the entry bar (variants.py:187), so outcomes re-simulate
exactly from segcache bars. Stop UNCHANGED. Stop-first. Occupancy re-run per k.
"""
import pickle, numpy as np, os
from collections import defaultdict
SEG="artifacts/multiyear_validation_v2/segcache"; OUT="artifacts/rb_refinement"
MAXH=480; KS=[0.5,0.7,1.0,1.5,2.0]
C=pickle.load(open("artifacts/broad_discovery/candidates_with_features.pkl","rb"))
C=[c for c in C if c["risk"]>=12.0 and c["session"]=="NY_AM"
   and c["fkey"][2]=="rb" and c["context_tf"] in (1,3,5)]
px=np.array([c["_px"] for c in C]); vw=np.array([c["vwap_CASH_0930"] for c in C])
sd=np.maximum(np.array([c["vwsd_CASH_0930"] for c in C]),1e-9)
C=[c for c,z in zip(C,(px-vw)/sd) if abs(z)<1.0]
print(f"RB-K1 candidate stream: {len(C):,}",flush=True)
bysec=defaultdict(list)
for c in C: bysec[int(c["gvid"].split("::")[0][3:6])].append(c)
SIM=defaultdict(list); BASE=[]
for si,grp in sorted(bysec.items()):
    bars=pickle.load(open(f"{SEG}/seg{si:03d}.pkl","rb"))
    o=np.array([b.open for b in bars]); h=np.array([b.high for b in bars]); l=np.array([b.low for b in bars])
    ti={b.ts_et:i for i,b in enumerate(bars)}
    for c in grp:
        i=ti.get(c["entry_ts"],-1)
        if i<0: continue
        BASE.append({"sd":c["sd"],"e":c["entry_ts"],"xts":c["exit_ts"],
                     "pts":c["points"],"risk":c["risk"],"fk":c["fkey"]})
        d=c["direction"]; e=o[i]; risk=c["risk"]; stop=e-d*risk
        for k in KS:
            tgt=e+d*k*risk; end=min(len(o)-1,i+MAXH); xt=None
            for s in range(i,end+1):
                if d>0: hs=l[s]<=stop; ht=h[s]>=tgt
                else:   hs=h[s]>=stop; ht=l[s]<=tgt
                if hs: xt=("STOP",-risk,s); break
                if ht: xt=("TARGET",k*risk,s); break
            if xt is None: xt=("TIME",(o[end]-e)*d,end)
            SIM[k].append({"sd":c["sd"],"e":c["entry_ts"],"xts":bars[xt[2]].ts_et,
                           "pts":xt[1],"risk":risk,"fk":c["fkey"],"xt":xt[0]})
    print(f"  seg{si:03d} done",flush=True)
pickle.dump({"sim":dict(SIM),"base":BASE},open(f"{OUT}/rr_sweep.pkl","wb"))
def report(tr,lab):
    tr=sorted(tr,key=lambda z:(z["e"],z["fk"]))
    ch=[];until=None
    for t in tr:
        if until is not None and t["e"]<until: continue
        ch.append(t); until=t["xts"]
    wk=(ch[-1]["sd"]-ch[0]["sd"]).days/7
    out=f"{lab:<20}{len(ch):>6}{len(ch)/wk:>7.2f}"
    for cost in (1.0,2.0):
        r=np.array([(t["pts"]-cost)/t["risk"] for t in ch])
        p=r[r>0].sum(); n=-r[r<=0].sum()
        yv=defaultdict(float)
        for t,x in zip(ch,r): yv[t["sd"].year]+=x
        eq=np.cumsum(r)
        out+=f"{(p/n if n>0 else 0):>9.4f}{r.sum():>9.1f}{sum(1 for v in yv.values() if v>0):>4}/8"
        if cost==2.0: out+=f"{(eq-np.maximum.accumulate(eq)).min():>9.1f}{100*(r>0).mean():>7.1f}%"
    print(out,flush=True)
print(f"\n{'target':<20}{'n':>6}{'/wk':>7}{'PF@1':>9}{'net@1':>9}{'py1':>6}{'PF@2':>9}{'net@2':>9}{'py2':>6}{'MDD2':>9}{'win':>8}")
report(BASE,"STRUCTURAL (frozen)")
for k in KS: report(SIM[k],f"fixed {k}R")
