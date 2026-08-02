"""Does the reporting company's size predict how well the trade works?

No free source reaches historical stock prices (Stooq is behind a JS challenge, Alpha
Vantage's full daily series is paywalled), so market cap cannot be computed directly.

EDGAR reports `dei:EntityPublicFloat` -- the market value of shares held by non-affiliates,
stated as of a specific date in each annual filing. It is a genuine point-in-time size
measure, free, and immune to hindsight: for every earnings event we take the most recent
float value FILED BEFORE that event, never a later one.

Granularity is annual, so this tracks size tier rather than month-to-month cap.
"""
import json, time, urllib.request, os
import pandas as pd, numpy as np

UA = {"User-Agent": "discretion-study research contact dylankazakovas93@gmail.com"}
CIK = {"AAPL":320193,"MSFT":789019,"GOOGL":1652044,"AMZN":1018724,"NVDA":1045810,
       "META":1326801,"TSLA":1318605,"NFLX":1065280,"CSCO":858877,"INTC":50863,
       "QCOM":804328,"TXN":97476,"AVGO":1730168,"ADBE":796343,"MU":723125,"AMAT":6951,
       "PEP":77476,"COST":909832,"SBUX":829224,"GILD":882095,"AMGN":318154,
       "BKNG":1075531,"ISRG":1035267,"LRCX":707549,"MRVL":1835632,"KLAC":319201,
       "NXPI":1413447,"ADI":6281,"ON":1097864,"CDNS":813672,"SNPS":883241,
       "PANW":1327567,"CRWD":1535527,"INTU":896878,"SMCI":1375365}

def floats(sym, cik):
    u = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/dei/EntityPublicFloat.json"
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60))
    except Exception as ex:
        print(f"  {sym:6} no float data ({type(ex).__name__})"); return []
    out = []
    for unit in d.get("units", {}).values():
        for r in unit:
            if r.get("val") and r.get("filed"):
                out.append((pd.Timestamp(r["filed"]), pd.Timestamp(r["end"]), float(r["val"])))
    return sorted(set(out))

if not os.path.exists("data/macro/public_float.csv"):
    rows = []
    for sym, cik in CIK.items():
        for filed, end, val in floats(sym, cik):
            rows.append(dict(sym=sym, filed=filed, asof=end, float_usd=val))
        time.sleep(0.15)
    pd.DataFrame(rows).to_csv("data/macro/public_float.csv", index=False)
F = pd.read_csv("data/macro/public_float.csv", parse_dates=["filed","asof"])
print(f"float observations: {len(F)} across {F.sym.nunique()} symbols "
      f"({F.filed.min():%Y-%m} to {F.filed.max():%Y-%m})\n")

W = pd.read_csv("data/macro/weight.csv")          # per-event trade outcomes, confirm-0.2 entry
W["sess"] = pd.to_datetime(W.sess)

def float_asof(sym, when):
    k = F[(F.sym == sym) & (F.filed < when)]
    return k.sort_values("filed").float_usd.iloc[-1] if len(k) else np.nan

W["mcap"] = [float_asof(s, d) for s, d in zip(W.sym, W.sess)]
W = W.dropna(subset=["mcap"])
# rank within each session's own point in time, so 2020 and 2026 are comparable
W["yr"] = W.sess.dt.year
W["rank_pct"] = W.groupby("yr").mcap.rank(pct=True)
# one row per session: the largest reporter that evening
S = W.sort_values("mcap").groupby("sess").last().reset_index()
S.to_csv("data/macro/mcap_events.csv", index=False)

def stat(x):
    x = pd.Series(x).dropna()
    return (f"n={len(x):3} {x.mean():+.3f}% w{(x>0).mean():.0%} "
            f"t{x.mean()/(x.std()/np.sqrt(len(x))):+.1f}") if len(x) >= 8 else f"n={len(x)} too few"

print(f"sessions with size data: {len(S)}")
print(f"largest reporter's float: median ${S.mcap.median()/1e9:.0f}B  "
      f"p10 ${S.mcap.quantile(.1)/1e9:.0f}B  p90 ${S.mcap.quantile(.9)/1e9:.0f}B\n")
print("=== BY SIZE OF THE LARGEST REPORTER THAT EVENING (quartiles, ranked within year) ===")
q = pd.qcut(S.rank_pct, 4, labels=["Q1 smallest","Q2","Q3","Q4 largest"])
r = S.groupby(q, observed=True).agg(n=("plain","size"), med_cap=("mcap", lambda x: x.median()/1e9),
        no_stop=("plain","mean"), win=("plain", lambda x:(x>0).mean()), struct=("stop","mean"))
r["med_cap"] = r.med_cap.round(0)
print(r.round(3).to_string())
print("\n=== correlation of size with outcome ===")
print(f"  corr(log market cap, no-stop return)     = {np.log(S.mcap).corr(S.plain):+.3f}")
print(f"  corr(log market cap, struct-stop return)  = {np.log(S.mcap).corr(S.stop):+.3f}")
print(f"  corr(within-year size rank, no-stop ret)  = {S.rank_pct.corr(S.plain):+.3f}")
print("\n=== absolute size thresholds ===")
for thr in [100, 250, 500, 1000]:
    k = S[S.mcap >= thr*1e9]
    print(f"  largest reporter >= ${thr:>4}B : no stop {stat(k.plain):<28} struct {stat(k.stop)}")
