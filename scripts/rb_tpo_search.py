"""Grammar B/C search: TPO state (+ optional VWAP state) + first eligible
1m/3m/5m RB trigger. Full candidate stream, occupancy rerun per config."""
import pickle, numpy as np, json, csv
from collections import defaultdict
OUT="artifacts/rb_refinement"
C=pickle.load(open("artifacts/broad_discovery/candidates_with_features.pkl","rb"))
C=[c for c in C if c["risk"]>=12.0]
C.sort(key=lambda z:(z["entry_ts"],z["fkey"]))
store=pickle.load(open(f"{OUT}/tpo_store.pkl","rb"))
def segidx(g): return int(g.split("::")[0][3:6])
TP={bs:{k:np.full(len(C),np.nan) for k in ("poc","vah","val","ppoc","pvah","pval")} for bs in (1,2,4)}
for i,c in enumerate(C):
    si=segidx(c["gvid"]); S=store.get(si)
    if not S: continue
    j=S["ts_index"].get(c["entry_ts"])
    if j is None or j<1: continue
    for bs in (1,2,4):
        for k in TP[bs]:
            TP[bs][k][i]=S["tpo"][bs][k][j-1]     # causal shift
a=lambda k,f=None: np.array([(f(c) if f else c[k]) for c in C])
ent=a(None,lambda c:c["entry_ts"].value); ext=a(None,lambda c:c["exit_ts"].value)
pts=a("points"); rsk=a("risk"); yr=a(None,lambda c:c["sd"].year); px=a("_px")
sess=a("session"); cf=a(None,lambda c:c["fkey"][2]); ctf=a("context_tf"); dirn=a("direction")
atr=rsk.copy()
weeks=(C[-1]["sd"]-C[0]["sd"]).days/7
BASE=(sess=="NY_AM")&(cf=="rb")&np.isin(ctf,[1,3,5])
def zs(an):
    v=a(f"vwap_{an}"); s=np.maximum(a(f"vwsd_{an}"),1e-9); return (px-v)/s
Z930=zs("CASH_0930"); ZLON=zs("LONDON_0300"); ema1=a("ema21_1")
def ev(mask):
    idx=np.flatnonzero(mask&BASE); ch=[];until=-1
    for i in idx:
        if ent[i]<until: continue
        ch.append(i); until=ext[i]
    if len(ch)<300: return None
    ci=np.array(ch); o={"trades":len(ci),"per_week":len(ci)/weeks}
    for cost in (0.0,1.0,2.0):
        r=(pts[ci]-cost)/rsk[ci]; p=r[r>0].sum(); n=-r[r<=0].sum()
        yv=defaultdict(float)
        for y,x in zip(yr[ci],r): yv[y]+=x
        eq=np.cumsum(r); t=f"{cost:g}"
        o[f"pf{t}"]=float(p/n) if n>0 else 0.0; o[f"net{t}"]=float(r.sum())
        o[f"mdd{t}"]=float((eq-np.maximum.accumulate(eq)).min())
        o[f"posyr{t}"]=int(sum(1 for v in yv.values() if v>0))
        o[f"best_year_share{t}"]=float(max(yv.values())/max(1e-9,sum(v for v in yv.values() if v>0)))
    return o
res=[];cid=0
def add(fam,desc,mask):
    global cid; cid+=1
    m=ev(mask); rec={"config_id":f"T{cid:04d}","grammar":fam,"desc":desc,
                     "status":"EVALUATED" if m else "TOO_FEW"}
    if m: rec.update(m)
    res.append(rec)
add("BASE","RB-K1 benchmark (09:30 VWAP <1sd)",np.abs(Z930)<1.0)
for bs in (1,2,4):
    P=TP[bs]
    for prof,pk,vh,vl in (("dev",P["poc"],P["vah"],P["val"]),("prior",P["ppoc"],P["pvah"],P["pval"])):
        dpoc=np.abs(px-pk)/np.maximum(atr,1e-9)
        inval=(px<=vh)&(px>=vl)
        for nm,m in (("inside_value",inval),("above_VAH",px>vh),("below_VAL",px<vl),
                     ("within_0.25ATR_POC",dpoc<0.25),("within_0.50ATR_POC",dpoc<0.50),
                     ("0.5-1.0ATR_from_POC",(dpoc>=0.5)&(dpoc<1.0)),("gt_1ATR_from_POC",dpoc>=1.0),
                     ("above_POC",px>pk),("below_POC",px<pk)):
            add("B",f"TPO {prof} bin{bs}: {nm}",np.nan_to_num(m,nan=False).astype(bool))
            add("C",f"TPO {prof} bin{bs}: {nm} + 09:30VWAP<1sd",
                np.nan_to_num(m,nan=False).astype(bool)&(np.abs(Z930)<1.0))
            add("C",f"TPO {prof} bin{bs}: {nm} + LONVWAP<1sd + EMA",
                np.nan_to_num(m,nan=False).astype(bool)&(np.abs(ZLON)<1.0)
                &np.where(dirn>0,px>ema1,px<ema1))
print(f"configs: {cid}",flush=True)
json.dump(res,open(f"{OUT}/tpo_results.json","w"),default=str)
ev_=[r for r in res if r["status"]=="EVALUATED"]
print(f"evaluated: {len(ev_)}")
gate=[r for r in ev_ if r["posyr1"]==8 and r["pf1"]>=1.30 and r["pf2"]>=1.15
      and r["posyr2"]>=7 and r["per_week"]>=2.5 and r["best_year_share2"]<=0.40]
gate.sort(key=lambda r:-r["pf2"])
print(f"\nPASSING FULL SELECTION GATE: {len(gate)}")
print(f"{'cfg':<7}{'desc':<56}{'n':>6}{'/wk':>6}{'PF1':>8}{'PF2':>8}{'net2':>8}{'MDD2':>8}{'py2':>5}")
for r in gate[:18]:
    print(f"{r['config_id']:<7}{r['desc'][:55]:<56}{r['trades']:>6}{r['per_week']:>6.2f}"
          f"{r['pf1']:>8.4f}{r['pf2']:>8.4f}{r['net2']:>+8.1f}{r['mdd2']:>8.1f}{r['posyr2']:>4}/8")
