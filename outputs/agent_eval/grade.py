"""Record a grade: python3 grade.py T06 pass 58381 8 28 "note" [trap_caught]"""
import json, os, sys
g = json.load(open("grades.json")) if os.path.exists("grades.json") else {}
tid, grade, tok, tools, secs, note = sys.argv[1:7]
g[tid] = {"grade": grade, "tokens": int(tok), "tools": int(tools), "seconds": int(secs), "note": note}
if len(sys.argv) > 7:
    g[tid]["trap_caught_unprompted"] = sys.argv[7] == "yes"
json.dump(dict(sorted(g.items())), open("grades.json", "w"), indent=1)
