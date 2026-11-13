"""Hébergements Apidae qui prêtent ou louent des vélos, et ceux qui ont un abri à vélos.
Lit les prestations déclarées dans la sélection des hébergements du hackathon (211890)
et ajoute « hebVelo » et « hebAbri » au catalogue de l'application (src/catalogue.json).

Usage :
    export APIDAE_API_KEY=...
    python pipeline/build_hebergements_velo.py [src/catalogue.json]"""
import requests, json, time, os, sys, collections
K=os.environ["APIDAE_API_KEY"]; P=9657; URL="https://api.apidae-tourisme.com/api/v002/recherche/list-objets-touristiques/"
F=["id","nom","type","localisation.adresse.commune","localisation.geolocalisation.geoJson","prestations","informations.moyensCommunication"]
H=[]; first=0
while True:
    q={"projetId":P,"apiKey":K,"selectionIds":[211890],"count":200,"first":first,"locales":["fr"],"responseFields":F}
    for essai in range(3):
        try: d=requests.post(URL,data={"query":json.dumps(q)},timeout=120).json(); break
        except Exception: time.sleep(2)
    H+=d.get("objetsTouristiques",[]); first+=200
    if first>=d.get("numFound",0): break
TY={"HEBERGEMENT_LOCATIF":0,"HEBERGEMENT_COLLECTIF":1,"HOTELLERIE":2,"HOTELLERIE_PLEIN_AIR":3}
L=[]; abri=[]; st=collections.Counter()
for o in H:
    pr=o.get("prestations") or {}
    lib=set(x.get("libelleFr","") for v in pr.values() if isinstance(v,list) for x in v if isinstance(x,dict))
    pret="Prêt de vélos" in lib; loc=bool(lib&{"Location de vélos","Location de VTT"})
    vae=bool(lib&{"Location de vélos à assistance électrique","Location de VTT à assistance électrique"})
    c=((o.get("localisation",{}).get("geolocalisation") or {}).get("geoJson") or {}).get("coordinates"); com=(o.get("localisation",{}).get("adresse",{}).get("commune") or {})
    if not c or not str(com.get("code","")).startswith("38"): continue
    if "Abris pour vélo ou VTT" in lib: abri.append(o["id"])
    if not (pret or loc or vae): continue
    mc=(o.get("informations") or {}).get("moyensCommunication") or []
    g=lambda lab:next((m.get("coordonnees",{}).get("fr","") for m in mc if (m.get("type") or {}).get("libelleFr")==lab),"")
    # format : [id, nom, commune, lat, lon, type, offre (1 prêt + 2 location + 4 location électrique), téléphone, site]
    L.append([o["id"],o["nom"]["libelleFr"].strip(),com.get("nom",""),round(c[1],5),round(c[0],5),TY.get(o.get("type"),0),(1 if pret else 0)+(2 if loc else 0)+(4 if vae else 0),g("Téléphone"),g("Site web (URL)")])
    st["prêt"]+=pret; st["location"]+=loc; st["location électrique"]+=vae
cat_path=sys.argv[1] if len(sys.argv)>1 else os.path.join(os.path.dirname(__file__),"..","src","catalogue.json")
cat=json.load(open(cat_path,encoding="utf-8")); cat["hebVelo"]=L; cat["hebAbri"]=abri
json.dump(cat,open(cat_path,"w",encoding="utf-8"),ensure_ascii=False,separators=(",",":"))
print(f"{len(H)} hébergements lus : {len(L)} prêtent ou louent des vélos {dict(st)}, {len(abri)} ont un abri à vélos.")
