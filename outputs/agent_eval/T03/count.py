import json
d=json.load(open('/Users/user/Desktop/Esri/proveit/data/raw/fire_ems/firehouses.json'))
def f(v):
    try: return float(v)
    except: return None
ok=[r for r in d if f(r.get('latitude')) is not None and f(r.get('longitude')) is not None]
nyc=[r for r in ok if 40.4<f(r['latitude'])<41.0 and -74.3<f(r['longitude'])<-73.6]
print(len(d),len(ok),len(nyc))
