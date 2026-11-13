"""Loueurs et réparateurs de vélos en Isère, en activité.
Sources : DATAtourisme (commerces de location, label Accueil Vélo, périodes d'ouverture, tarifs)
et Apidae (types structurés des commerces et services du hackathon).
Ajoute la liste « loueurs » au catalogue de l'application (src/catalogue.json)."""
import requests, json, re, time, os, sys, collections, datetime as dt
K=os.environ["DATATOURISME_API_KEY"]; B="https://api.datatourisme.fr/v1"; Hd={"X-API-Key":K}
DEP="isLocatedAt.address.hasAddressCity.isPartOfDepartment.insee[eq]=38"
TODAY=dt.date.today(); DEBUT_ANNEE=dt.date(TODAY.year,1,1)
def pages(**p):
    out=[]; url=f"{B}/catalog"; params={"page_size":100,"lang":"fr","fields":"*",**p}
    while url:
        d=requests.get(url,params=params,headers=Hd,timeout=90).json()
        out+=d.get("objects",[]); url=(d.get("meta") or {}).get("next"); params=None
        if url: url=url.replace("http://","https://"); time.sleep(0.25)
    return out
fr=lambda x:(x.get("@fr") if isinstance(x,dict) else (x[0] if isinstance(x,list) and x else x)) or ""
VEL=r"(vélos?|vtt|vae|vttae|e-?bikes?|bikes?|cycles?|bicyclettes?|gravel|fatbike)"
LOC=re.compile(rf"(location|locations|loue|louer|loueur|rent|rental).{{0,60}}{VEL}|{VEL}.{{0,40}}(à louer|en location|à la location|location)",re.I)
REP=re.compile(rf"(réparation|réparer|entretien|atelier|dépannage).{{0,50}}{VEL}|{VEL}.{{0,30}}(réparation|entretien|atelier)|atelier du cycle",re.I)
VAE=re.compile(r"électrique|electrique|\bvae\b|vttae|e-?bike|assistance",re.I)
HORS=re.compile(r"borne de recharge|grange aux skis|accompagnateur|souvenirs|parcours d'apprentissage|pumptrack|consigne|boutique du pavillon",re.I)   # faux positifs repérés à la relecture
COMMERCE={"EquipmentRentalShop","EquipmentRental","Rental","Store","LocalBusiness","EquipmentRepairShop"}
EXCLU={"Accommodation","Restaurant","EntertainmentAndEvent","Tour","Camping","Hotel","CulturalSite","Museum","CyclingTour","LocalTouristOffice","TouristInformationCenter"}
REQ=[dict(filters=DEP+" AND type=Rental"),dict(filters=DEP+" AND type=EquipmentRepairShop"),
     dict(filters=DEP+" AND type=Store",search="vélo"),dict(filters=DEP+" AND type=Store",search="cycles"),dict(filters=DEP+" AND type=Store",search="VTT"),
     dict(filters=DEP,search="location vélo"),dict(filters=DEP,search="location VTT"),dict(filters=DEP,search="location vélo électrique"),dict(filters=DEP,search="loueur vélo"),
     dict(filters=DEP,search="e-bike"),dict(filters=DEP+" AND type=LocalBusiness",search="bike"),dict(filters=DEP+" AND type=LocalBusiness",search="VAE"),
     dict(filters=DEP+" AND hasReview.hasReviewValue.key[eq]=LabelRating_AccueilVelo")]
objs={}
for kw in REQ:
    for o in pages(**kw): objs[o["uuid"]]=o
L=[]; ecartes=collections.Counter()
for o in objs.values():
    ty=set(o.get("type") or []); nom=fr(o.get("label")).strip()
    d=" ".join(fr(x.get("shortDescription"))+" "+fr(x.get("description")) for x in (o.get("hasDescription") or []))
    court=" ".join(fr((o.get("hasDescription") or [{}])[0].get("shortDescription")).split())[:140]
    av=any(((r.get("hasReviewValue") or {}).get("key")=="LabelRating_AccueilVelo") for r in (o.get("hasReview") or []))
    loc=(o.get("isLocatedAt") or [{}])[0]; g=loc.get("geo") or {}; ad=(loc.get("address") or [{}])[0]
    if not g.get("latitude") or ty&EXCLU or not ty&COMMERCE or HORS.search(nom+" "+d): continue
    loue=bool(LOC.search(nom+" . "+d)) or bool(ty&{"EquipmentRentalShop","EquipmentRental"} and re.search(VEL,nom+" "+d,re.I)); repare=bool(REP.search(nom+" . "+d))
    if not loue and not (repare and av): continue          # un réparateur n'est retenu que s'il est labellisé Accueil Vélo
    # en activité : une période d'ouverture en cours ou à venir, ou une fiche mise à jour depuis le début de l'année
    fins=[]
    for l in (o.get("isLocatedAt") or []):
        for p in (l.get("openingHoursSpecification") or []):
            try: fins.append(dt.date.fromisoformat(p["validThrough"][:10]))
            except Exception: pass
    maj=dt.date.fromisoformat((o.get("lastUpdate") or "2000-01-01")[:10])
    # (une période close depuis moins d'un an compte aussi : beaucoup de loueurs sont saisonniers)
    if not ((fins and max(fins)>=TODAY-dt.timedelta(days=365)) or maj>=DEBUT_ANNEE): ecartes[nom]=max(fins).isoformat() if fins else maj.isoformat(); continue
    prix=[m for of in (o.get("offers") or []) for ps in (of.get("priceSpecification") or []) if re.search(r"jour|heure|demi|location|semaine",fr(ps.get("name")),re.I) for m in (ps.get("minPrice") or []) if isinstance(m,(int,float)) and m>0]   # tarifs de location uniquement
    c=(o.get("hasContact") or [{}])[0]
    L.append([nom,ad.get("addressLocality") or fr((ad.get("hasAddressCity") or {}).get("label")),round(g["latitude"],5),round(g["longitude"],5),
              (c.get("telephone") or [""])[0],(c.get("homepage") or [""])[0],1 if VAE.search(nom+" "+d) else 0,court,"DATAtourisme",1 if av else 0,min(prix) if prix else None,0 if loue else 1])
n_dt=len(L)
# complément Apidae : types et prestations structurés des commerces et services (sélections 211906 et 211908)
AK=os.environ["APIDAE_API_KEY"]; AU="https://api.apidae-tourisme.com/api/v002/recherche/list-objets-touristiques/"
AF=["id","nom","localisation.adresse.commune","localisation.geolocalisation.geoJson","informationsCommerceEtService","prestations","informations.moyensCommunication","presentation.descriptifCourt"]
TYPES_LOC=re.compile(r"loueur de vélos|location de vélos|location de vtt|bornes de location vélo",re.I)
for sel in (211906,211908):
    first=0
    while True:
        q={"projetId":9657,"apiKey":AK,"selectionIds":[sel],"count":200,"first":first,"locales":["fr"],"responseFields":AF}
        d=requests.post(AU,data={"query":json.dumps(q)},timeout=120).json()
        for o in d.get("objetsTouristiques",[]):
            ics=o.get("informationsCommerceEtService") or {}; pr=o.get("prestations") or {}
            lib=[t.get("libelleFr","") for t in (ics.get("typesDetailles") or [])]+[x.get("libelleFr","") for v in pr.values() if isinstance(v,list) for x in v if isinstance(x,dict)]
            nom=o["nom"]["libelleFr"].strip(); desc=((o.get("presentation") or {}).get("descriptifCourt") or {}).get("libelleFr","") or ""
            c=((o.get("localisation",{}).get("geolocalisation") or {}).get("geoJson") or {}).get("coordinates")
            struct=any(TYPES_LOC.search(t) for t in lib)
            if not c or not (struct or (LOC.search(nom+" . "+desc) and not HORS.search(nom+" "+desc))): continue
            mc=(o.get("informations") or {}).get("moyensCommunication") or []
            g=lambda lab:next((m.get("coordonnees",{}).get("fr","") for m in mc if (m.get("type") or {}).get("libelleFr")==lab),"")
            L.append([nom,o["localisation"]["adresse"]["commune"]["nom"],round(c[1],5),round(c[0],5),g("Téléphone"),g("Site web (URL)"),
                      1 if (VAE.search(nom+" "+desc) or any("assistance électrique" in t for t in lib)) else 0," ".join(desc.split())[:140],"Apidae",0,None,0])
        first+=200
        if first>=d.get("numFound",0): break
# doublons : même position ; on garde d'abord les loueurs, puis les labellisés
vus=set(); out=[]
for x in sorted(L,key=lambda x:(x[11],-x[9],x[8]!="DATAtourisme")):
    k=(round(x[2],3),round(x[3],3))
    if k in vus: continue
    vus.add(k); out.append(x)
cat_path=sys.argv[1] if len(sys.argv)>1 else os.path.join(os.path.dirname(__file__),"..","src","catalogue.json")
cat=json.load(open(cat_path,encoding="utf-8")); cat["loueurs"]=out
json.dump(cat,open(cat_path,"w",encoding="utf-8"),ensure_ascii=False,separators=(",",":"))
lo=[x for x in out if x[11]==0]; re_=[x for x in out if x[11]==1]
print(f"{len(objs)} fiches DATAtourisme examinées. {len(lo)} loueurs en activité ({sum(x[9] for x in lo)} labellisés Accueil Vélo, {sum(x[6] for x in lo)} avec vélos électriques, {sum(x[10] is not None for x in lo)} avec tarif) et {len(re_)} réparateurs labellisés.")
print("Écartés car sans signe d'activité récent :",dict(ecartes))
for x in out: print(f" {'loueur    ' if x[11]==0 else 'réparateur'} | {x[0][:42]:42s} | {x[1][:24]:24s} | {'AV ' if x[9] else '   '}{'VAE' if x[6] else '   '} | {('dès '+str(x[10])+' €') if x[10] else '':9s} | {x[8]}")
