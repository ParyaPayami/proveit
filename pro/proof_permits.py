"""Proof: score a simple permit forecast with Score My Layer, in two cities.

The forecast is persistence (last period's permits per area predict next
year's), the baseline any planning model should beat. Also runs two
known-answer checks of the tool itself: an oracle field (the true counts,
must score Spearman 1) and a random field (must score near 0).
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUTS, WORK, log, work_gdb, write_json  # noqa: E402
import score_layer  # noqa: E402

import arcpy  # noqa: E402

PROJECT_GDB = Path.home() / "Documents" / "ArcGIS" / "Projects" / "ProveIt" / "ProveIt.gdb"


def counts_from_pairs(name: str) -> dict[int, float]:
    import csv

    rows = csv.DictReader(open(OUTPUTS / "score" / name / "pairs.csv", encoding="utf-8"))
    return {int(r["id"]): float(r["outcome"]) for r in rows if r["outcome"]}


def set_field(fc: str, field: str, values: dict[int, float]) -> None:
    arcpy.management.AddField(fc, field, "DOUBLE")
    with arcpy.da.UpdateCursor(fc, ["OID@", field]) as cur:
        for row in cur:
            cur.updateRow([row[0], values.get(row[0], 0.0)])


def persistence(name: str, areas: str, source: str, where: str, past: tuple, future: tuple) -> dict:
    base = {"prediction": areas, "source": source, "where": where, "higher_means": "more"}
    score_layer.run(base | {"field": "OBJECTID", "start": past[0], "end": past[1], "name": f"{name}_past"})
    past_counts = counts_from_pairs(f"{name}_past")
    set_field(areas, "past_permits", past_counts)
    result = score_layer.run(base | {"field": "past_permits", "start": future[0], "end": future[1],
                                     "prediction_date": future[0], "name": name})
    # Known-answer checks of the tool: a perfect field and a random one.
    set_field(areas, "oracle", counts_from_pairs(name))
    rng = random.Random(7)
    set_field(areas, "random", {oid: rng.random() for oid in past_counts})
    oracle = score_layer.run(base | {"field": "oracle", "start": future[0], "end": future[1],
                                     "prediction_date": future[0], "name": f"{name}_oracle"})
    rand = score_layer.run(base | {"field": "random", "start": future[0], "end": future[1],
                                   "prediction_date": future[0], "name": f"{name}_random"})
    return {"forecast": result["scorecard"]["metrics"], "oracle": oracle["scorecard"]["metrics"],
            "random": rand["scorecard"]["metrics"], "headline": result["scorecard"]["headline"]}


def chicago_areas(gdb: str) -> str:
    from proveit.truth import _curl

    path = WORK / "chicago_community_areas.geojson"
    path.write_bytes(_curl("https://data.cityofchicago.org/api/geospatial/igwz-8jzy?method=export&format=GeoJSON"))
    raw = arcpy.conversion.JSONToFeatures(str(path), f"{gdb}\\chi_raw", "POLYGON")[0]
    return arcpy.management.Project(raw, f"{gdb}\\chicago_areas", arcpy.SpatialReference(26916))[0]


def main() -> None:
    arcpy.env.overwriteOutput = True
    gdb = work_gdb("proof_permits", fresh=True)
    results = {}

    nyc = arcpy.management.CopyFeatures(str(PROJECT_GDB / "fire_zip_results"), f"{gdb}\\nyc_zip_areas")[0]
    results["nyc_solar"] = persistence("nyc_solar_2025", nyc, "nyc_dob_now_permits", "work_type='Solar'",
                                       ("2023-01-01", "2024-12-31"), ("2025-01-01", "2025-12-31"))
    log(f"NYC solar: {results['nyc_solar']['headline']}")

    chi = chicago_areas(gdb)
    results["chicago_new_construction"] = persistence(
        "chicago_new_construction_2024_25", chi, "chicago_building_permits", "permit_type='PERMIT - NEW CONSTRUCTION'",
        ("2021-01-01", "2023-12-31"), ("2024-01-01", "2025-12-31"))
    log(f"Chicago new construction: {results['chicago_new_construction']['headline']}")
    write_json(OUTPUTS / "proof_permits.json", results)


if __name__ == "__main__":
    main()
