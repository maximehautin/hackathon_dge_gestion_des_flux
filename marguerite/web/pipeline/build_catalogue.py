import requests, json, time, re, math, statistics as st, collections
import os
K=os.environ["APIDAE_API_KEY"]; P=9657
URL="https://api.apidae-tourisme.com/api/v002/recherche/list-objets-touristiques/"
F=["id","nom","type","localisation.adresse.commune","localisation.geolocalisation","presentation.descriptifCourt","ouverture.periodeEnClair","illustrations"]
def fetch(sel,fields=F):
    out=[];first=0
    while True:
        q={"projetId":P,"apiKey":K,"selectionIds":[sel],"count":200,"first":first,"locales":["fr"],"responseFields":fields}
        for a in range(3):
            try:
                d=requests.post(URL,data={"query":json.dumps(q)},timeout=120).json(); break
            except Exception as e: time.sleep(2)
        out+=d.get("objetsTouristiques",[]); first+=200
        if first>=d.get("numFound",0): break
    return out
AV=re.compile(r"parapente|via ferrata|escalade|canyon|ski nautique|wake|luge|accrobranche|chiens|spéléo|rafting|tyrolienne|grotte|kayak|paddle|plongée|montgolfi",re.I)
SP=re.compile(r"vtt|vélo|cycl|cheval|équ|randonn|sentier|circuit|boucle|trek|trail|marche|raquette|course|bivouac|sommet|golf|piscine|baignade|plage|parcours|tour du|tour de|pêche|orientation",re.I)
CU=re.compile(r"musée|visite|découverte|forge|patrimoine|histoire|château|atelier|abbaye|église|chapelle|village|mémoire|art",re.I)
NA=re.compile(r"lac\b|lacs\b|cascade|belvédère|forêt|marais|étang|gorges|réserve|espace naturel|tourbière|point de vue|panorama|col d|arboretum|jardin",re.I)
GAS=re.compile(r"ferme|fromag|chocolat|boulang|pâtiss|patiss|café|bar\b|salon de thé|miel|cave|producteur|brasserie|glac|fournil|tisan|confiserie|gourmand|cellier|douceur|boucherie|noix|liqueur|distiller",re.I)
NOGAS=re.compile(r"spar|casino|tabac|biocoop|vie claire|eau vive|intercaves|carrefour|intermarché|leclerc|presse|pharmacie",re.I)
FAM=re.compile(r"lac|cascade|bastille|téléphérique|gorges|dent de crolles|col du coq|croix|fort|abbaye|grotte|pont|cuves",re.I)
CLUB=re.compile(r"association|club|basket|foot|tennis|judo|yoga|gym|danse|pilates|multi ?activités|sorties? natures?|accompagn|encadr|stage|cours|initiation|séjour|bivouac|week-end|rando du|les rendez-vous|moniteur|guide|école|ecole|bureau des|avec ",re.I)
LIEU=re.compile(r"visite|ferme|âne|ânes|cheval|poney|équestre|vélo|vtt|kayak|paddle|bateau|pêche|baignade|plage|piscine|luge|parc|sentier|circuit|balade|découverte|rail|train|musée|lac |grotte|golf|mini-golf|labyrinthe",re.I)
DROP=re.compile(r"^(randonnée|marche|rando)( |$)|iaïdo|leçons|stage |cours |fermé|rando du mois|rendez-vous de l'office",re.I)
PREF="https://static.apidae-tourisme.com/filestore/objets-touristiques/images/"
def cat(o,grp):
    n=o.get("nom",{}).get("libelleFr","") ; t=o.get("type")
    if grp=="gas": return "gastronomie" if GAS.search(n) and not NOGAS.search(n) else None
    if t=="PATRIMOINE_NATUREL": return "nature"
    if t=="PATRIMOINE_CULTUREL": return "culture"
    if AV.search(n): return "aventure"
    if grp=="plein":
        if NA.search(n) and not SP.search(n): return "nature"
        if CU.search(n) and not SP.search(n): return "culture"
        return "sportif"
    if t=="EQUIPEMENT": return "culture"
    return "sportif" if SP.search(n) else "culture" if CU.search(n) else "sportif"
GROUPS={"site":[211891,211999,211884],"plein":[211911,211914,211888],"gas":[211908]}
pois=[];seen=set();stats=collections.Counter()
for grp,sels in GROUPS.items():
    for s in sels:
        obs=fetch(s); print(grp,s,len(obs),flush=True)
        for o in obs:
            g=(o.get("localisation",{}).get("geolocalisation") or {}); c=(g.get("geoJson") or {}).get("coordinates")
            com=(o.get("localisation",{}).get("adresse",{}).get("commune") or {})
            if not c or not str(com.get("code","")).startswith("38"): continue
            nom=o.get("nom",{}).get("libelleFr","").strip()
            if not nom or DROP.search(nom): continue
            ca=cat(o,grp)
            if not ca: continue
            # les fiches « activité » sont souvent géolocalisées au siège d'un club ou d'un prestataire :
            # on ne garde que celles qui désignent une pratique sur un lieu
            if o.get("type")=="ACTIVITE":
                if CLUB.search(nom): stats["club"]+=1; continue
                if not (AV.search(nom) or LIEU.search(nom)): stats["activite_floue"]+=1; continue
            key=(round(c[1],4),round(c[0],4),ca)
            if o["id"] in seen or key in seen: stats["doublon"]+=1; continue
            seen.add(o["id"]); seen.add(key)
            ill=[x for x in o.get("illustrations",[]) if x.get("type")=="IMAGE"]
            img=cr=""
            if ill:
                u=(ill[0].get("traductionFichiers") or [{}])[0].get("urlDiaporama") or ""
                if u.startswith(PREF) and u.endswith("-diaporama.jpg"): img=u[len(PREF):-len("-diaporama.jpg")]
                cr=(ill[0].get("copyright") or {}).get("libelleFr","") or ""
            t0=0.25+(0.35 if FAM.search(nom) else 0)+(0.15 if com.get("nom")=="Grenoble" else 0)
            if ca=="gastronomie": t0=0.15
            d=((o.get("presentation") or {}).get("descriptifCourt") or {}).get("libelleFr","") or ""
            ou=((o.get("ouverture") or {}).get("periodeEnClair") or {}).get("libelleFr","") or ""
            pois.append([o["id"],nom,ca,com.get("nom",""),round(c[1],5),round(c[0],5),g.get("altitude"),img,cr[:60],round(min(t0,0.85),2),
                         " ".join(d.split())[:170]," ".join(ou.split())[:90]])
            stats[grp+":"+ca]+=1
print(dict(stats)); print("POI:",len(pois),"avec photo:",sum(1 for p in pois if p[7]))
# hébergements agrégés par commune
H=fetch(211890,["id","type","localisation.adresse.commune","localisation.geolocalisation.geoJson","localisation.geolocalisation.altitude"])
G=collections.defaultdict(lambda:{"lat":[],"lon":[],"alt":[],"t":collections.Counter()})
for o in H:
    c=((o.get("localisation",{}).get("geolocalisation") or {}).get("geoJson") or {}).get("coordinates"); com=(o.get("localisation",{}).get("adresse",{}).get("commune") or {})
    if not c or not str(com.get("code","")).startswith("38"): continue
    g=G[com["nom"]]; g["lat"].append(c[1]); g["lon"].append(c[0]); g["t"][o.get("type")]+=1
    a=(o.get("localisation",{}).get("geolocalisation") or {}).get("altitude")
    if a is not None: g["alt"].append(a)
TY={"HEBERGEMENT_LOCATIF":0,"HEBERGEMENT_COLLECTIF":1,"HOTELLERIE":2,"HOTELLERIE_PLEIN_AIR":3}
bases=[]
for nom,g in G.items():
    n=len(g["lat"])
    if n<2: continue
    ty=[0,0,0,0]
    for k,v in g["t"].items():
        if k in TY: ty[TY[k]]=v
    bases.append([nom,round(st.median(g["lat"]),5),round(st.median(g["lon"]),5),n,ty,round(st.median(g["alt"])) if g["alt"] else None])
bases.sort()
print("hébergements:",len(H),"communes candidates:",len(bases))
CHEMIN=os.path.join(os.path.dirname(__file__),"..","src","catalogue.json")
cat=json.load(open(CHEMIN,encoding="utf-8")) if os.path.exists(CHEMIN) else {}   # conserve loueurs, hebVelo et hebAbri
cat.update({"pois":pois,"bases":bases})
json.dump(cat,open(CHEMIN,"w",encoding="utf-8"),ensure_ascii=False,separators=(",",":"))
print("Catalogue reconstruit :",len(pois),"activités,",len(bases),"communes")
