"""AMD v2 -- operator-specified definitions.

Accumulation : >=20 min (>=60 min on 15m), range/ATR24(tf) <= tf-scaled width
Manipulation : SUSTAINED breach -- >=N consecutive completed 1m closes beyond
               the accumulation boundary (5 min low tf, 15 min on 15m)
Gate         : the manipulation extreme must reach a level -- VWAP SD band or EMA21
Distribution : first eligible opposite-direction RB trigger after the sweep ends
All causal, completed bars only, development years only.
"""
import numpy as np, pickle, os, json
from collections import defaultdict
SEG="artifacts/multiyear_validation_v2/segcache"; FEAT="artifacts/broad_discovery"
OUT="artifacts/rb_refinement"
# tf -> (accumulation bars, width x ATR24, sustained-breach minutes)
TFP={1:(20,3.0,5), 3:(7,2.0,5), 5:(4,1.5,5), 15:(4,1.0,15)}

def resample(ts,h,l,c,tf):
    if tf==1: return h.copy(),l.copy(),c.copy(),np.arange(len(c))
    key=np.array([t.date().toordinal()*10000+((t.hour*60+t.minute)//tf) for t in ts])
    hs=[];ls=[];cs=[];en=[];cur=None;ch=cl=cc=None
    for i in range(len(c)):
        if key[i]!=cur:
            if cur is not None: hs.append(ch);ls.append(cl);cs.append(cc);en.append(i-1)
            cur=key[i];ch=h[i];cl=l[i];cc=c[i]
        else: ch=max(ch,h[i]);cl=min(cl,l[i]);cc=c[i]
    hs.append(ch);ls.append(cl);cs.append(cc);en.append(len(c)-1)
    return np.array(hs),np.array(ls),np.array(cs),np.array(en)

def atr_w(h,l,c,n=24):
    m=len(c);tr=np.zeros(m)
    for i in range(1,m): tr[i]=max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1]))
    o=np.zeros(m);s=0.0
    for i in range(m):
        s=tr[i] if i==0 else (s*(n-1)+tr[i])/n; o[i]=s
    return o

def amd_v2(F,ts,tf,wid_mult,sustain,gate,max_wait):
    """Returns list of (sweep_end_1m_idx, distribution_direction, expiry_1m_idx)."""
    h=F["high"].astype(float); l=F["low"].astype(float); c=F["close"].astype(float)
    H,L,C,E=resample(ts,h,l,c,tf); A=atr_w(H,L,C,24)
    LEN=TFP[tf][0]; n1=len(c); out=[]
    # causal level arrays for the gate
    lv=[]
    for an in ("CASH_0930","LONDON_0300"):
        vw=F[f"vwap_{an}"].astype(float); sd=np.maximum(F[f"vwsd_{an}"].astype(float),1e-9)
        for k in (1,2,3): lv += [vw+k*sd, vw-k*sd]
    for t in (1,5,15): lv.append(F[f"ema21_{t}"].astype(float))
    for a in range(LEN,len(C)-1):
        s=a-LEN
        rh=H[s:a].max(); rl=L[s:a].min()
        if A[a-1]<=0 or (rh-rl)/A[a-1]>wid_mult: continue
        i0=E[a-1]+1                                   # activation on 1m grid
        if i0>=n1-1: continue
        # find sustained breach on the 1m grid
        found=None
        for i in range(i0,min(n1,i0+max_wait)):
            if c[i]>rh:
                k=i
                while k<n1 and c[k]>rh: k+=1
                if k-i>=sustain: found=(i,k-1,+1); break
            elif c[i]<rl:
                k=i
                while k<n1 and c[k]<rl: k+=1
                if k-i>=sustain: found=(i,k-1,-1); break
        if not found: continue
        b0,b1,side=found
        if gate:                                       # sweep must reach a level
            ext=h[b0:b1+1].max() if side>0 else l[b0:b1+1].min()
            hit=any((min(arr[b0:b1+1])<=ext<=max(arr[b0:b1+1])) for arr in lv
                    if not np.isnan(arr[b0:b1+1]).all())
            if not hit: continue
        out.append((b1,-side,min(n1-1,b1+max_wait)))
    return out

if __name__=="__main__":
    man=json.load(open(os.path.join(SEG,"manifest.json")))
    GRID=[{"tf":tf,"wid":w,"gate":g,"wait":wt}
          for tf in (1,3,5,15) for w in (TFP[tf][1],TFP[tf][1]*1.5)
          for g in (True,False) for wt in (30,60)]
    print(f"AMD v2 configs: {len(GRID)}",flush=True)
    PARTS=os.path.join(OUT,"amd_v2_parts"); os.makedirs(PARTS,exist_ok=True)
    for si in range(man["n_segments"]):
        pp=os.path.join(PARTS,f"p{si:03d}.pkl")
        if os.path.exists(pp): print(f"seg{si:03d} cached",flush=True); continue
        fp=os.path.join(FEAT,f"feat_{si:03d}.pkl")
        if not os.path.exists(fp): pickle.dump({},open(pp,"wb")); continue
        D=pickle.load(open(fp,"rb"))
        if D.get("empty"): pickle.dump({},open(pp,"wb")); continue
        bars=pickle.load(open(os.path.join(SEG,f"seg{si:03d}.pkl"),"rb"))
        ts=[b.ts_et for b in bars]
        seg={}
        for gi,cfg in enumerate(GRID):
            seg[gi]=amd_v2(D["feat"],ts,cfg["tf"],cfg["wid"],
                           TFP[cfg["tf"]][2],cfg["gate"],cfg["wait"])
        pickle.dump(seg,open(pp,"wb"))
        print(f"seg{si:03d} done",flush=True)
    store=defaultdict(dict)
    for si in range(man["n_segments"]):
        pp=os.path.join(PARTS,f"p{si:03d}.pkl")
        if not os.path.exists(pp): continue
        for gi,v in pickle.load(open(pp,"rb")).items(): store[gi][si]=v
    pickle.dump({"store":dict(store),"grid":GRID},open(os.path.join(OUT,"amd_v2.pkl"),"wb"))
    print("AMD V2 COMPLETE",flush=True)
    for gi,cfg in enumerate(GRID[:8]):
        print(f"  tf{cfg['tf']}m w{cfg['wid']} gate={cfg['gate']} wait{cfg['wait']}: "
              f"{sum(len(v) for v in store[gi].values()):,} instances",flush=True)
