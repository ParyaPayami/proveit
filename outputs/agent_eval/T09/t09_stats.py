import csv, json, sys, statistics
sys.path.insert(0, "/Users/user/Desktop/Esri/proveit")
from proveit import score
rows = list(csv.DictReader(open("/Users/user/Desktop/Esri/proveit/outputs/agent_eval/T09/results_by_zip.csv")))
print(len(rows), "areas")
def sel(f):
    return [r for r in rows if r["model_median_min"] != "" and r["obs_travel_min"] != "" and int(r["obs_incidents"]) >= 20 and f(r)]
res = {}
for nm, f in [("all", lambda r: True), ("single_zip", lambda r: r["postal_zips"] == "1")]:
    u = sel(f)
    m = [float(r["model_median_min"]) for r in u]; o = [float(r["obs_travel_min"]) for r in u]; rs = [float(r["obs_response_min"]) for r in u]
    res[nm] = {"travel": score.agreement(m, o, 1.0), "response": score.agreement(m, rs, 1.0),
               "model_median": round(statistics.median(m),2), "obs_median": round(statistics.median(o),2)}
    print(nm, json.dumps(res[nm]))
u = sel(lambda r: True)
print("excluded no model:", [r["modzcta"] for r in rows if r["model_median_min"]==""])
print("excluded no obs:", [r["modzcta"] for r in rows if r["obs_travel_min"]==""])
print("excluded <20:", [(r["modzcta"], r["obs_incidents"]) for r in rows if r["obs_travel_min"]!="" and int(r["obs_incidents"])<20])
print("unreached>0:", [(r["modzcta"], r["unreached_points"], r["street_points"]) for r in rows if int(r["unreached_points"])>0])
w = sorted(u, key=lambda r: -abs(float(r["obs_travel_min"])-float(r["model_median_min"])))[:8]
for r in w: print(r["modzcta"], r["model_median_min"], r["obs_travel_min"], r["obs_incidents"])
print("total unreached", sum(int(r["unreached_points"]) for r in rows), "of", sum(int(r["unreached_points"])+int(r["street_points"]) for r in rows))
print("obs incidents used", sum(int(r["obs_incidents"]) for r in u))
