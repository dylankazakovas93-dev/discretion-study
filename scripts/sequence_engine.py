"""Native ordered-event-sequence engine.

Candidates are created BECAUSE an ordered sequence of causal events occurred.
No existing FVG/iFVG/RB candidate is consumed. Entry, stop, target and outcome
are all constructed by this module from completed bars.

CAUSALITY: event_asof <= decision < entry. Entry is the OPEN of the next 1m bar
after final confirmation. Outcomes are stop-first on same-bar ambiguity.
HOLDOUT: development years only.
"""
from __future__ import annotations
import numpy as np, pickle, os, json
from collections import defaultdict

DEV=(2018,2025); SEG="artifacts/multiyear_validation_v2/segcache"
FEAT="artifacts/broad_discovery"; OUT="artifacts/sequence_discovery"
os.makedirs(OUT,exist_ok=True)
MIN_STOP=12.0; MAX_HOLD=480

def atr_wilder(h,l,c,n=24):
    m=len(c); tr=np.zeros(m)
    for i in range(1,m):
        tr[i]=max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1]))
    o=np.zeros(m); s=0.0
    for i in range(m):
        s=tr[i] if i==0 else (s*(n-1)+tr[i])/n
        o[i]=s
    return o

def simulate(bars_h,bars_l,bars_o,i_entry,direction,stop,target):
    """Stop-first outcome from next-bar open. Returns (exit_type, points)."""
    n=len(bars_h); end=min(n-1,i_entry+MAX_HOLD)
    entry=bars_o[i_entry]
    for s in range(i_entry,end+1):
        if direction>0:
            hs=bars_l[s]<=stop; ht=bars_h[s]>=target
        else:
            hs=bars_h[s]>=stop; ht=bars_l[s]<=target
        if hs: return "STOP",(stop-entry) if direction>0 else (entry-stop)
        if ht: return "TARGET",(target-entry) if direction>0 else (entry-target)
    px=bars_o[end]
    return "TIME",(px-entry) if direction>0 else (entry-px)

def build_events(F,c,h,l,atr1,anchor,band_k):
    """VWAP band events for one anchor/band. Returns arrays of bar indices."""
    vw=F[f"vwap_{anchor}"].astype(float); sd=np.maximum(F[f"vwsd_{anchor}"].astype(float),1e-9)
    up=vw+band_k*sd; dn=vw-band_k*sd
    closed_above=c>up; closed_below=c<dn
    # EXTENSION: first completed close beyond band (state entry)
    ext_up=np.flatnonzero(closed_above[1:] & ~closed_above[:-1])+1
    ext_dn=np.flatnonzero(closed_below[1:] & ~closed_below[:-1])+1
    # REVERSION: first completed close back inside after being beyond
    rev_dn=np.flatnonzero(~closed_above[1:] & closed_above[:-1])+1   # was above -> back inside => SHORT
    rev_up=np.flatnonzero(~closed_below[1:] & closed_below[:-1])+1   # was below -> back inside => LONG
    return {"ext_up":ext_up,"ext_dn":ext_dn,"rev_dn":rev_dn,"rev_up":rev_up,
            "vw":vw,"up":up,"dn":dn}

def family_A(F,bars,atr1,cfg):
    """Family A native: band extension -> close back inside -> optional EMA
    confirmation -> next-bar entry. Direction is TOWARD vwap."""
    c=F["close"].astype(float); h=F["high"].astype(float); l=F["low"].astype(float)
    o=np.array([b.open for b in bars]); ts=[b.ts_et for b in bars]
    E=build_events(F,c,h,l,atr1,cfg["anchor"],cfg["band"])
    ema=F[f"ema21_{cfg['ema_tf']}"].astype(float) if cfg["ema_tf"] else None
    W=cfg["window"]; out=[]
    for side,ext_arr,rev_arr,d in (("up",E["ext_up"],E["rev_dn"],-1),
                                   ("dn",E["ext_dn"],E["rev_up"],+1)):
        ri=0
        for a in ext_arr:
            while ri<len(rev_arr) and rev_arr[ri]<=a: ri+=1
            if ri>=len(rev_arr): break
            b=rev_arr[ri]
            if b-a>W: continue                      # expiry: reversion too late
            conf=b
            if ema is not None:                     # ordered EMA confirmation
                k=b; found=-1
                while k<min(len(c),b+cfg["ema_window"]+1):
                    if (d<0 and c[k]<ema[k]) or (d>0 and c[k]>ema[k]): found=k; break
                    k+=1
                if found<0: continue
                conf=found
            i=conf+1                                # NEXT-BAR ENTRY
            if i>=len(c)-1: continue
            if not (DEV[0]<=ts[i].year<=DEV[1]): continue
            ext_px=(h[a:conf+1].max() if d<0 else l[a:conf+1].min())
            entry=o[i]
            raw=abs(entry-ext_px)
            stop_d=max(raw,atr1[i-1],MIN_STOP)
            stop=entry-stop_d if d>0 else entry+stop_d
            tm=cfg["target"]
            if tm=="vwap": tgt=E["vw"][i-1]
            elif tm=="1R": tgt=entry+d*stop_d
            elif tm=="1.5R": tgt=entry+d*1.5*stop_d
            elif tm=="2R": tgt=entry+d*2.0*stop_d
            else: raise ValueError(tm)
            if (d>0 and tgt<=entry) or (d<0 and tgt>=entry): continue
            if abs(tgt-entry)<atr1[i-1]: continue   # 1m ATR minimum target distance
            xt,pnl=simulate(h,l,o,i,d,stop,tgt)
            out.append({"i":i,"ts":ts[i],"sd":ts[i].date(),"dir":d,"points":pnl,
                        "risk":stop_d,"exit_type":xt,"a":a,"b":b,"conf":conf})
    return out

if __name__=="__main__":
    import sys
    cfg=json.loads(sys.argv[1]) if len(sys.argv)>1 else {
        "anchor":"CASH_0930","band":1,"window":10,"ema_tf":1,"ema_window":5,"target":"vwap"}
    man=json.load(open(os.path.join(SEG,"manifest.json")))
    allc=[]
    for si in range(man["n_segments"]):
        fp=os.path.join(FEAT,f"feat_{si:03d}.pkl")
        if not os.path.exists(fp): continue
        D=pickle.load(open(fp,"rb"))
        if D.get("empty"): continue
        bars=pickle.load(open(os.path.join(SEG,f"seg{si:03d}.pkl"),"rb"))
        F=D["feat"]
        h=F["high"].astype(float); l=F["low"].astype(float); c=F["close"].astype(float)
        atr1=atr_wilder(h,l,c,24)
        allc.extend(family_A(F,bars,atr1,cfg))
    allc.sort(key=lambda z:z["ts"])
    print(f"native candidates generated: {len(allc):,}")
    if allc:
        r=[x["points"]/x["risk"] for x in allc]
        pos=sum(v for v in r if v>0); neg=-sum(v for v in r if v<=0)
        print(f"pre-occupancy PF(gross)={pos/neg:.4f}  n={len(r)}")
    pickle.dump(allc,open(os.path.join(OUT,"probe_family_A.pkl"),"wb"))
