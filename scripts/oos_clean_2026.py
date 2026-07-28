"""CLEAN OOS: 2026-06-08 -> 2026-07-17, never previously ingested.

Observer is warmed up from 2026-04-19 so structures exist before the scoring
window opens; only trades with session_date >= 2026-06-08 are scored.
Rule: FROZEN RB-K1 (docs/FROZEN_MANUAL_RULE_V1.md lineage, RB-restricted).
"""
import os, sys, pickle, dataclasses, numpy as np, importlib.util
import zstandard as zs, io, pandas as pd
from collections import defaultdict
sys.path.insert(0,"src")
from discretion.data.loader import read_raw_csv, ET
from discretion.data.bars import Bar
from discretion.setup_observer.observer import observe
from discretion.setup_observer.outcomes import process_outcome
fe=importlib.util.spec_from_file_location("fe","scripts/feature_engine.py")
FE=importlib.util.module_from_spec(fe); fe.loader.exec_module(FE)

SRC="/root/.claude/uploads/6bbfe5fa-ed66-5075-a056-4af4be88eb35/dc21205c-glbxmdp32026041920260718.ohlcv1m.csv.zst"
WARM="2026-04-19"; SCORE_FROM=pd.Timestamp("2026-06-08").date()
rows=[]
with open(SRC,'rb') as fh:
    t=io.TextIOWrapper(zs.ZstdDecompressor().stream_reader(fh),encoding='utf-8')
    import csv as _c
    for r in _c.DictReader(t):
        if not r["symbol"].startswith("NQ"): continue
        if len(r["symbol"])!=4: continue          # front-month outrights only
        rows.append((r["ts_event"],r["symbol"],float(r["open"]),float(r["high"]),
                     float(r["low"]),float(r["close"]),int(float(r["volume"]))))
print(f"raw NQ 1m rows: {len(rows):,}",flush=True)
df=pd.DataFrame(rows,columns=["ts","sym","o","h","l","c","v"])
df["ts"]=pd.to_datetime(df["ts"],utc=True)
df=df.sort_values("ts")
# front month = highest-volume contract per session day
df["d"]=df["ts"].dt.tz_convert(ET).dt.date
vol=df.groupby(["d","sym"])["v"].sum().reset_index()
front=vol.sort_values("v").groupby("d").tail(1).set_index("d")["sym"].to_dict()
df=df[df.apply(lambda r: front.get(r["d"])==r["sym"],axis=1)]
print(f"front-month rows: {len(df):,}  {df['d'].min()} -> {df['d'].max()}",flush=True)
bars=[];seq=0;prev=None;segid=0
for _,r in df.iterrows():
    if prev is not None and r["sym"]!=prev: segid+=1; seq=0
    bars.append(Bar(seq=seq,ts_utc=r["ts"],ts_et=r["ts"].tz_convert(ET),open=r["o"],
                    high=r["h"],low=r["l"],close=r["c"],volume=r["v"],
                    contract=r["sym"],segment_id=segid))
    seq+=1; prev=r["sym"]
print(f"bars: {len(bars):,}, segments: {segid+1}",flush=True)
segs=defaultdict(list)
for b in bars: segs[b.segment_id].append(b)
allc=[]
for sid,sb in sorted(segs.items()):
    local=[dataclasses.replace(b,seq=i,segment_id=0) for i,b in enumerate(sb)]
    print(f"  observing segment {sid} ({len(local):,} bars)...",flush=True)
    _e,variants,_d=observe(local,target_window=600)
    F=FE.segment_features(local); ti={b.ts_et:i for i,b in enumerate(local)}
    for v in variants:
        if not v.executable: continue
        o=process_outcome(v,local)
        if o is None or o.r_multiple==0: continue
        risk=abs(o.points/o.r_multiple)
        if risk<12.0: continue
        j=ti.get(v.entry_ts,-1)
        if j<1: continue
        px=float(F["close"][j-1]); vw=float(F["vwap_CASH_0930"][j-1])
        sd=max(float(F["vwsd_CASH_0930"][j-1]),1e-9)
        allc.append({"sd":v.session_date_et,"e":v.entry_ts,"x":o.exit_ts,"fk":(v.lane,v.direction,
                     v.context_family,v.session,v.entry_variant,v.reaction_state),
                     "pts":o.points,"risk":risk,"sess":v.session,"cf":v.context_family,
                     "ctf":v.context_tf,"z":(px-vw)/sd})
    print(f"  segment {sid}: {len(allc):,} cumulative eligible candidates",flush=True)
pickle.dump(allc,open("artifacts/rb_refinement/oos_clean_candidates.pkl","wb"))
sel=[r for r in allc if r["sess"]=="NY_AM" and r["cf"]=="rb" and r["ctf"] in (1,3,5) and abs(r["z"])<1.0]
sel.sort(key=lambda z:(z["e"],z["fk"]))
ch=[];until=None
for r in sel:
    if until is not None and r["e"]<until: continue
    ch.append(r); until=r["x"]
sc=[t for t in ch if t["sd"]>=SCORE_FROM]
print(f"\nRB-K1 trades in FULL ingested range: {len(ch)}")
print(f"RB-K1 trades in CLEAN window (>= {SCORE_FROM}): {len(sc)}")
if sc:
    d=(sc[-1]["sd"]-sc[0]["sd"]).days or 1
    print(f"\n=== CLEAN OOS {sc[0]['sd']} -> {sc[-1]['sd']} ({len(sc)} trades, {len(sc)/(d/7):.2f}/wk) ===")
    for cost in (0.0,1.0,2.0):
        rr=np.array([(t["pts"]-cost)/t["risk"] for t in sc])
        p=rr[rr>0].sum(); n=-rr[rr<=0].sum()
        print(f"  @{cost:g}pt  PF={(p/n if n>0 else 0):.4f}  net={rr.sum():+7.1f}R  "
              f"exp={rr.mean():+.4f}R  win={100*(rr>0).mean():.1f}%")
    rr2=np.array([(t["pts"]-2.0)/t["risk"] for t in sc])
    p=rr2[rr2>0].sum(); n=-rr2[rr2<=0].sum(); pf2=p/n if n>0 else 0
    v="PASS" if (pf2>1.10 and rr2.sum()>0) else ("MARGINAL" if pf2>=1.0 else "FAIL")
    print(f"\n  PRE-REGISTERED VERDICT (PF@2pt>1.10 and net>0): {v}")
