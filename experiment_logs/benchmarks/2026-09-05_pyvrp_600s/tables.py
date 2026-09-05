import json, sys, statistics as st
sys.path.insert(0, "pyvrp_benchmarking/benchmark")
from pathlib import Path
from cvrplib import read_bks
D = Path("experiment_logs/benchmarks/2026-09-05_pyvrp_600s")
IDIR = Path("pyvrp_benchmarking/benchmark/instances/CVRP")

def load(p):
    g = {}
    for l in open(p):
        r = json.loads(l)
        g.setdefault(r["instance"], {}).setdefault(r["solver"], []).append(r["cost"])
    return g

print("== CVRP: mean over seeds, gap vs published best-known ==")
print(f"{'instance':<14}{'BKS':>9}{'PyVRP':>9}{'gap%':>8}{'SA':>9}{'gap%':>8}{'sd':>7}")
g = load(D/"results_cvrp.jsonl"); pg=[]; sg=[]
for name, d in g.items():
    bks = read_bks(IDIR/f"{name}.sol")
    sa = d.get("simann_sa", []); pv = d.get("pyvrp", [])
    if not sa or not pv: print(f"{name:<14}  incomplete: sa={len(sa)} pyvrp={len(pv)}"); continue
    m = st.mean(sa); sd = st.stdev(sa) if len(sa)>1 else 0.0
    sgap = 100*(m-bks)/bks; pgap = 100*(pv[0]-bks)/bks
    sg.append(sgap); pg.append(pgap)
    print(f"{name:<14}{bks:>9.0f}{pv[0]:>9.0f}{pgap:>8.2f}{m:>9.0f}{sgap:>8.2f}{sd:>7.0f}")
if sg: print(f"{'mean':<14}{'':>9}{'':>9}{st.mean(pg):>8.2f}{'':>9}{st.mean(sg):>8.2f}")

print("\n== MDVRP: mean over seeds, gap vs PyVRP (negative = SA cheaper) ==")
print(f"{'instance':<14}{'PyVRP':>10}{'SA':>10}{'gap%':>8}{'sd':>8}")
g = load(D/"results_mdvrp.jsonl"); gg=[]
for name, d in sorted(g.items()):
    sa = d["simann_sa"]; pv = d["pyvrp"][0]
    m = st.mean(sa); sd = st.stdev(sa) if len(sa)>1 else 0.0
    gap = 100*(m-pv)/pv; gg.append(gap)
    print(f"{name:<14}{pv:>10.0f}{m:>10.0f}{gap:>8.2f}{sd:>8.0f}")
print(f"{'mean':<14}{'':>10}{'':>10}{st.mean(gg):>8.2f}")
