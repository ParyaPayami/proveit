# Agent evaluation: 32 tasks (October 23, 2026)

**Setup**
- One fresh Claude Code agent (Sonnet) per task, run once, working in ArcGIS Pro 3.7 through `bin/pro`.
- The agents got only the task text and the rules. They could not read the reference answers, run the case scripts, or write outside their own folder.
- Grading checked each answer against the pre-registered checks in `tasks/suite.json` and a snapshot of the reference results.
- The grader was the author's own assistant, not a blind reviewer. Details: `grades.json`, `summary.json`; every agent's scripts and `answer.json` are in `T01/` to `T32/`.

| Level | Tasks | Passed |
|---|---|---|
| 1. Known answers (counts, toy network, statistics by hand) | 8 | 8 |
| 3. Observed outcomes (fire, flood, wildfire, summary, Pro project) | 14 | 14 |
| 4. Traps (requests that lead to a misleading answer) | 10 | 10 |

- **Trap tasks:**
  - **Refused (3):** perimeter as a predictor, invented wind data, invented sewer data.
  - **Redirected to the correct comparison (5):** ZIP to ZCTA join, CSV header, feet vs meters, false alarms, response vs travel time.
  - **Did what was asked but warned and showed the distortion (2):** flagged FDNY records, uninspected structures counted as undamaged.
- **Unprompted:** in 29 of 32 tasks the agent named at least one documented trap without being told.
- **Reproduction:** agents independently matched the reference within rounding. Examples: fire bias +2.23 min and r = 0.48 over 167 areas; flood marks in low spots 51% vs 12% of controls; wildfire open-land AUC 0.379.
- **Effort:** median 89 s and 67k tokens per task (longest 10 min); 2.2M tokens in total.

## Flaws the agents found in the reference analysis (all fixed October 23, 2026)
1. **T16, T14:** the interior-mark keyword rule over-flags (31 hits, about 10 truly indoor). *Fixed:* a reviewed list of 10 in `cases/flood_ida.json`; the depth test now uses 142 street marks, Spearman 0.35 (was 0.33 on 121).
2. **T11, T09, T10, T12:** ZIP 11249 (94 fires) is dropped by the ZIP mapping. *Fixed:* the MODZCTA `label` is read too; unmatched incidents fell from 206 to 112.
3. **T09:** Score My Layer's area join can't combine postal ZIPs into multi-ZIP areas. *Fixed:* new `key_members` option with incident-weighted roll-up (tested).
4. **T09, T21:** "92% within 1 min after removing bias" is in-sample and partly reflects narrow spreads. *Fixed:* the scorer labels it in-sample and adds a leave-one-out version, which is also 92%.
5. **T12:** the proof-case toolbox tools have no study-area parameter. *Fixed:* Fire Coverage takes a ZIP-area prefix (e.g. 112 for Brooklyn); the network and firehouses stay citywide.
6. **T18, T19:** open-land distance partly encodes position inside the burned area, and models fitted on one fire don't transfer (AUC about 0.5). *Fixed:* both are now stated assumptions and checked traps in `cases/wildfire_la.json`.

## Limits
- Each task was run once. Repeated runs would measure variability.
- One model was tested.
- The grader was not blind.
- Several Level 3 tasks overlap in the data they use.
