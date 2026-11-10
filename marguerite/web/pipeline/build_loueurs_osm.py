"""Complète la liste des loueurs et réparateurs de vélos avec un export OpenStreetMap.

Usage :
    python build_loueurs_osm.py export.geojson [src/catalogue.json]

L'export vient d'Overpass Turbo (https://overpass-turbo.eu), au format GeoJSON ou
« données brutes OSM » (JSON), avec la requête donnée dans le README.
Les objets déjà présents dans le catalogue (même lieu ou même nom à proximité) ne sont pas ajoutés."""
import json, sys, re, math, os
src=sys.argv[1]; cat_path=sys.argv[2] if len(sys.argv)>2 else os.path.join(os.path.dirname(__file__),"..","src","catalogue.json")
d=json.load(open(src,encoding="utf-8"))
def centre(geom):
    t=geom.get("type"); c=geom.get("coordinates")
    if t=="Point": return c[1],c[0]
    pts=[]
    def walk(x):
        if isinstance(x,list) and x and isinstance(x[0],(int,float)): pts.append(x)
        elif isinstance(x,list): [walk(y) for y in x]
    walk(c)
    return (sum(p[1] for p in pts)/len(pts), sum(p[0] for p in pts)/len(pts)) if pts else (None,None)
objs=[]
if d.get("type")=="FeatureCollection":                      # export GeoJSON d'Overpass Turbo
    for f in d["features"]:
        lat,lon=centre(f.get("geometry") or {}); tg={k:v for k,v in (f.get("properties") or {}).items() if isinstance(v,str)}
        if lat: objs.append((lat,lon,tg,f.get("id") or tg.get("@id","")))
else:                                                        # données brutes OSM (JSON)
    for e in d.get("elements",[]):
        lat=e.get("lat") or (e.get("center") or {}).get("lat"); lon=e.get("lon") or (e.get("center") or {}).get("lon")
        if lat: objs.append((lat,lon,e.get("tags") or {},f"{e.get('type')}/{e.get('id')}"))
def hav(a,b,c,e):
    R=6371000; p=math.pi/180; x=math.sin((c-a)*p/2)**2+math.cos(a*p)*math.cos(c*p)*math.sin((e-b)*p/2)**2; return 2*R*math.asin(math.sqrt(x))
norm=lambda s:re.sub(r"[^a-z0-9]","",s.lower())
cat=json.load(open(cat_path,encoding="utf-8")); L=cat.setdefault("loueurs",[])
stats={"loueur":0,"réparateur":0,"station en libre-service":0,"sans nom":0,"fermé ou désaffecté":0,"déjà présent":0,"ni location ni réparation":0}
for lat,lon,t,oid in objs:
    if any(k.startswith(("disused:","abandoned:","was:","demolished:")) for k in t) or t.get("opening_hours") in ("closed","off"): stats["fermé ou désaffecté"]+=1; continue
    station=t.get("amenity")=="bicycle_rental" and t.get("bicycle_rental") in ("docking_station","dropoff_point")
    if station: stats["station en libre-service"]+=1; continue      # libre-service : hors sujet pour une location à la semaine
    loue=t.get("amenity")=="bicycle_rental" or t.get("service:bicycle:rental")=="yes" or (t.get("shop")=="rental" and "bic" in t.get("rental",""))
    repare=t.get("service:bicycle:repair")=="yes" or t.get("shop")=="bicycle"
    if not loue and not repare: stats["ni location ni réparation"]+=1; continue
    nom=(t.get("name") or t.get("brand") or t.get("operator") or "").strip()
    if not nom: stats["sans nom"]+=1; continue
    if any(hav(lat,lon,x[2],x[3])<150 or (hav(lat,lon,x[2],x[3])<1500 and norm(nom)[:10]==norm(x[0])[:10]) for x in L): stats["déjà présent"]+=1; continue
    vae=1 if (re.search(r"électrique|electrique|e-?bike|vae",nom,re.I) or t.get("service:bicycle:electric")=="yes" or "ebike" in t.get("rental","")) else 0
    tel=t.get("phone") or t.get("contact:phone") or ""; web=t.get("website") or t.get("contact:website") or ""
    commune=t.get("addr:city") or t.get("contact:city") or ""
    desc=" ".join(x for x in [t.get("description",""),("Horaires : "+t["opening_hours"]) if t.get("opening_hours") else ""] if x)[:140]
    L.append([nom,commune,round(lat,5),round(lon,5),tel,web,vae,desc,"OpenStreetMap",0,None,0 if loue else 1])
    stats["loueur" if loue else "réparateur"]+=1
json.dump(cat,open(cat_path,"w",encoding="utf-8"),ensure_ascii=False,separators=(",",":"))
print(f"{len(objs)} objets OpenStreetMap lus :",", ".join(f"{v} {k}" for k,v in stats.items() if v))
print(f"Le catalogue contient maintenant {sum(1 for x in L if x[11]==0)} loueurs et {sum(1 for x in L if x[11]==1)} réparateurs.")
