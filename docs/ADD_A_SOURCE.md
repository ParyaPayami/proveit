# Adding a truth source

A truth source is one JSON file in `catalog/`. Copy the closest existing entry and edit it.

| Key | What to write |
|---|---|
| `id`, `name`, `publisher`, `docs`, `license` | Who publishes it, and where it is documented |
| `topics` | Words people will search for (`permits`, `flood`, `energy`...) |
| `coverage` | `place`, `bbox` [west, south, east, north] in lon/lat, `start` date |
| `adapter` | How to read it (below) |
| `outcome` | `kind` plus `describes` (one line) and `unit` if it has values |
| `traps` | Every documented pitfall: `id`, `check` (plain words), `handled: true` if the adapter already deals with it |

**Outcome kinds:** `event` (something happened here: permits, complaints), `measure` (a value at a place: energy use, depth), `label` (yes/no per record, with `positive_values`, `negative_values`, `exclude_values`), `presence` (records only where it happened: flood marks), `areal_measure` (published as totals by area code).

**Adapters:**
- `socrata`: `domain`, `dataset`, `date_field` (+ `date_format` if dates are text), `lat`/`lon` (+ `coords_are_text`) or `point`, optional `value_field`, `value_factor`, `label_field`, `category_field`, `base_where`, `keep`.
- `socrata_join`: events plus a sites table joined on `join_key` (sensor networks).
- `socrata_aggregate`: totals by `key_field` computed on the portal (`count`, `median(value_field)`).
- `arcgis_layer`: an ArcGIS feature layer `url`; polygons are matched by an interior point.
- `csv_url`: a CSV file with `lat`/`lon` columns (`header_line` if it doesn't start on line 1).
- `manual`: not downloadable automatically; give `url` and `instructions`.

Test it: `python3 -m proveit.truth get <id> --start ... --end ...`, then check `records`, `dropped` and a few features. Run `.venv/bin/python -m pytest -q tests`.
