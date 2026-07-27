"""Causal AMD state machine: Accumulation -> Manipulation -> Distribution.

Every stage is confirmed on COMPLETED bars only. An accumulation range is
unknown until its final bar closes (activation_time), so no earlier bar can
use the future-known high/low. Manipulation must follow activation;
distribution must follow manipulation completion. Development years only.
"""
from __future__ import annotations
import numpy as np, pickle, os, json
from collections import defaultdict
DEV=(2018,2025); SEG="artifacts/multiyear_validation_v2/segcache"
FEAT="artifacts/broad_discovery"; OUT="artifacts/rb_refinement"

def resample(ts,h,l,c,tf):
    """Completed tf-bars -> (hi,lo,cl,end_1m_index). Bar k is knowable only
    from 1m index end[k]+1 onward."""
    if tf==1: return h.copy(),l.copy(),c.copy(),np.arange(len(c))
    key=np.array([t.date().toordinal()*10000+((t.hour*60+t.minute)//tf) for t in ts])
    hs=[];ls=[];cs=[];en=[];cur=None;ch=cl=cc=None
    for i in range(len(c)):
        if key[i]!=cur:
            if cur is not None: hs.append(ch);ls.append(cl);cs.append(cc);en.append(i-1)
            cur=key[i];ch=h[i];cl=l[i];cc=c[i]
        else:
            ch=max(ch,h[i]);cl=min(cl,l[i]);cc=c[i]
    hs.append(ch);ls.append(cl);cs.append(cc);en.append(len(c)-1)
    return np.array(hs),np.array(ls),np.array(cs),np.array(en)

def atr_w(h,l,c,n=24):
    m=len(c);tr=np.zeros(m)
    for i in range(1,m): tr[i]=max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1]))
    o=np.zeros(m);s=0.0
    for i in range(m):
        s=tr[i] if i==0 else (s*(n-1)+tr[i])/n
        o[i]=s
    return o

def amd_instances(H,L,C,END,ATR,cfg):
    """Returns list of dicts, one per completed AMD instance."""
    n=len(C); LEN=cfg["length"]; WID=cfg["width"]; EXC=cfg["excursion"]
    MW=cfg["manip_window"]; DIST=cfg["dist"]; out=[]
    for a in range(LEN,n-1):
        s=a-LEN
        rh=H[s:a].max(); rl=L[s:a].min()
        if ATR[a-1]<=0: continue
        if (rh-rl)/ATR[a-1]>WID: continue          # accumulation must be tight
        mid=(rh+rl)/2.0
        # ACTIVATION at close of bar a-1; scan forward for manipulation
        mi=-1; side=0
        for k in range(a,min(n,a+MW+1)):
            if H[k]>=rh+EXC*ATR[a-1]: mi=k; side=+1; break
            if L[k]<=rl-EXC*ATR[a-1]: mi=k; side=-1; break
        if mi<0: continue
        # manipulation completion: completed close back inside the range
        ri=-1
        for k in range(mi,min(n,mi+MW+1)):
            if rl<=C[k]<=rh: ri=k; break
        if ri<0: continue
        d=-side                                     # reversal AMD
        # distribution confirmation AFTER re-entry
        di=-1
        for k in range(ri+1,min(n,ri+MW+1)):
            if DIST=="midpoint":
                if (d>0 and C[k]>mid) or (d<0 and C[k]<mid): di=k;break
            else:
                if (d>0 and C[k]>rh) or (d<0 and C[k]<rl): di=k;break
        if di<0: continue
        out.append({"conf_1m":int(END[di]),"dir":int(d),"rh":float(rh),"rl":float(rl),
                    "expiry_1m":int(END[min(n-1,di+cfg["rb_window"])])})
    return out

if __name__=="__main__":
    man=json.load(open(os.path.join(SEG,"manifest.json")))
    GRID=[]
    for tf in (1,3,5):
      for length in (12,18,24):
        for width in (1.0,1.5):
          for exc in (0.0,0.25):
            for mw in (6,12):
              for dist in ("midpoint","opposite"):
                for rbw in (6,12):
                  GRID.append({"tf":tf,"length":length,"width":width,"excursion":exc,
                               "manip_window":mw,"dist":dist,"rb_window":rbw})
    print(f"AMD configs: {len(GRID)}",flush=True)
    json.dump(GRID,open(os.path.join(OUT,"amd_grid.json"),"w"))
    store=defaultdict(dict)
    for si in range(man["n_segments"]):
        fp=os.path.join(FEAT,f"feat_{si:03d}.pkl")
        if not os.path.exists(fp): continue
        D=pickle.load(open(fp,"rb"))
        if D.get("empty"): continue
        bars=pickle.load(open(os.path.join(SEG,f"seg{si:03d}.pkl"),"rb"))
        ts=[b.ts_et for b in bars]
        h=D["feat"]["high"].astype(float); l=D["feat"]["low"].astype(float); c=D["feat"]["close"].astype(float)
        cache={}
        for gi,cfg in enumerate(GRID):
            k=(cfg["tf"],)
            if k not in cache:
                H,L,C,E=resample(ts,h,l,c,cfg["tf"]); cache[k]=(H,L,C,E,atr_w(H,L,C,24))
            H,L,C,E,A=cache[k]
            store[gi][si]=amd_instances(H,L,C,E,A,cfg)
        print(f"seg{si:03d} AMD done",flush=True)
    pickle.dump(dict(store),open(os.path.join(OUT,"amd_store.pkl"),"wb"))
    tot=sum(len(v) for g in store.values() for v in g.values())
    print(f"AMD engine complete. total instances across all configs: {tot:,}",flush=True)
