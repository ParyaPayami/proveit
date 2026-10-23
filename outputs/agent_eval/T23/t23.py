import sys, csv, json, math, statistics
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, r"\\Mac\Home\Desktop\Esri\proveit\pro")
import fire_ems as fe          # imports functions only; main() is not run
from common import OUTPUTS, WORK, log, write_json, check_out
import arcpy

OUT = OUTPUTS / "agent_eval" / "T23"
SRC = r"C:\proveit_work\fire_ems.gdb"
check_out("Network")
arcpy.env.overwriteOutput = True
gdb = str(WORK / "T23_work.gdb")
if arcpy.Exists(gdb): arcpy.management.Delete(gdb)
arcpy.management.CreateFileGDB(str(WORK), "T23_work.gdb")
nd = SRC + r"\net\streets_nd"
print([f.name for f in arcpy.ListFields(SRC + r"\mids")])
print(arcpy.management.GetCount(SRC + r"\mids")[0], arcpy.management.GetCount(SRC + r"\firehouses")[0])
points = arcpy.management.CopyFeatures(SRC + r"\mids", gdb + r"\mids")[0]
fh_all = arcpy.management.CopyFeatures(SRC + r"\firehouses", gdb + r"\fh_all")[0]
fh_land = arcpy.management.MakeFeatureLayer(fh_all, "fh_land", "Name NOT LIKE 'Marine%'")[0]
fh_land = arcpy.management.CopyFeatures(fh_land, gdb + r"\fh_land")[0]
print("firehouses all/land", arcpy.management.GetCount(fh_all)[0], arcpy.management.GetCount(fh_land)[0])

zips, member = fe.load_zips(gdb)
observed, unmatched = fe.observed_by_area(member)

# raw obs for min_incidents (areas pooled across postal ZIPs)
def per_area(fh):
    minutes, loaded = fe.nearest_drive_minutes(nd, fh, points)
    d = defaultdict(list); unr = defaultdict(int)
    with arcpy.da.SearchCursor(points, ["OID@", "modzcta"]) as cur:
        for oid, m in cur:
            if oid in minutes: d[m].append(minutes[oid])
            else: unr[m] += 1
    return d, unr, loaded, len(minutes)
res = {}
for tag, fh in [("land", fh_land), ("all", fh_all)]:
    res[tag] = per_area(fh)
    log(f"{tag}: loaded {res[tag][2]} reached {res[tag][3]}")

MIN = fe.CASE["answer_key"]["min_incidents"]
rows = []
for m in sorted(set(res["land"][0]) | set(observed)):
    o = observed.get(m)
    r = {"modzcta": m, "obs_incidents": o["incidents"] if o else 0,
         "obs_travel_min": round(o["obs_travel_min"], 3) if o else "",
         "obs_response_min": round(o["obs_response_min"], 3) if o else ""}
    for tag in ("land", "all"):
        d, unr, _, _ = res[tag]
        v = d.get(m, [])
        r[f"model_median_min_{tag}"] = round(statistics.median(v), 3) if v else ""
        r[f"unreached_{tag}"] = unr.get(m, 0)
    r["street_points"] = len(res["land"][0].get(m, [])) + res["land"][1].get(m, 0)
    rows.append(r)
with open(OUT / "results_by_zip.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

def stats(tag, obskey):
    xs = [(float(r[f"model_median_min_{tag}"]), float(r[obskey]), r["modzcta"]) for r in rows
          if r["obs_incidents"] >= MIN and r[f"model_median_min_{tag}"] != "" and r[obskey] != ""]
    n = len(xs); err = [a - b for a, b, _ in xs]
    mx = sum(a for a, _, _ in xs) / n; my = sum(b for _, b, _ in xs) / n
    cov = sum((a - mx) * (b - my) for a, b, _ in xs)
    r = cov / math.sqrt(sum((a - mx) ** 2 for a, _, _ in xs) * sum((b - my) ** 2 for _, b, _ in xs))
    worst = sorted(xs, key=lambda t: -abs(t[0] - t[1]))[:8]
    return {"n_areas": n, "bias_min(model-obs)": round(sum(err) / n, 3), "mae_min": round(sum(abs(e) for e in err) / n, 3),
            "rmse_min": round(math.sqrt(sum(e * e for e in err) / n), 3), "pearson_r": round(r, 3),
            "within_1min": sum(abs(e) <= 1 for e in err), "median_model": round(statistics.median(a for a, _, _ in xs), 3),
            "median_obs": round(statistics.median(b for _, b, _ in xs), 3),
            "worst": [(z, round(a, 2), round(b, 2)) for a, b, z in worst]}
out = {"min_incidents": MIN,
       "areas_total_obs": len(observed), "areas_excluded_small": sorted(m for m, o in observed.items() if o["incidents"] < MIN),
       "areas_obs_without_model": sorted(m for m in observed if m not in res["land"][0]),
       "unmatched_zips": unmatched, "points": {t: {"loaded": res[t][2], "reached": res[t][3]} for t in res},
       "vs_travel_land": stats("land", "obs_travel_min"), "vs_travel_all": stats("all", "obs_travel_min"),
       "vs_response_land": stats("land", "obs_response_min")}
write_json(OUT / "stats.json", out)
print(json.dumps(out, indent=1, default=str))
