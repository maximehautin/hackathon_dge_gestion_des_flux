/* =====================================================================
   Marguerite – version en direct (toute l'Isère)
   Appels navigateur : API Flux Isère, tuiles OpenStreetMap et Overpass.
   Les clés Apidae et GéoVélo restent côté serveur.
   ===================================================================== */
const CFG = {
  apidae: { projetId: 9657 },
  geovelo: {},
  flux: { url: "__FLUX_API_URL__" },
  sel: { poi: [211891, 211999, 211884], gas: [211908], heb: [211890] },
  radiusKm: 17
};
const CAT = __CATALOGUE__;   // catalogue Apidae de toute l'Isère, construit par pipeline/build_catalogue.py
const CATS = {nature:"Nature",culture:"Culture",gastronomie:"Gastronomie",aventure:"Aventure",sportif:"Sportif"};
const CATCOL = c => `var(--c-${c})`;
const S = {prof:"couple", velo:"classique", km:30, prefs:{nature:50,culture:50,gastronomie:50,aventure:50,sportif:50},
           fav:new Set(), liked:new Set(), plan:null, base:null, camps:null, sejour:null, reglage:false};
const POI = {};
const $ = id => document.getElementById(id);
const fmtDay = d => new Intl.DateTimeFormat("fr-FR",{weekday:"long",day:"numeric",month:"long"}).format(d);
const fmtShort = d => new Intl.DateTimeFormat("fr-FR",{day:"2-digit",month:"2-digit",year:"2-digit"}).format(d);
const wd = d => new Intl.DateTimeFormat("fr-FR",{weekday:"long"}).format(d);
const cap = s => s.charAt(0).toUpperCase()+s.slice(1);
const esc = s => String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const norm = s => s.normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().replace(/[’']/g,"'").replace(/[^a-z']/g,"");
const FLUX_CACHE=new Map();
async function flux(path,timeout=8000){
  const url=CFG.flux.url.replace(/\/$/,"")+path; if(FLUX_CACHE.has(url)) return FLUX_CACHE.get(url);
  const request=(async()=>{const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),timeout);
    try{const r=await fetch(url,{signal:controller.signal}); return r.ok?await r.json():null;}
    catch{return null}finally{clearTimeout(timer)}})();
  FLUX_CACHE.set(url,request); const result=await request;
  if(result===null) FLUX_CACHE.delete(url);
  return result;
}
function dateKey(d){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`}
function fluxT(row){
  const s=Number(row?.indice_saturation); let value;
  if(row?.indice_saturation!=null&&Number.isFinite(s)){
    value=s<=0.3?1.5*s:(s<=0.8?0.45+0.6*(s-0.3):Math.min(1,0.75+1.25*(s-0.8)));
  }else{
    const h=Number(row?.indice_habitude);
    if(row?.indice_habitude==null||!Number.isFinite(h)||h<=0) return null;
    value=0.6+0.15*Math.log(h)/Math.log(1.5);
  }
  return Math.max(0,Math.min(1,value));
}
async function fluxFrequentation(p,start,days=1){
  if(p.cat==="gastronomie") return null;
  const result=await flux(`/api/poi/apidae-${p.id}/frequentation?start=${dateKey(start)}&days=${days}`);
  if(!result?.jours) return null;
  p.freq=p.freq||{};
  result.jours.forEach(row=>{p.freq[row.date]={t:fluxT(row),niveau:row.niveau,calibrage:result.calibrage}});
  return result;
}

/* ---------- géométrie ---------- */
function hav(a,b){const R=6371,dl=(b.lat-a.lat)*Math.PI/180,dn=(b.lon-a.lon)*Math.PI/180;
  const x=Math.sin(dl/2)**2+Math.cos(a.lat*Math.PI/180)*Math.cos(b.lat*Math.PI/180)*Math.sin(dn/2)**2; return 2*R*Math.asin(Math.sqrt(x));}
function bearing(a,b){const y=Math.sin((b.lon-a.lon)*Math.PI/180)*Math.cos(b.lat*Math.PI/180);
  const x=Math.cos(a.lat*Math.PI/180)*Math.sin(b.lat*Math.PI/180)-Math.sin(a.lat*Math.PI/180)*Math.cos(b.lat*Math.PI/180)*Math.cos((b.lon-a.lon)*Math.PI/180);
  return (Math.atan2(y,x)*180/Math.PI+360)%360;}
function choisirDiversifie(feas,n,forcees){
  const caps=new Map(),cap=l=>{
    if(caps.has(l)) return caps.get(l);
    const all=l.stops.map(i=>POI[i]).filter(Boolean),visites=all.filter(p=>p.cat!=="gastronomie"),points=visites.length?visites:all;
    if(!points.length) return 0;
    let x=0,y=0;
    points.forEach(p=>{const d=hav(S.plan.origin,p),a=bearing(S.plan.origin,p)*Math.PI/180;
      x+=d*Math.cos(a);y+=d*Math.sin(a);});
    const value=Math.hypot(x,y)<1e-9?bearing(S.plan.origin,points[0]):(Math.atan2(y,x)*180/Math.PI+360)%360;
    caps.set(l,value); return value;
  };
  const chosen=[...new Set(forcees||[])].filter(l=>feas.includes(l)).sort((a,b)=>b.score-a.score).slice(0,n);
  if(!chosen.length&&feas.length) chosen.push([...feas].sort((a,b)=>b.score-a.score)[0]);
  while(chosen.length<n&&chosen.length<feas.length){
    let best=null,bestScore=-Infinity;
    feas.forEach(l=>{
      if(chosen.includes(l)) return;
      const a=cap(l)*Math.PI/180;
      const penalty=chosen.length?Math.max(...chosen.map(x=>Math.max(0,Math.cos(a-cap(x)*Math.PI/180)))):0;
      const score=l.score-0.8*penalty;
      if(score>bestScore){best=l;bestScore=score;}
    });
    if(!best) break;
    chosen.push(best);
  }
  return chosen;
}
function decodePolyline(s,p=6){let i=0,lat=0,lng=0;const out=[];const f=10**p;
  while(i<s.length){for(const k of [0,1]){let sh=0,r=0,b;do{b=s.charCodeAt(i++)-63;r|=(b&0x1f)<<sh;sh+=5}while(b>=0x20);
    const d=(r&1)?~(r>>1):(r>>1); if(k===0) lat+=d; else lng+=d;} out.push([lat/f,lng/f]);} return out;}

/* ---------- catalogue ---------- */
const IMG="https://static.apidae-tourisme.com/filestore/objets-touristiques/images/";
CAT.pois.forEach(a=>{POI[a[0]]={id:a[0],nom:a[1],cat:a[2],commune:a[3],lat:a[4],lon:a[5],alt:a[6],img:a[7]?IMG+a[7]+"-diaporama.jpg":null,credit:a[8]||null,t0:a[9],desc:a[10]||"",ouv:a[11]||""};});
const TOUS=Object.values(POI), LIEUX=TOUS.filter(p=>p.cat!=="gastronomie"), GOURMAND=TOUS.filter(p=>p.cat==="gastronomie");
const LOUEURS=(CAT.loueurs||[]).map(l=>({nom:l[0],commune:l[1],lat:l[2],lon:l[3],tel:l[4],web:l[5],vae:!!l[6],desc:l[7],src:l[8],av:!!l[9],prix:l[10],repare:l[11]===1}));
// hébergements Apidae qui prêtent ou louent des vélos (prestations déclarées), et ceux qui ont un abri à vélos
const HEBVELO=(CAT.hebVelo||[]).map(h=>({id:h[0],nom:h[1],commune:h[2],lat:h[3],lon:h[4],type:h[5],pret:!!(h[6]&1),loc:!!(h[6]&2),vae:!!(h[6]&4),tel:h[7],web:h[8]}));
const HEBVELO_ID=new Map(HEBVELO.map(h=>[h.id,h])), ABRI=new Set(CAT.hebAbri||[]);
const atoutVelo=id=>{const h=HEBVELO_ID.get(id); return h?(h.pret?"prête des vélos":h.vae&&!h.loc?"loue des vélos électriques":"loue des vélos"):ABRI.has(id)?"abri vélo":"";};
const BASES=CAT.bases.map(b=>({nom:b[0],lat:b[1],lon:b[2],n:b[3],ty:b[4],alt:b[5]}));
/* ---------- saison : une activité n'est proposée que si elle se pratique aux dates du séjour ---------- */
const HIVER=/raquette|\bski|skiable|nordique|traîneau|traineau|chiens? de tra|patinoire|igloo|biathlon|snow|motoneige|cascade de glace|sur neige|hivernal/i;
const ETE=/baignade|plage|canyon|rafting|kayak|paddle|aviron|voile|wake|ski nautique|pédalo|piscine d'été|bivouac/i;
const jourAn=(m,j)=>m*31+j;
function deSaison(p,d){ if(!d) return true; const m=d.getMonth()+1, neige=(m>=12||m<=3), beau=(m>=5&&m<=9);
  if(!neige&&HIVER.test(p.nom)&&!/ski nautique|ski[- ]roues?|marche nordique|été|estival|vtt|vélo/i.test(p.nom)) return false;   // pas de raquettes ni de ski hors saison de neige
  if(!beau&&ETE.test(p.nom)) return false;
  // périodes d'ouverture Apidae du type « Du 15/12 au 31/03 » : le séjour doit tomber dans l'une d'elles
  const per=[...(p.ouv||"").matchAll(/(\d{1,2})\/(\d{1,2})(?:\/\d{2,4})?\s+au\s+(\d{1,2})\/(\d{1,2})/g)];
  if(per.length){const x=jourAn(m,d.getDate()); return per.some(r=>{const a=jourAn(+r[2],+r[1]), b=jourAn(+r[4],+r[3]); return a<=b?(x>=a&&x<=b):(x>=a||x<=b);});}
  return true;}
let ACTIFS=LIEUX, GOURMETS=GOURMAND, ENSAISON=TOUS;
function appliquerSaison(d){ACTIFS=LIEUX.filter(p=>deSaison(p,d)); GOURMETS=GOURMAND.filter(p=>deSaison(p,d)); ENSAISON=[...ACTIFS,...GOURMETS];}
const zone=B=>({nom:B.nom,center:{lat:B.lat,lon:B.lon},pois:ACTIFS.filter(p=>hav(B,p)<=CFG.radiusKm),gas:GOURMETS.filter(p=>hav(B,p)<=CFG.radiusKm)});

/* ---------- API Apidae ---------- */
async function apidae(selectionIds, center, radiusKm, count=200, first=0){
  const url=CFG.flux.url.replace(/\/$/,"")+"/api/marguerite/apidae";
  const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({selectionIds,lat:center.lat,lon:center.lon,radiusKm,count,first})});
  if(!r.ok) throw new Error(`Apidae a répondu ${r.status}`);
  const d=await r.json(); return {total:d.numFound||0, objets:d.objetsTouristiques||[]};
}
/* ---------- navigation ---------- */
function go(id){
  if((id==="programme"||id==="pros") && (!S.plan||S.plan.loading)) id=S.plan?"programme":"profil";
  if((id==="camp"||id==="resultat") && !SW.fini) id="profil";
  document.querySelectorAll("#splash,.screen").forEach(s=>s.classList.remove("on"));
  $(id).classList.add("on"); closeMenu(); window.scrollTo(0,0);
  if(id==="territoire") renderTerritory();
  if(id==="swipe") startSwipe();
  if(id==="camp" && !S.camps) suggererCamps();
  if(id==="pros") renderLoueurs();
}
document.addEventListener("click",e=>{const g=e.target.closest("[data-go]"); if(g) go(g.dataset.go);});
const menu=$("menu");
function closeMenu(){menu.classList.remove("on");$("menuBtn").setAttribute("aria-expanded","false")}
$("menuBtn").onclick=()=>{const on=!menu.classList.contains("on");menu.classList.toggle("on",on);$("menuBtn").setAttribute("aria-expanded",on)};
$("profileBtn").onclick=()=>go("profil");

/* ---------- profil : nom, profil, dates ---------- */
function chipGroup(id,key){ $(id).addEventListener("click",e=>{const b=e.target.closest(".chip"); if(!b) return;
  $(id).querySelectorAll(".chip").forEach(c=>c.setAttribute("aria-pressed",c===b)); S[key]=b.dataset.v; if(key!=="prof"){S.camps=null; kmHint();} });}
chipGroup("chipsProf","prof"); chipGroup("chipsVelo","velo");
const sl=$("sliders");
Object.entries(CATS).forEach(([k,l])=>{const r=document.createElement("div");r.className="slider";
  r.innerHTML=`<span><span class="dot" style="background:${CATCOL(k)}"></span>${l}</span><input type="range" min="0" max="100" value="${S.prefs[k]}" aria-label="Intérêt ${l}" id="r_${k}"><output id="o_${k}">${S.prefs[k]}</output>`;
  sl.appendChild(r); r.querySelector("input").oninput=e=>{S.prefs[k]=+e.target.value;$("o_"+k).textContent=e.target.value; S.camps=null;};});
// budget d'effort : la distance est choisie par le visiteur, le dénivelé admis en découle (plus large en vélo électrique)
function budget(){const d=Math.max(250,Math.round(S.km*12)); return {km:S.km,d:S.velo==="vae"?Math.round(d*2.2):d};}
// activités possibles : à portée de vélo d'au moins une commune où l'on peut loger
function possibles(b){const portee=Math.min(CFG.radiusKm,b.km/2.5), ok=new Set();
  for(const B of BASES) for(const p of ENSAISON){ if(ok.has(p.id)) continue; if(Math.abs(p.lat-B.lat)>0.17||Math.abs(p.lon-B.lon)>0.24) continue;
    if(B.alt!=null&&p.alt!=null&&Math.abs(p.alt-B.alt)>b.d*0.6) continue; if(hav(B,p)<=portee) ok.add(p.id); }
  return ok;}
let kmTimer=null;
function kmHint(){const b=budget(); $("kmVal").textContent=`${S.km} km`; clearTimeout(kmTimer);
  kmTimer=setTimeout(()=>{S.possibles=possibles(b); const n=[...S.possibles].filter(i=>POI[i].cat!=="gastronomie").length;
    $("kmHint").textContent=`Jusqu’à ${b.d} m de dénivelé par jour. ${n.toLocaleString("fr-FR")} activités de saison sont accessibles avec cette distance.`;},120);}
function majSaison(){const d=new Date($("fStart").value+"T12:00"); appliquerSaison(isNaN(d)?null:d); S.camps=null; kmHint();}
$("fStart").addEventListener("change",majSaison); majSaison();
$("fKm").oninput=e=>{S.km=+e.target.value; S.camps=null; kmHint();};
const PERS={solo:1,couple:2,famille:4,amis:4};
function lireDates(){const err=$("errDates"); err.textContent="";
  const start=new Date($("fStart").value+"T12:00"), end=new Date($("fEnd").value+"T12:00");
  if(isNaN(start)||isNaN(end)){err.textContent="Indiquez vos dates d’arrivée et de départ.";return null}
  const n=Math.round((end-start)/864e5)+1;
  if(n<1){err.textContent="La date de départ doit suivre la date d’arrivée.";return null}
  if(n>7){err.textContent="Marguerite compose des séjours de 7 jours maximum. Raccourcissez la période.";return null}
  return {start,end,n,days:[...Array(n)].map((_,i)=>new Date(start.getTime()+i*864e5))};}
$("okProfil").onclick=()=>{const s=lireDates(); if(!s){$("fStart").focus();return}
  S.sejour=s; S.nom=$("fName").value.trim(); clearTimeout(kmTimer); appliquerSaison(s.start); S.possibles=possibles(budget());
  S.camps=null; SW.fini=false; go("swipe");};

/* ---------- swipe adaptatif sur toute l'Isère ---------- */
const SW={pool:[],shown:[],ab:{},max:15,min:10,cur:null,lastCat:null,fini:false};
const betaVar=([a,b])=>a*b/((a+b)**2*(a+b+1));
function startSwipe(){
  SW.pool=ENSAISON.filter(p=>p.img&&(!S.possibles||S.possibles.has(p.id))&&(p.cat!=="gastronomie"||/ferme|fromag|chocolat|miel|cave |cellier|producteur|brasserie|distiller|tisan|noix|liqueur|glac/i.test(p.nom))&&!/inter ?caves|bowling/i.test(p.nom)); SW.shown=[]; SW.lastCat=null; SW.fini=false; Object.keys(CATS).forEach(k=>SW.ab[k]=[1,1]); S.liked.clear(); S.camps=null;
  nextCard();}
function pickNext(){
  const vus=new Set(SW.shown.map(x=>x.p.id)), communes=new Set(SW.shown.map(x=>x.p.commune));
  // carte la plus informative : catégorie la plus incertaine ; on varie aussi les communes pour couvrir le département
  const aimes=SW.shown.filter(x=>x.yes).map(x=>x.p);
  // dès qu'une idée plaît, les suivantes se rapprochent de ce secteur : les coups de cœur dessinent une destination
  const pres=p=>!aimes.length?1:aimes.some(a=>hav(a,p)<=18)?1.6:0.8;
  const score=p=>betaVar(SW.ab[p.cat])*(p.cat===SW.lastCat?0.6:1)*(communes.has(p.commune)?0.7:1)*pres(p)+0.03*p.t0+Math.random()*0.02;
  let best=null,bs=-1; for(const p of SW.pool){ if(vus.has(p.id)) continue; const s=score(p); if(s>bs){bs=s;best=p} } return best;}
function done(){const n=SW.shown.length; if(n>=SW.max) return true; if(n<SW.min) return false;
  return Object.values(SW.ab).every(ab=>betaVar(ab)<0.039);}
function nextCard(){
  const st=$("stack"); st.innerHTML="";
  $("swProg").innerHTML=Array.from({length:SW.max},(_,k)=>`<i class="${k<SW.shown.length?"on":""}"></i>`).join("");
  if(done()) return showResult();
  const p=pickNext(); if(!p) return showResult(); SW.cur=p;
  const el=document.createElement("div"); el.className="card"; el.setAttribute("aria-label",`Idée ${SW.shown.length+1} : ${p.nom}`);
  el.innerHTML=`<div class="ph" style="background:${CATCOL(p.cat)}"><img src="${esc(p.img)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">${p.credit?`<span class="credit">© ${esc(p.credit)}</span>`:""}<span class="stamp yes">OUI</span><span class="stamp no">NON</span></div>
    <div class="cap"><h2>${esc(p.nom)}</h2><div class="cat">${CATS[p.cat]}, ${esc(p.commune)}</div>${p.desc?`<p class="kv" style="margin:6px 0 0">${esc(p.desc.length>120?p.desc.slice(0,118)+"…":p.desc)}</p>`:""}</div>`;
  st.appendChild(el); drag(el);}
const reduce=matchMedia("(prefers-reduced-motion: reduce)").matches;
function decide(yes){const el=$("stack").querySelector(".card"); if(!el||!SW.cur) return; const p=SW.cur; SW.cur=null;
  SW.shown.push({p,yes}); SW.ab[p.cat][yes?0:1]+=1; SW.lastCat=p.cat; if(yes) S.liked.add(p.id);
  el.style.transition="transform .3s ease, opacity .3s"; el.style.transform=`translateX(${yes?520:-520}px) rotate(${yes?18:-18}deg)`; el.style.opacity="0";
  setTimeout(nextCard,reduce?0:260);}
function drag(el){let x0=null,dx=0;
  el.addEventListener("pointerdown",e=>{x0=e.clientX;dx=0;el.setPointerCapture(e.pointerId);el.classList.add("drag");el.style.transition="none"});
  el.addEventListener("pointermove",e=>{if(x0===null) return; dx=e.clientX-x0; el.style.transform=`translateX(${dx}px) rotate(${dx/18}deg)`;
    el.querySelector(".stamp.yes").style.opacity=Math.max(0,Math.min(1,dx/90)); el.querySelector(".stamp.no").style.opacity=Math.max(0,Math.min(1,-dx/90));});
  const end=()=>{if(x0===null) return; x0=null; el.classList.remove("drag");
    if(Math.abs(dx)>90) decide(dx>0); else {el.style.transition="transform .2s";el.style.transform="";el.querySelectorAll(".stamp").forEach(s=>s.style.opacity=0)}};
  el.addEventListener("pointerup",end); el.addEventListener("pointercancel",end);}
$("swYes").onclick=()=>decide(true); $("swNo").onclick=()=>decide(false);
document.addEventListener("keydown",e=>{if(!$("swipe").classList.contains("on")) return; if(e.key==="ArrowRight") decide(true); if(e.key==="ArrowLeft") decide(false);});
const NOMS={nature:"contemplatif",culture:"curieux",gastronomie:"gourmand",aventure:"aventurier",sportif:"sportif"};
function showResult(){
  Object.entries(SW.ab).forEach(([k,[a,b]])=>{const v=Math.round(10+85*(a/(a+b))); S.prefs[k]=v; $("r_"+k).value=v; $("o_"+k).textContent=v;});
  const top=Object.entries(S.prefs).sort((a,b)=>b[1]-a[1]); const n=SW.shown.length, nl=S.liked.size;
  $("rTitle").textContent=nl===0?"Profil à préciser":`${S.nom?S.nom.split(" ")[0]+", vous":"Vous"} êtes plutôt ${NOMS[top[0][0]]}${top[1][1]>=55?` et ${NOMS[top[1][0]]}`:""}`;
  $("rSub").textContent=`Profil déduit de vos ${n} choix. ${nl?"Il guide le choix du camp de base et la composition du séjour.":"Aucune idée ne vous a tenté : ajustez vos envies ci-dessous ou recommencez."}`;
  SW.fini=true; go("resultat");}
$("resOk").onclick=()=>{S.camps=null; go("camp");};

/* ---------- affluence Flux Isère, modèle de démonstration en repli ---------- */
function dayFactor(d){const w=d.getDay(), m=d.getMonth();
  const dw=(w===0||w===6)?1.5:(w===5?1.15:1); const mf=(m===6||m===7)?1.3:((m===5||m===8)?1.1:0.8); return dw*mf;}
const tension=(p,d)=>p.cat==="gastronomie"?0.15:(Number.isFinite(p.freq?.[dateKey(d)]?.t)?p.freq[dateKey(d)].t:Math.min(1,p.t0*dayFactor(d)*0.95));
const level=t=>t<0.45?"calm":(t<0.75?"mid":"high");
const LVL={calm:"Affluence calme",mid:"Affluence modérée",high:"Affluence forte"};
const LVLC={calm:"var(--calm)",mid:"var(--mid)",high:"var(--high)"};
const loopT=(l,d)=>Math.max(...l.stops.map(i=>tension(POI[i],d)));

/* ---------- GéoVélo ---------- */
async function route(origin, stops, boucle=true){
  const url=CFG.flux.url.replace(/\/$/,"")+"/api/marguerite/geovelo";
  const points=(boucle?[origin,...stops,origin]:[origin,...stops]).map(p=>({lat:p.lat,lon:p.lon}));
  const body={points,velo:S.velo,profil:"RIDE",instructions:true};
  // profil RIDE : itinéraire touristique GéoVélo, qui privilégie voies vertes et aménagements cyclables
  const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  if(!r.ok) throw new Error(`GéoVélo a répondu ${r.status}`);
  const it=(await r.json())[0]; const s=it.sections[0], d=s.details, dist=d.distances||{};
  const voies=voirie(dist), ins=d.instructions||[], h=ins[0]||[];
  const iF=h.indexOf("facility"), iC=h.indexOf("cyclability"), iG=h.indexOf("geometryIndex");
  const segs=(iF<0||iG<0)?[]:ins.slice(1).map(x=>({g:x[iG],c:catTroncon(x[iF],iC<0?null:x[iC])}));
  return {km:Math.round(dist.total/100)/10, dplus:d.verticalGain||0, dmoins:d.verticalLoss||0, green:voies.dedie, voies, segs, type:it.title||"RIDE", geom:decodePolyline(s.geometry)};
}
/* ---------- profil de voirie d'un itinéraire ---------- */
const VOIES=[
  {k:"verte",  l:"Voie verte",                 c:"#2E8B57"},
  {k:"piste",  l:"Piste cyclable",             c:"#1F78B4"},
  {k:"bande",  l:"Bande ou voie partagée",     c:"#6BAED6"},
  {k:"apaisee",l:"Rue apaisée",                c:"#B59B2B"},
  {k:"route",  l:"Route ordinaire",            c:"#8D938E"},
  {k:"deconseillee",l:"Route déconseillée à vélo",c:"#C2412D"},
  {k:"pied",   l:"Passage à pied",             c:"#8E6BBF"}];
function voirie(x){const T=Math.max(1,x.total||0), g=k=>x[k]||0;
  const v={verte:g("greenway"), piste:g("cycleway"), bande:g("lane")+g("sharebusway")+g("opposite"),
           apaisee:g("zone30")+g("livingstreet")+g("residential"), deconseillee:g("discouragedRoads"), pied:g("footway")+g("pedestrian")+g("steps")};
  // les catégories de GéoVélo se recoupent en partie : on borne puis on complète par les routes ordinaires
  let reste=T-(v.verte+v.piste+v.bande+v.pied+v.deconseillee); if(reste<0) reste=0;
  v.apaisee=Math.min(v.apaisee,reste); v.route=Math.max(0,reste-v.apaisee);
  const s=Object.values(v).reduce((a,b)=>a+b,0)||1; const p={}; Object.keys(v).forEach(k=>p[k]=v[k]/s);
  p.dedie=p.verte+p.piste+p.bande; return p;}
function catTroncon(f,c){
  if(f==="GREENWAY") return "verte"; if(f==="CYCLEWAY") return "piste";
  if(f==="LANE"||f==="SHAREBUSWAY"||f==="OPPOSITE") return "bande";
  if(f==="FOOTWAY"||f==="PEDESTRIAN"||f==="STEPS") return "pied";
  if(c!=null&&c<=1) return "deconseillee";
  if(f==="RESIDENTIAL"||f==="LIVINGSTREET"||f==="ZONE30") return "apaisee";
  return "route";}
const pct=x=>x>0&&x<0.005?"moins de 1 %":Math.round(x*100)+" %";
function profilHTML(l){const v=l.voies; if(!v) return "";
  const parts=VOIES.filter(o=>v[o.k]>0.004);
  return `<div class="voirie"><h3>Profil de l’itinéraire</h3>
    <p class="kv">Itinéraire touristique GéoVélo, qui privilégie les aménagements cyclables. <b>${pct(v.dedie)}</b> du parcours sur voies dédiées au vélo (voies vertes, pistes et bandes cyclables).</p>
    <div class="vbar" role="img" aria-label="Répartition du parcours par type de voie">${parts.map(o=>`<i style="width:${(v[o.k]*100).toFixed(1)}%;background:${o.c}"></i>`).join("")}</div>
    <ul class="vleg">${parts.map(o=>`<li><span class="dot" style="background:${o.c}"></span>${o.l}<b>${pct(v[o.k])}</b><span class="cat">${(v[o.k]*l.km).toFixed(1)} km</span></li>`).join("")}</ul></div>`;}
async function pool(items,n,fn){const out=[];let i=0;await Promise.all(Array.from({length:n},async()=>{while(i<items.length){const k=i++;try{out[k]=await fn(items[k],k)}catch(e){out[k]=null}}}));return out;}

/* ---------- accès cyclable d'un lieu ---------- */
// Note entre -1 et 1 : les voies dédiées comptent pleinement, les routes déconseillées pénalisent.
const noteAcces=v=>v.verte+v.piste+0.7*v.bande+0.6*v.apaisee+0.3*v.pied+0.2*v.route-1.0*v.deconseillee;
function libelleAcces(a){const s=a.note; return s>=0.6?"Accès vélo très bien aménagé":s>=0.4?"Accès vélo bien aménagé":s>=0.2?"Accès vélo partiellement aménagé":"Accès vélo peu aménagé";}
const niveauAcces=a=>a.note>=0.4?"calm":a.note>=0.2?"mid":"high";
const seuilDeconseille=()=>S.prof==="famille"?0.15:0.35;
function rayon(b){return Math.min(CFG.radiusKm,b.km/3.2);}
function preselection(area,origin,b){
  const rmax=rayon(b), oa=originAlt(area,origin);
  const tropHaut=p=>oa!=null&&p.alt!=null&&(p.alt-oa)>b.d*0.85;
  const A=area.pois.map(p=>({p,d:hav(origin,p),b:bearing(origin,p)})).filter(x=>x.d>0.4&&x.d<=rmax&&!tropHaut(x.p));
  const sc=x=>S.prefs[x.p.cat]/100+(S.liked.has(x.p.id)?2:0)+(x.p.img?0.05:0)-x.d/60;
  A.sort((a,c)=>sc(c)-sc(a));
  const par={}, out=[];
  for(const x of A){const k=Math.floor(x.b/45); par[k]=par[k]||0; if(par[k]>=5&&!S.liked.has(x.p.id)) continue; par[k]++; out.push(x.p); if(out.length>=30) break;}
  return out;}

/* ---------- camp de base : où loger pour profiter de ses envies ? ---------- */
const TYNOM=[["location","locations"],["hébergement collectif","hébergements collectifs"],["hôtel","hôtels"],["camping","campings"]];
const offreTxt=B=>B.ty.map((n,i)=>({n,i})).filter(x=>x.n).sort((a,b)=>b.n-a.n).slice(0,3).map(x=>`${x.n} ${TYNOM[x.i][x.n>1?1:0]}`).join(", ");
let MAPC=null, LAYERC=null;
async function suggererCamps(){
  const b=budget(), portee=Math.min(CFG.radiusKm,b.km/2.5), ld=$("campLoad"), list=$("campList"), nl=S.liked.size;
  list.innerHTML=""; $("campMapBox").hidden=true; ld.hidden=false; ld.textContent="Comparaison des communes d’Isère…";
  $("cSub").textContent=`Les communes d’Isère où loger pour rejoindre à vélo le plus d’activités à votre goût, dans la limite de ${b.km} km par jour.`;
  await new Promise(r=>setTimeout(r,30));
  // 1. tri géométrique sur tout le département : coups de cœur et activités au goût du visiteur, à portée de vélo
  BASES.forEach(B=>{B.near=[]; B.wl=0; B.rich=0; B.nb=0;
    for(const p of ACTIFS){ const d=hav(B,p); if(d>portee) continue; const coeur=S.liked.has(p.id);
      // l'aller-retour remonte ce qu'il descend : on borne l'écart d'altitude dans les deux sens
      if(B.alt!=null&&p.alt!=null&&Math.abs(p.alt-B.alt)>b.d*0.6) continue;
      if(!coeur&&d<1.8) continue;                       // trop proche pour une sortie à vélo : cela se fait à pied
      const w=S.prefs[p.cat]/100; if(coeur){B.wl++; B.near.push({p,d,w:3});} else if(w>=0.5){B.rich+=w; B.nb++; B.near.push({p,d,w});} }
    // variété : des activités dans plusieurs directions permettent plusieurs boucles
    B.secteurs=new Set(B.near.map(x=>Math.floor(bearing(B,x.p)/60))).size; });
  const maxRich=Math.max(...BASES.map(B=>B.rich),1);
  BASES.forEach(B=>{B.geo=((nl?0.7*B.wl/nl:0)+(nl?0.3:1)*B.rich/maxRich)*(0.5+B.secteurs/12);});
  const espaces=(L,dmin,k)=>{const out=[]; for(const B of L){ if(out.every(o=>hav(o,B)>=dmin)) out.push(B); if(out.length>=k) break;} return out;};
  let bases=espaces(BASES.filter(B=>B.near.length>=5&&B.secteurs>=3).sort((x,y)=>y.geo-x.geo),6,7);
  if(!bases.length){ld.textContent="Aucune commune ne donne accès à vélo à des activités à votre goût. Augmentez votre distance quotidienne ou passez au vélo électrique.";return}
  // 2. itinéraires touristiques GéoVélo : commune -> lieux les plus prometteurs
  const taches=bases.flatMap(B=>{const l=B.near.filter(x=>x.w===3).sort((x,y)=>x.d-y.d).slice(0,4), vus={}, a=[];
    for(const x of B.near.filter(x=>x.w<3).sort((x,y)=>(y.w-x.w)||(x.d-y.d))){const k=Math.floor(bearing(B,x.p)/60); if(vus[k]>=2) continue; vus[k]=(vus[k]||0)+1; a.push(x); if(a.length>=8-l.length) break;}
    return [...l,...a].map(x=>({B,x}));});
  let fait=0; ld.textContent=`Calcul des trajets à vélo : 0 sur ${taches.length}…`;
  const res=await pool(taches,4,async tk=>{const r=await route(tk.B,[tk.x.p],false); ld.textContent=`Calcul des trajets à vélo : ${++fait} sur ${taches.length}…`; return r;});
  bases.forEach(B=>{B.ok=[]; B.testes=0;});
  taches.forEach((tk,i)=>{const r=res[i]; if(!r) return; tk.B.testes++; if(2*r.km<=b.km&&(r.dplus+r.dmoins)<=b.d&&(2*r.km>=5||tk.x.w===3)) tk.B.ok.push({p:tk.x.p,w:tk.x.w,km:r.km,dedie:r.voies.dedie,note:Math.max(0,noteAcces(r.voies))});});
  if(!res.some(Boolean)){ld.textContent="GéoVélo ne répond pas. Vérifiez la connexion puis relancez la recherche.";return}
  bases.forEach(B=>{const k=B.ok.length, taux=B.testes?k/B.testes:0; B.okl=B.ok.filter(x=>x.w===3).length;
    B.acces=k?B.ok.reduce((a,x)=>a+x.note,0)/k:0; B.km=k?B.ok.reduce((a,x)=>a+x.km,0)/k:0; B.dedie=k?B.ok.reduce((a,x)=>a+x.dedie,0)/k:0;
    B.offre=0.5*Math.min(1,Math.log(1+B.n)/Math.log(31))+0.5*Math.min(1,B.ty.filter(x=>x).length/3); B.nbEst=Math.round(B.nb*taux);
    // de quoi remplir le séjour : des sorties possibles dans plusieurs directions
    B.jours=Math.min(S.sejour?S.sejour.n:7,new Set(B.ok.map(x=>Math.floor(bearing(B,x.p)/45))).size+Math.floor(B.nbEst/12)); const plein=Math.min(1,B.jours/(S.sejour?S.sejour.n:7));
    const rich=(B.rich/maxRich)*taux; B.score=(nl?0.45*B.okl/nl+0.25*rich+0.15*B.acces+0.15*B.offre:0.55*rich+0.3*B.acces+0.15*B.offre)*(0.35+0.65*plein);});
  const top=espaces(bases.filter(B=>B.ok.length>=2).sort((x,y)=>y.score-x.score),8,3);
  if(!top.length){ld.textContent="Les activités repérées dépassent votre budget d’effort depuis ces communes. Augmentez votre distance quotidienne ou passez au vélo électrique.";return}
  ld.hidden=true; S.camps=top;
  list.innerHTML=top.map((B,i)=>`<div class="day" style="cursor:default;grid-template-columns:34px 1fr">
      <div class="daynum" style="background:var(--leaf-deep)">${i+1}</div>
      <div><h3>${esc(B.nom)} ${i===0?'<span class="pill calm">Meilleur compromis</span>':""}</h3>
      <div class="kv">Environ <b>${B.nbEst} activités à votre goût</b> accessibles à vélo, de quoi remplir <b>${B.jours} journée${B.jours>1?"s":""}</b></div>
      <div class="kv">Trajet moyen : <b>${B.km.toFixed(1)} km</b>, dont <b>${pct(B.dedie)}</b> sur voies dédiées au vélo</div>
      <div class="kv">Hébergements Apidae : <b>${B.n}</b> (${offreTxt(B)})</div>
      <div class="kv" style="margin-top:4px">${B.ok.slice().sort((x,y)=>y.w-x.w).slice(0,4).map(x=>esc(x.p.nom)).join(", ")}…</div>
      <button type="button" class="btn small" style="margin-top:10px" data-camp="${i}">Créer mon séjour à ${esc(B.nom)}</button></div></div>`).join("");
  list.querySelectorAll("[data-camp]").forEach(bt=>bt.onclick=()=>{S.base=top[+bt.dataset.camp]; generate(S.base,null);});
  if(typeof L!=="undefined"){ $("campMapBox").hidden=false;
    if(!MAPC){MAPC=L.map("mapCamp",{zoomControl:true}); L.tileLayer("https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&TILEMATRIXSET=PM&FORMAT=image/png&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}",{maxZoom:19,attribution:'© <a href="https://www.ign.fr/">IGN</a> – Plan IGN'}).addTo(MAPC);}
    if(LAYERC) LAYERC.remove(); LAYERC=L.featureGroup().addTo(MAPC);
    const cs=getComputedStyle(document.documentElement);
    // sur la carte : des exemples d'activités accessibles depuis chaque commune proposée
    const vus=new Set(); top.forEach(B=>B.ok.slice(0,5).forEach(x=>{const p=x.p; if(vus.has(p.id)) return; vus.add(p.id);
      L.circleMarker([p.lat,p.lon],{radius:6,color:"#fff",weight:2,fillColor:cs.getPropertyValue("--c-"+p.cat).trim(),fillOpacity:1}).bindTooltip(p.nom).addTo(LAYERC);}));
    top.forEach((B,i)=>L.marker([B.lat,B.lon],{title:B.nom,icon:L.divIcon({className:"",html:`<div class="pin home"><b style="position:static;border:0;background:none;color:#fff;font-size:14px">${i+1}</b></div>`,iconSize:[32,32],iconAnchor:[16,16]})}).addTo(LAYERC));
    setTimeout(()=>{MAPC.invalidateSize(); MAPC.fitBounds(LAYERC.getBounds(),{padding:[28,28],maxZoom:12});},60);}
}

/* ---------- générateur de séjour ---------- */
const DIRS=["le nord","le nord-est","l’est","le sud-est","le sud","le sud-ouest","l’ouest","le nord-ouest"];
function loopInfo(l){const sts=l.stops.map(i=>POI[i]); const main=sts.find(p=>p.cat!=="gastronomie")||sts[0];
  const c={lat:sts.reduce((s,p)=>s+p.lat,0)/sts.length,lon:sts.reduce((s,p)=>s+p.lon,0)/sts.length};
  const br=bearing(S.plan.origin,c); return {main,br,dir:DIRS[Math.round(br/45)%8]};}
function minutes(l){const v=S.velo==="vae"?20:15; return Math.round(l.km/v*60 + l.dplus/100*(S.velo==="vae"?3:8));}
function hm(m){const h=Math.floor(m/60), mm=m%60; return h?`${h} h ${String(mm).padStart(2,"0")}`:`${mm} min`}
function interest(stops,must){const core=stops.filter(p=>p.cat!=="gastronomie");
  let s=core.reduce((a,p)=>a+S.prefs[p.cat]/100,0)/Math.max(1,core.length);
  if(stops.some(p=>p.cat==="gastronomie")) s+=0.25*S.prefs.gastronomie/100;
  const acc=S.plan&&S.plan.acces; if(acc){const n=core.filter(p=>acc.has(p.id)); if(n.length) s+=0.8*n.reduce((a,p)=>a+acc.get(p.id).note,0)/n.length;}
  stops.forEach(p=>{if(S.liked.has(p.id)) s+=1.5; if(must&&p.id===+must) s+=10;}); return s;}
function originAlt(area,origin){const v=[...area.pois,...area.gas].filter(p=>p.alt!=null&&hav(origin,p)<=2.5).map(p=>p.alt).sort((a,b)=>a-b);
  return v.length?v[Math.floor(v.length/2)]:null;}
function candidates(area,origin,b,must=null){
  const rmax=rayon(b), oa=originAlt(area,origin), acc=S.plan.acces;   // l'itinéraire touristique rallonge les boucles
  const tooHigh=p=>oa!=null&&p.alt!=null&&(p.alt-oa)>b.d*0.85;
  S.plan.tooHigh=area.pois.filter(p=>(S.liked.has(p.id)||p.id===+must)&&(tooHigh(p)||hav(origin,p)>rmax)).map(p=>p.nom);
  const A=area.pois.map(p=>({p,d:hav(origin,p),b:bearing(origin,p)})).filter(x=>x.d>0.4&&x.d<=rmax&&!tooHigh(x.p)&&(!acc||acc.has(x.p.id)));
  const valeur=x=>S.prefs[x.p.cat]+(acc&&acc.has(x.p.id)?60*acc.get(x.p.id).note:0);
  const nearGas=(c,r=3)=>area.gas.map(g=>({g,d:hav(c,g)})).filter(x=>x.d<=r).sort((a,b)=>a.d-b.d)[0]?.g;
  const groups={}; A.forEach(x=>{const k=Math.floor(x.b/45)+"-"+(x.d<=rmax/2?0:1); (groups[k]=groups[k]||[]).push(x)});
  const out=[], used=new Set();
  const mk=stops=>{const g=nearGas({lat:stops.reduce((s,p)=>s+p.lat,0)/stops.length,lon:stops.reduce((s,p)=>s+p.lon,0)/stops.length});
    const all=g?[...stops,g]:stops; all.sort((p,q)=>bearing(origin,p)-bearing(origin,q)); stops.forEach(p=>used.add(p.id)); out.push({stops:all.map(p=>p.id),score:interest(all,must)});};
  // 1. coups de cœur et lieu incontournable : une boucle chacun
  A.filter(x=>S.liked.has(x.p.id)||x.p.id===+must).forEach(x=>{if(!used.has(x.p.id)) mk([x.p])});
  // 2. un secteur × anneau = une boucle (jusqu'à 2 lieux de catégories différentes, proches l'un de l'autre)
  Object.values(groups).forEach(g=>{
    g=g.filter(x=>!used.has(x.p.id)).sort((a,b)=>(valeur(b)-valeur(a))||(a.d-b.d));
    const picks=[]; const cats=new Set();
    for(const x of g){ if(picks.length===(b.km<=35?2:3)) break; if(cats.has(x.p.cat)&&g.some(y=>!cats.has(y.p.cat))) continue;
      if(picks.length&&hav(picks[0],x.p)>7) continue; picks.push(x.p); cats.add(x.p.cat);}
    if(picks.length) mk(picks);});
  // 3. boucles gourmandes de proximité (producteurs, fromagers, chocolatiers…) : solution de repli à faible dénivelé
  const PROD=/ferme|fromag|chocolat|miel|cave|cellier|producteur|brasserie|confiserie|tisan|noix|distiller/i;
  const gs={}; area.gas.filter(g=>PROD.test(g.nom)&&!tooHigh(g)).forEach(g=>{const d=hav(origin,g); if(d>0.8&&d<=Math.min(12,rmax)){const k=Math.floor(bearing(origin,g)/45);(gs[k]=gs[k]||[]).push({g,d})}});
  Object.values(gs).forEach(v=>{v.sort((a,b)=>a.d-b.d); const st=[v[0].g]; if(v[1]&&hav(v[0].g,v[1].g)<5) st.push(v[1].g);
    st.sort((p,q)=>bearing(origin,p)-bearing(origin,q)); out.push({stops:st.map(p=>p.id),score:0.2*S.prefs.gastronomie/100+0.05});});
  return out.sort((a,b)=>b.score-a.score);
}
async function generate(B,heb){
  const s=S.sejour||lireDates(); if(!s){go("profil");return false}
  const area=zone(B), origin=heb?{lat:heb.lat,lon:heb.lon}:area.center, b=budget(), {start,end,n,days}=s;
  S.plan={area,base:B,origin,heb,days:[],n,pers:PERS[S.prof]||2,start,end,loading:true};
  go("programme"); const ld=$("loading"); ld.hidden=false; $("days").innerHTML=""; $("daisy").innerHTML=""; $("tip").innerHTML=""; $("hebBox").hidden=true;
  $("gDates").textContent=`Du ${fmtShort(start)} au ${fmtShort(end)}, depuis ${heb?heb.nom:"le centre de "+area.nom} (${area.nom})`;
  // 1. accès cyclable de chaque lieu candidat : itinéraire touristique hébergement -> lieu
  const pre=preselection(area,origin,b); let fait=0;
  ld.textContent=`Évaluation de l’accès à vélo de ${pre.length} lieux : 0 sur ${pre.length}…`;
  const acces=await pool(pre,4,async p=>{const r=await route(origin,[p],false); ld.textContent=`Évaluation de l’accès à vélo de ${pre.length} lieux : ${++fait} sur ${pre.length}…`;
    return {id:p.id,note:noteAcces(r.voies),voies:r.voies,km:r.km};});
  const seuil=seuilDeconseille(); S.plan.acces=new Map(); S.plan.ecartes=[]; S.plan.evalues=0;
  acces.forEach((a,i)=>{ if(!a) return; S.plan.evalues++; const p=pre[i];
    if(a.voies.deconseillee>seuil){ if(S.liked.has(p.id)) S.plan.ecartes.push(p.nom); return; }
    S.plan.acces.set(p.id,a); });
  if(!S.plan.evalues){ld.textContent="GéoVélo ne répond pas. Vérifiez la connexion puis relancez la création du séjour.";return true}
  // 2. boucles composées avec les lieux les mieux desservis
  const cands=candidates(area,origin,b);
  if(!cands.length){ld.textContent=`Aucune activité n’est accessible avec votre distance quotidienne autour de ${area.nom}. Choisissez un autre camp de base, une distance plus longue ou un vélo électrique.`;return true}
  let k=0; ld.textContent=`Calcul des boucles à vélo avec GéoVélo : 0 sur ${cands.length}…`;
  const routed=await pool(cands,4,async c=>{const r=await route(origin,c.stops.map(i=>POI[i])); ld.textContent=`Calcul des boucles à vélo avec GéoVélo : ${++k} sur ${cands.length}…`; return {...c,...r,id:c.stops.join("-")};});
  const ok=routed.filter(Boolean);
  // une journée doit faire au moins 5 km, sauf si elle mène à un coup de cœur
  const feas=ok.filter(l=>l.km<=b.km&&l.dplus<=b.d&&(l.km>=5||l.stops.some(x=>S.liked.has(x))));
  const freqPois=[...new Map(feas.flatMap(loop=>loop.stops.map(id=>POI[id]))
    .filter(p=>p&&p.cat!=="gastronomie").map(p=>[p.id,p])).values()];
  const missingFreqPois=freqPois.filter(p=>!days.every(d=>Number.isFinite(p.freq?.[dateKey(d)]?.t)));
  if(missingFreqPois.length){
    let frequentationChargee=0;
    ld.textContent=`Calcul de l'affluence avec Flux Isère : 0 sur ${missingFreqPois.length}…`;
    await pool(missingFreqPois,4,async p=>{await fluxFrequentation(p,start,n); ld.textContent=`Calcul de l'affluence avec Flux Isère : ${++frequentationChargee} sur ${missingFreqPois.length}…`; return p;});
  }
  ld.hidden=true;
  if(!ok.length){ld.hidden=false;ld.textContent="GéoVélo ne répond pas. Vérifiez la connexion puis relancez la création du séjour.";return true}
  // à intérêt comparable, on préfère les boucles les mieux aménagées pour le vélo
  feas.forEach(l=>{l.score+=l.voies?1.2*l.voies.dedie-2.5*l.voies.deconseillee:0});
  const safe=feas.filter(l=>l.voies&&l.voies.deconseillee<=0.1);
  const routePool=safe.length>=n?safe:feas;
  const forcees=[...routePool].sort((a,c)=>c.score-a.score).slice(0,n).filter(l=>l.stops.some(s=>S.liked.has(s)));
  const chosen=choisirDiversifie(routePool,n,forcees);
  const base=new Map(chosen.map((l,i)=>[l.id,days[i]]));
  const free=new Set(days.map((_,i)=>i)); const assign=new Map();
  [...chosen].sort((a,c)=>Math.max(...days.map(d=>loopT(c,d)))-Math.max(...days.map(d=>loopT(a,d)))).forEach(l=>{
    let best=null,bt=9; free.forEach(i=>{const t=loopT(l,days[i]); if(t<bt-1e-9){bt=t;best=i}}); free.delete(best); assign.set(best,l);});
  const usedIds=new Set(chosen.map(l=>l.id));
  S.plan.days=days.map((d,i)=>{let l=assign.get(i); if(!l) return {d,free:true}; let msg=null; const t=loopT(l,d);
    if(t>=0.75){const main=l.stops.map(x=>POI[x]).find(p=>p.cat!=="gastronomie"); const keep=l.stops.some(x=>S.liked.has(x));
      const alt=!keep&&routePool.filter(x=>!usedIds.has(x.id)&&x.stops.some(y=>POI[y].cat===main?.cat)&&loopT(x,d)<0.55).sort((a,c)=>c.score-a.score)[0];
      if(alt){usedIds.add(alt.id); msg=`${main.nom} sera très fréquenté ce jour-là. Nous vous proposons ${POI[alt.stops.find(y=>POI[y].cat!=="gastronomie")||alt.stops[0]].nom}, une expérience proche, plus au calme.`; l=alt;}}
    if(!msg){const bd=base.get(l.id); if(bd&&bd.getTime()!==d.getTime()){const tb=loopT(l,bd), tc=loopT(l,d);
      if(tb>=0.6&&tc<=tb-0.15){const hot=l.stops.map(x=>POI[x]).sort((a,c)=>tension(c,bd)-tension(a,bd))[0];
        msg=`${hot.nom} est très fréquenté ${wd(bd)}. Nous l’avons programmé ce jour, plus calme.`}}}
    const warningVoies=Boolean(l.voies&&l.voies.deconseillee>0.1);
    return {d,loop:l,t:loopT(l,d),msg,warningVoies,
      versions:[{feedback:null,loop:l,resume:"Parcours initial"}]};});
  S.plan.feas=feas.length; S.plan.routed=ok.length; S.plan.loading=false;
  renderProgramme(); chargerHebergements(B,heb); return true;
}
/* ---------- hébergements de la commune retenue (Apidae, en direct) ---------- */
const TYPES={HEBERGEMENT_LOCATIF:"location",HEBERGEMENT_COLLECTIF:"hébergement collectif",HOTELLERIE:"hôtel",HOTELLERIE_PLEIN_AIR:"camping"};
async function chargerHebergements(B,heb){
  const box=$("hebBox"), sel=$("hebSel");
  try{ if(!B.hebs){const h=await apidae(CFG.sel.heb,B,5,60,0);
      B.hebs=h.objets.map(o=>{const x=o.localisation?.geolocalisation?.geoJson?.coordinates; return x?{id:o.id,nom:o.nom?.libelleFr,type:o.type,lat:x[1],lon:x[0]}:null}).filter(Boolean).sort((p,q)=>hav(B,p)-hav(B,q)).slice(0,30);}
  }catch(e){ box.hidden=true; return }
  if(S.plan.base!==B||!B.hebs.length){box.hidden=true;return}
  sel.innerHTML=`<option value="">Centre de ${esc(B.nom)}</option>`+B.hebs.map(h=>`<option value="${h.id}" ${heb&&heb.id===h.id?"selected":""}>${esc(h.nom)} (${TYPES[h.type]||"hébergement"}, ${hav(B,h).toFixed(1)} km${atoutVelo(h.id)?", "+atoutVelo(h.id):""})</option>`).join("");
  box.hidden=false;
  sel.onchange=()=>{const h=B.hebs.find(x=>String(x.id)===sel.value)||null; generate(B,h);};
}

/* ---------- programme ---------- */
function renderProgramme(){const P=S.plan; $("validMsg").textContent=""; renderDaisy(); resumePros();
  const nFree=P.days.filter(x=>x.free).length;
  const info=P.evalues?`<div class="hint" style="margin:8px 0">Accès à vélo évalué pour ${P.evalues} lieux autour de ${esc(P.area.nom)} : le programme privilégie ceux que l’on rejoint par des voies vertes, des pistes cyclables et des rues apaisées. Vous pouvez changer une activité ou ajuster une journée depuis sa vue détaillée.</div>`:"";
  $("tip").innerHTML=info+(nFree?`<div class="flux">Autour de ${esc(P.area.nom)}, peu de boucles correspondent à la fois à votre distance quotidienne et à un accès vélo bien aménagé. ${S.velo!=="vae"?"Avec un vélo électrique, vous élargirez votre rayon d’action : les loueurs du territoire en proposent à la semaine.":"Augmentez votre distance quotidienne pour élargir votre rayon d’action."}</div>`:"");
  const box=$("days"); box.innerHTML="";
  P.days.forEach((x,i)=>{const b=document.createElement("button"); b.className="day"; b.type="button";
    if(x.free){b.innerHTML=`<div class="daynum" style="background:var(--ink-2)">${i+1}</div><div><h3>${cap(fmtDay(x.d))}</h3><div class="kv">Journée libre : repos, marché ou balade au village. Profitez des commerces de ${esc(P.area.nom)}.</div></div><div></div>`; b.disabled=true; b.style.cursor="default"; box.appendChild(b); return;}
    const inf=loopInfo(x.loop), lv=level(x.t), fav=x.loop.stops.some(s=>S.liked.has(s));
    b.innerHTML=`<div class="daynum" style="background:${LVLC[lv]}">${i+1}</div>
      <div><h3>${cap(fmtDay(x.d))}</h3>
      <div class="kv">Direction : <b>${esc(inf.main.nom)}</b>, vers ${inf.dir}</div>
      <div class="kv" style="display:flex;gap:6px;margin:4px 0" aria-hidden="true">${x.loop.stops.map(s=>`<span class="mk" style="width:24px;height:24px;background:${CATCOL(POI[s].cat)}">${picto(pictoKey(POI[s]))}</span>`).join("")}</div>
      <div class="kv">Temps de trajet : <b>${hm(minutes(x.loop))}</b> ${S.velo==="vae"?"en vélo électrique":"à vélo"}</div>
      <div class="kv">Parcours : <b>${x.loop.km} km</b>, ${x.loop.dplus} m de dénivelé, ${x.loop.stops.length} étape${x.loop.stops.length>1?"s":""}</div>
      <div class="kv">Voies dédiées au vélo : <b>${pct(x.loop.voies?x.loop.voies.dedie:x.loop.green||0)}</b></div>
      <span class="pill ${lv}">${LVL[lv]}</span>${x.modifie?` <span class="pill mid">Modifiée par vous</span>`:""}${x.msg?`<div class="flux">${esc(x.msg)}</div>`:""}${x.warningVoies?`<div class="flux">Une partie de ce trajet emprunte des routes déconseillées aux vélos.</div>`:""}</div>
      <div class="go"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>Voir l’itinéraire</div>`;
    b.onclick=()=>openDay(i); box.appendChild(b);});
}
/* ---------- fin du parcours : les professionnels du vélo aux alentours (écran dédié) ---------- */
/* OpenStreetMap, interrogé en direct depuis le navigateur (API Overpass) : complète DATAtourisme et Apidae */
const OVERPASS=["https://overpass-api.de/api/interpreter","https://overpass.kumi.systems/api/interpreter"];
function osmVersPro(e){const t=e.tags||{}, lat=e.lat??e.center?.lat, lon=e.lon??e.center?.lon; if(lat==null) return null;
  if(Object.keys(t).some(k=>/^(disused|abandoned|was|demolished):/.test(k))||t.opening_hours==="closed"||t.opening_hours==="off") return null;   // fermé ou désaffecté
  if(t.amenity==="bicycle_rental"&&(t.bicycle_rental==="docking_station"||t.bicycle_rental==="dropoff_point")) return null;                 // libre-service : hors sujet pour une semaine
  const loue=t.amenity==="bicycle_rental"||t["service:bicycle:rental"]==="yes"||(t.shop==="rental"&&/bic/.test(t.rental||""));
  const repare=t["service:bicycle:repair"]==="yes"||t.shop==="bicycle"; const nom=(t.name||t.brand||t.operator||"").trim();
  if(!nom||(!loue&&!repare)) return null;
  return {nom,commune:t["addr:city"]||"",lat,lon,tel:t.phone||t["contact:phone"]||"",web:t.website||t["contact:website"]||"",
    vae:/électrique|electrique|e-?bike|vae/i.test(nom)||t["service:bicycle:electric"]==="yes"||/ebike/.test(t.rental||""),
    desc:t.opening_hours?`Horaires : ${t.opening_hours}`:"",src:"OpenStreetMap",av:false,prix:null,repare:!loue};}
async function osmPros(o,rayon=20000){
  const a=`(around:${rayon},${o.lat.toFixed(5)},${o.lon.toFixed(5)})`;
  const q=`[out:json][timeout:20];(nwr["amenity"="bicycle_rental"]${a};nwr["shop"="bicycle"]["service:bicycle:rental"="yes"]${a};nwr["shop"="sports"]["service:bicycle:rental"="yes"]${a};nwr["shop"="rental"]["rental"~"bic"]${a};nwr["shop"="bicycle"]["service:bicycle:repair"="yes"]${a};);out center tags;`;
  for(const u of OVERPASS){ const c=new AbortController(), tm=setTimeout(()=>c.abort(),12000);
    try{ const r=await fetch(u,{method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded"},body:"data="+encodeURIComponent(q),signal:c.signal});
      if(!r.ok) continue; const d=await r.json(); return (d.elements||[]).map(osmVersPro).filter(Boolean);
    }catch(e){}finally{clearTimeout(tm)} }
  return null;}
const cle=s=>norm(s).replace(/[^a-z0-9]/g,"").slice(0,10);
function tousLesPros(){const base=[...LOUEURS], P=S.plan;
  for(const x of (P.osm||[])){ if(base.some(l=>hav(l,x)<0.15||(hav(l,x)<1.5&&cle(l.nom)===cle(x.nom)))) continue; base.push(x); }   // sans doublon avec le catalogue
  return base;}
function prosAutour(){const P=S.plan, veutVae=S.velo==="vae", LOUEURS=tousLesPros();
  return {veutVae,
    loueurs:LOUEURS.filter(l=>!l.repare).map(l=>({l,d:hav(P.origin,l)})).filter(x=>!veutVae||x.l.vae).sort((a,b)=>a.d-b.d).slice(0,3),
    hebs:HEBVELO.map(h=>({h,d:hav(P.origin,h)})).filter(x=>x.d<=12&&(!veutVae||x.h.vae)).sort((a,b)=>a.d-b.d).slice(0,3),
    reps:LOUEURS.filter(l=>l.repare).map(l=>({l,d:hav(P.origin,l)})).filter(x=>x.d<=25).sort((a,b)=>a.d-b.d).slice(0,2)};}
const kmTxt=d=>d<1?"moins de 1 km":`${Math.round(d)} km`;
function resumePros(){const bt=$("prosBtn"); if(!S.plan||S.plan.loading){bt.hidden=true;return}
  const A=prosAutour(), parts=[];
  if(A.loueurs.length) parts.push(`loueur le plus proche à ${kmTxt(A.loueurs[0].d)}`);
  if(A.hebs.length) parts.push(`${A.hebs.length} hébergement${A.hebs.length>1?"s":""} avec vélos`);
  if(A.reps.length) parts.push(`${A.reps.length} réparateur${A.reps.length>1?"s":""}`);
  $("prosResume").textContent=parts.length?"Besoin d’un vélo ou d’un réparateur ? "+cap(parts.join(", "))+".":"Besoin d’un vélo ou d’un réparateur ?";
  bt.hidden=false;}
$("prosBtn").onclick=()=>go("pros");
let MAPP=null, LAYERP=null;
function renderLoueurs(){const P=S.plan, box=$("loueurs"), A=prosAutour(), ou=P.heb?`de ${P.heb.nom}`:`du centre de ${P.area.nom}`;
  $("prSub").textContent=`Autour ${ou} : où louer un vélo, où loger avec des vélos fournis, et qui appeler en cas de pépin.`;
  const liens=(tel,web,lib)=>{const n=(tel||"").replace(/[^+\d]/g,""); return `<div class="liens">${n?`<a href="tel:${n}">${esc(tel)}</a>`:""}${/^https?:\/\//.test(web||"")?`<a href="${esc(web)}" target="_blank" rel="noopener noreferrer">${lib}</a>`:""}</div>`;};
  const num=k=>`<div class="mk num">${k}</div>`; let k=0; const pts=[];
  let h=`<h2>${A.veutVae?"Louer un vélo électrique":"Louer un vélo"}</h2>`;
  if(!A.loueurs.length||A.loueurs[0].d>15) h+=`<div class="flux">Aucun loueur référencé à moins de 15 km. Demandez à votre hébergeur : certains prêtent ou louent des vélos, et des loueurs livrent à domicile.</div>`;
  h+=A.loueurs.map(x=>{const l=x.l; pts.push({k:++k,lat:l.lat,lon:l.lon,nom:l.nom,c:"--leaf-deep"});
    return `<div class="loueur">${num(k)}<div><b>${esc(l.nom)}</b><div class="cat">${l.commune?esc(l.commune)+", ":""}à ${kmTxt(x.d)}</div>
      ${l.av?'<span class="pill calm">Label Accueil Vélo</span> ':""}${l.vae?'<span class="pill calm">Vélos électriques</span> ':""}${l.prix?`<span class="pill mid">Location dès ${l.prix} €</span>`:""}
      ${l.desc?`<p class="kv" style="margin:6px 0 0">${esc(l.desc)}${l.desc.length>=140?"…":""}</p>`:""}${liens(l.tel,l.web,"Site du loueur")}<div class="src">Source : ${esc(l.src)}</div></div></div>`;}).join("");
  if(A.hebs.length) h+=`<h2 style="margin-top:24px">Loger avec des vélos fournis</h2>`+A.hebs.map(x=>{const g=x.h; pts.push({k:++k,lat:g.lat,lon:g.lon,nom:g.nom,c:"--c-nature"});
    const at=[g.pret?"Prêt de vélos":"",g.loc?"Location de vélos":"",g.vae?"Location de vélos électriques":""].filter(Boolean);
    return `<div class="loueur">${num(k)}<div><b>${esc(g.nom)}</b><div class="cat">${cap(TYNOM[g.type][0])}, ${esc(g.commune)}, à ${kmTxt(x.d)}</div>
      ${at.map(a=>`<span class="pill calm">${a}</span>`).join(" ")}${liens(g.tel,g.web,"Site de l’hébergement")}<div class="src">Source : Apidae, fiche n° ${g.id}</div></div></div>`;}).join("");
  if(A.reps.length) h+=`<h2 style="margin-top:24px">En cas de pépin mécanique</h2>`+A.reps.map(x=>{const l=x.l; pts.push({k:++k,lat:l.lat,lon:l.lon,nom:l.nom,c:"--ink-2"});
    return `<div class="loueur">${num(k)}<div><b>${esc(l.nom)}</b><div class="cat">${l.commune?esc(l.commune)+", ":""}à ${kmTxt(x.d)}</div>${l.av?'<span class="pill calm">Label Accueil Vélo</span>':""}
      ${liens(l.tel,l.web,"Site")}<div class="src">Source : ${esc(l.src)}</div></div></div>`;}).join("");
  const etat=P.osm===undefined?"Recherche complémentaire dans OpenStreetMap…":P.osm===null?"OpenStreetMap ne répond pas : la liste se limite à DATAtourisme et Apidae.":`OpenStreetMap consulté dans un rayon de 20 km : ${P.osmAjout} professionnel${P.osmAjout>1?"s":""} ajouté${P.osmAjout>1?"s":""} à la liste.`;
  box.innerHTML=h+`<p class="hint" role="status" style="margin-top:14px">${etat}</p>`;
  if(P.osm===undefined&&!P.osmEnCours){ P.osmEnCours=true;
    osmPros(P.origin).then(r=>{ if(S.plan!==P) return; const avant=LOUEURS.length; P.osm=r; P.osmAjout=r?tousLesPros().length-avant:0; P.osmEnCours=false;
      resumePros(); if($("pros").classList.contains("on")) renderLoueurs(); }); }
  // carte : point de départ et professionnels numérotés
  if(typeof L!=="undefined"&&pts.length){ $("prosMapBox").hidden=false;
    if(!MAPP){MAPP=L.map("mapPros",{zoomControl:true}); L.tileLayer("https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&TILEMATRIXSET=PM&FORMAT=image/png&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}",{maxZoom:19,attribution:'© <a href="https://www.ign.fr/">IGN</a> – Plan IGN'}).addTo(MAPP);}
    if(LAYERP) LAYERP.remove(); LAYERP=L.featureGroup().addTo(MAPP);
    L.marker([P.origin.lat,P.origin.lon],{title:"Votre point de départ",icon:L.divIcon({className:"",html:`<div class="pin home">${picto("maison")}</div>`,iconSize:[32,32],iconAnchor:[16,16]})}).addTo(LAYERP);
    pts.forEach(p=>L.marker([p.lat,p.lon],{title:p.nom,icon:L.divIcon({className:"",html:`<div class="pin" style="background:var(${p.c})"><b style="position:static;border:0;background:none;color:#fff;font-size:13px">${p.k}</b></div>`,iconSize:[28,28],iconAnchor:[14,14]})}).addTo(LAYERP));
    setTimeout(()=>{MAPP.invalidateSize(); MAPP.fitBounds(LAYERP.getBounds(),{padding:[26,26],maxZoom:14});},60);}
  else $("prosMapBox").hidden=true;}
function renderDaisy(){const P=S.plan, svg=$("daisy"); const ls=P.days.filter(x=>!x.free); const maxkm=Math.max(...ls.map(x=>x.loop.km),1);
  let s=`<circle cx="80" cy="80" r="76" style="fill:none;stroke:var(--line)" stroke-dasharray="2 4"/>`;
  ls.forEach((x,i)=>{const inf=loopInfo(x.loop); const L=26+48*(x.loop.km/maxkm); const w=Math.max(9,L*0.32);
    s+=`<g transform="rotate(${inf.br.toFixed(0)} 80 80)"><path class="petal" style="animation-delay:${i*90}ms;fill:${LVLC[level(x.t)]};fill-opacity:.85;stroke:var(--paper);stroke-width:1.5" d="M80 80 C ${80-w} ${80-L*0.45}, ${80-w*0.7} ${80-L}, 80 ${80-L} C ${80+w*0.7} ${80-L}, ${80+w} ${80-L*0.45}, 80 80 Z"/></g>`;});
  s+=`<circle cx="80" cy="80" r="11" style="fill:var(--paper);stroke:var(--leaf-deep);stroke-width:2"/><path d="M75 83v-5l5-4 5 4v5z" style="fill:var(--leaf-deep)"/><text x="80" y="10" text-anchor="middle" font-size="9" style="fill:var(--ink-2)">N</text>`;
  svg.innerHTML=s;}
$("validBtn").onclick=()=>{$("validMsg").textContent="Programme validé. Retrouvez chaque journée dans Mon séjour."; const b=$("prosBtn"); if(!b.hidden) b.scrollIntoView({behavior:reduce?"auto":"smooth",block:"center"});};

/* ---------- pictogrammes (repris des maquettes) ---------- */
const PICTO={
  verre:'<path d="M8 3h8l-1 6a3 3 0 0 1-6 0z"/><path d="M12 12v8M8.5 20.5h7"/>',
  couverts:'<path d="M7 3v18M5 3v5a2 2 0 0 0 4 0V3"/><path d="M17 21V3c-2 1.5-3 4-3 7h3"/>',
  feuille:'<path d="M5 19c0-8 6-14 14-14 0 8-6 14-14 14z"/><path d="M5 19l8-8"/>',
  marteau:'<path d="m14 4 6 6-3 3-6-6z"/><path d="m11 7-8 8 3 3 8-8"/>',
  musee:'<path d="M3 10l9-6 9 6"/><path d="M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18"/>',
  montagne:'<path d="M3 20 9.5 9l3.5 6 2.5-4L21 20z"/><path d="m8 12 1.5-1.5L11 12"/>',
  velo:'<circle cx="6" cy="16.5" r="3.5"/><circle cx="18" cy="16.5" r="3.5"/><path d="M6 16.5 9.5 9h5l3.5 7.5M9.5 9l2.5 7.5 3-7.5M13 6h3"/>',
  marche:'<circle cx="13" cy="4.5" r="1.8"/><path d="m10 21 2-6-3-3 1-5 4 3 3 1M9 12l-3 3"/>',
  eau:'<path d="M12 3c3 4 6 7 6 11a6 6 0 0 1-12 0c0-4 3-7 6-11z"/>',
  maison:'<path d="M4 11 12 4l8 7v9H4z"/><path d="M10 20v-5h4v5"/>'
};
function pictoKey(p){const n=p.nom.toLowerCase();
  if(p.cat==="gastronomie") return /cave|vin|bar\b|liqueur|distiller|brasserie|bière|cellier|cocktail/.test(n)?"verre":"couverts";
  if(/atelier|forge|artisan|poterie|savoir-faire|moulin/.test(n)) return "marteau";
  if(p.cat==="nature") return /lac|cascade|rivière|plan d'eau|étang|source|gorges/.test(n)?"eau":"feuille";
  if(p.cat==="culture") return "musee";
  if(p.cat==="aventure") return "montagne";
  return /vtt|vélo|cycl/.test(n)?"velo":"marche";}
const picto=(k,col="#fff")=>`<svg viewBox="0 0 24 24" fill="none" stroke="${col}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PICTO[k]}</svg>`;

/* ---------- journée + carte OpenStreetMap ---------- */
let MAP=null, LAYER=null;
const ROAD_WARNING="Une partie de ce trajet emprunte des routes déconseillées aux vélos.";
function setAgentProgress(active){
  $("dayFeedbackForm").hidden=active;
  $("dayRequestLabel").hidden=active;
  $("dayRequest").hidden=active;
  $("sendDayFeedback").hidden=active;
  $("agentProgress").hidden=!active;
}
function appendAgentProgress(text){
  const list=$("agentProgressMessages"), item=document.createElement("li");
  item.textContent=String(text);
  list.appendChild(item);
  list.scrollTop=list.scrollHeight;
}
async function ajusterJournee(i){
  const field=$("dayRequest"), feedback=field.value.trim(), status=$("changeStatus"), button=$("sendDayFeedback");
  if(!feedback){status.textContent="Indiquez votre retour.";return}
  const P=S.plan, day=P.days[i], b=budget(), rmax=rayon(b);
  const describe=loop=>loop.stops.map(id=>({id,nom:POI[id]?.nom||"",cat:POI[id]?.cat||""}));
  const payload={
    zone:{lat:P.area.center.lat,lon:P.area.center.lon},
    jour:{
      date:dateKey(day.d),
      hebergement:{lat:P.origin.lat,lon:P.origin.lon,nom:P.heb?.nom||P.area.nom},
      profil:S.prof,velo:S.velo,budget:b,prefs:{...S.prefs},
      rmax,alt_origine:originAlt(P.area,P.origin),
      etapes:describe(day.loop),
      autres_jours:P.days.flatMap((other,index)=>index===i||other.free?[]:[other.loop.stops])
    },
    historique:day.versions.slice(-20).map(version=>({
      feedback:version.feedback,
      etapes:describe(version.loop).map(({id,nom})=>({id,nom})),
      km:version.loop.km,dplus:version.loop.dplus,resume:version.resume
    })),
    feedback,
    variante:"v2",
    profil_geovelo:"RIDE"
  };
  const url=CFG.flux.url.replace(/\/$/,"")+"/api/marguerite/agent";
  const deadline=Date.now()+170000;
  const fetchBeforeDeadline=async(endpoint,options={})=>{
    const remaining=deadline-Date.now();
    if(remaining<=0) throw new Error("L'ajustement a pris trop de temps. Réessayez.");
    const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),remaining);
    try{return await fetch(endpoint,{...options,signal:controller.signal});}
    finally{clearTimeout(timer);}
  };
  let received=0, result=null;
  button.disabled=true;
  status.textContent="";
  $("agentProgressMessages").replaceChildren();
  try{
    const response=await fetchBeforeDeadline(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    const data=await response.json().catch(()=>null);
    if(!response.ok) throw new Error(data?.detail||"Impossible d'ajuster cette journée pour le moment.");
    if(response.status!==202||typeof data?.job!=="string") throw new Error("L'ajustement n'a pas pu démarrer.");
    setAgentProgress(true);
    while(Date.now()<deadline){
      const pollStarted=Date.now();
      const progressResponse=await fetchBeforeDeadline(`${url}/${encodeURIComponent(data.job)}`);
      const progressData=await progressResponse.json().catch(()=>null);
      if(!progressResponse.ok) throw new Error(progressData?.detail||"Impossible de suivre l'ajustement de cette journée.");
      const messages=Array.isArray(progressData?.progression)?progressData.progression:[];
      while(received<messages.length){
        appendAgentProgress(messages[received]?.texte||"");
        received++;
      }
      if(progressData?.etat==="termine"){result=progressData.resultat;break;}
      if(progressData?.etat==="erreur") throw new Error(progressData.erreur?.detail||"Impossible d'ajuster cette journée pour le moment.");
      const pollDelay=1000-(Date.now()-pollStarted), remaining=deadline-Date.now();
      if(pollDelay>0&&remaining>0) await new Promise(resolve=>setTimeout(resolve,Math.min(pollDelay,remaining)));
    }
    if(!result) throw new Error("L'ajustement a pris trop de temps. Réessayez.");
    const loop=result?.loop;
    if(!Array.isArray(loop?.stops)||loop.stops.some(id=>!POI[id])) throw new Error("Le parcours proposé est invalide. Réessayez.");
    const resume=String(result.resume||"");
    const visits=[...new Set(loop.stops.map(id=>POI[id]).filter(p=>p.cat!=="gastronomie"))];
    await pool(visits,4,p=>fluxFrequentation(p,day.d,1));
    // Le serveur ne renvoie que deux parts de voirie : le tracé détaillé est recalculé comme à la génération.
    appendAgentProgress("Tracé détaillé de la nouvelle boucle…");
    const detail=await route(P.origin,loop.stops.map(id=>POI[id])).catch(()=>null);
    const nouvelle={...(detail||{...loop,voies:null}),stops:loop.stops,id:loop.stops.join("-"),score:day.loop.score};
    day.versions.push({feedback,loop:nouvelle,resume});
    day.loop=nouvelle; day.t=loopT(nouvelle,day.d); day.msg=resume; day.modifie=false;
    day.warningVoies=((nouvelle.voies||loop.voies)?.deconseillee||0)>0.1;
    field.value="";
    status.textContent="";
    setAgentProgress(false);
    renderProgramme(); openDay(i);
  }catch(error){
    setAgentProgress(false);
    field.value=feedback;
    status.textContent=error.name==="AbortError"?"L'ajustement a pris trop de temps. Réessayez.":error.message||"Impossible d'ajuster cette journée pour le moment.";
  }finally{
    button.disabled=false;
  }
}
function openDay(i){const x=S.plan.days[i], l=x.loop, inf=loopInfo(l), P=S.plan;
  const where=P.heb?P.heb.nom:`centre de ${P.area.nom}`;
  $("jTitle").textContent=`Jour ${i+1} : vers ${inf.main.nom}`;
  $("jSub").textContent=`${cap(fmtDay(x.d))}, départ et retour : ${where}`;
  $("jStats").innerHTML=`<div class="stat"><b>${l.km} km</b><span>boucle</span></div><div class="stat"><b>${l.dplus} m</b><span>dénivelé +</span></div><div class="stat"><b>${hm(minutes(l))}</b><span>${S.velo==="vae"?"en VAE":"à vélo"}</span></div>`;
  $("jFlux").innerHTML=(x.msg?`<div class="flux">${esc(x.msg)}</div>`:"")+(x.warningVoies?`<div class="flux">${ROAD_WARNING}</div>`:"")+profilHTML(l);
  $("changeStatus").textContent="";
  $("sendDayFeedback").onclick=()=>ajusterJournee(i);
  setAgentProgress(false);
  $("agentProgressMessages").replaceChildren();
  const ol=$("steps"); ol.innerHTML="";
  l.stops.map(s=>POI[s]).forEach((p,k)=>{const lv=level(tension(p,x.d)); const li=document.createElement("li");
    li.innerHTML=`<div class="mk" style="background:${CATCOL(p.cat)}" title="Étape ${k+1}">${picto(pictoKey(p))}</div><button type="button"><span class="cat">Étape ${k+1}</span><br><b>${esc(p.nom)}</b><div class="cat">${CATS[p.cat]}, ${esc(p.commune)}</div><span class="pill ${lv}">${LVL[lv]}</span>${P.acces&&P.acces.has(p.id)?` <span class="pill ${niveauAcces(P.acces.get(p.id))}">${libelleAcces(P.acces.get(p.id))}</span>`:""}</button>`;
    li.querySelector("button").onclick=()=>openPoi(p.id,x.d);
    const ch=document.createElement("button"); ch.type="button"; ch.className="btn small ghost changer"; ch.textContent="Changer"; ch.setAttribute("aria-label",`Changer l’activité ${p.nom}`);
    ch.onclick=()=>ouvrirRemplacement(i,p.id); li.appendChild(ch); ol.appendChild(li);});
  const back=document.createElement("li"); back.innerHTML=`<div class="mk" style="background:var(--leaf-deep)">${picto("maison")}</div><div><b>Retour : ${esc(where)}</b><div class="cat">${esc(P.area.nom)}</div></div>`; ol.appendChild(back);
  go("jour"); renderMap(l,x.d);}
function renderMap(l,d){
  if(typeof L==="undefined"){$("map").innerHTML='<p class="hint" style="padding:12px">Carte indisponible.</p>';return}
  if(!MAP){MAP=L.map("map",{zoomControl:true,attributionControl:true});
    const osmAttr='© <a href="https://www.openstreetmap.org/copyright">les contributeurs d’OpenStreetMap</a>';
    const BASES={
      "Plan IGN": L.tileLayer("https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&TILEMATRIXSET=PM&FORMAT=image/png&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}",
        {maxZoom:19,attribution:'© <a href="https://www.ign.fr/">IGN</a> – Plan IGN'}),
      "Plan OpenStreetMap (CARTO)": L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
        {subdomains:"abcd",maxZoom:19,attribution:osmAttr+' © <a href="https://carto.com/attributions">CARTO</a>'})
    };
    const names=Object.keys(BASES); let cur=0; BASES[names[0]].addTo(MAP);
    L.control.layers(BASES,null,{position:"topright"}).addTo(MAP);
    // bascule automatique si le fond affiché refuse ses tuiles
    names.forEach((nm,i)=>{let fails=0; BASES[nm].on("tileerror",()=>{ if(++fails===4 && MAP.hasLayer(BASES[nm])){
      const nx=names[(i+1)%names.length]; MAP.removeLayer(BASES[nm]); BASES[nx].addTo(MAP); }}); BASES[nm].on("tileload",()=>{fails=0}); });}
  if(LAYER) LAYER.remove(); LAYER=L.featureGroup().addTo(MAP);
  const cs=getComputedStyle(document.documentElement), col=v=>cs.getPropertyValue(v).trim();
  L.polyline(l.geom,{color:"#fff",weight:9,opacity:.95}).addTo(LAYER);
  if(l.segs&&l.segs.length){const C=Object.fromEntries(VOIES.map(o=>[o.k,o.c]));
    l.segs.forEach((sg,i)=>{const fin=i+1<l.segs.length?l.segs[i+1].g:l.geom.length-1; if(fin<=sg.g) return;
      L.polyline(l.geom.slice(sg.g,fin+1),{color:C[sg.c],weight:5,lineCap:"butt"}).addTo(LAYER);});}
  else L.polyline(l.geom,{color:col("--route")||"#A3262A",weight:4.5}).addTo(LAYER);
  l.stops.forEach((s,i)=>{const p=POI[s];
    L.marker([p.lat,p.lon],{title:p.nom,icon:L.divIcon({className:"",html:`<div class="pin">${picto(pictoKey(p))}<b>${i+1}</b></div>`,iconSize:[32,32],iconAnchor:[16,16]})})
     .on("click",()=>openPoi(p.id,d)).addTo(LAYER);});
  const o=S.plan.origin; L.marker([o.lat,o.lon],{title:"Hébergement",icon:L.divIcon({className:"",html:`<div class="pin home">${picto("maison")}</div>`,iconSize:[32,32],iconAnchor:[16,16]})}).addTo(LAYER);
  setTimeout(()=>{MAP.invalidateSize(); MAP.fitBounds(LAYER.getBounds(),{padding:[24,24]});},50);
}

/* ---------- fiche lieu ---------- */
const scrim=$("scrim"); let lastFocus=null, replacementView=0;
function openPoi(id,d){const p=POI[id], lv=level(tension(p,d)), freq=p.freq?.[dateKey(d)]; lastFocus=document.activeElement;
  $("sheet").innerHTML=`${p.img?`<img src="${esc(p.img)}" alt="" referrerpolicy="no-referrer" style="width:100%;height:170px;object-fit:cover;border-radius:14px;margin-bottom:12px">`:""}
   <div class="sheethead"><div><h2 id="sTitle">${esc(p.nom)}</h2><div class="cat">${CATS[p.cat]}, ${esc(p.commune)}</div></div>
   <button class="iconbtn heart" id="favBtn" aria-label="Ajouter aux favoris" aria-pressed="${S.fav.has(id)}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/></svg></button></div>
   <span class="pill ${lv}">${LVL[lv]} ${wd(d)}</span>
   <div class="hint">${Number.isFinite(freq?.t)?`Prévision Flux Isère : ${esc(freq.niveau||"non disponible")} (${esc(freq.calibrage||"non disponible")})`:"Affluence estimée (prévision indisponible)"}</div>
   ${S.plan&&S.plan.acces&&S.plan.acces.has(id)?(a=>`<p class="kv"><b>${libelleAcces(a)}.</b> Depuis votre hébergement : ${a.km} km, dont ${pct(a.voies.dedie)} sur voies dédiées au vélo${a.voies.deconseillee>0.004?` et ${pct(a.voies.deconseillee)} sur routes déconseillées`:""}.</p>`)(S.plan.acces.get(id)):""}
   ${p.desc?`<p>${esc(p.desc)}</p>`:""}${p.ouv?`<p class="kv"><b>Ouverture :</b> ${esc(p.ouv)}</p>`:""}
  <p class="src">Source : Apidae, fiche n° ${p.id}${p.credit?`. Photo © ${esc(p.credit)}`:""}</p><button class="btn ghost" id="closeSheet">Fermer</button>`;
  scrim.classList.add("on"); document.body.classList.add("sheet-open"); $("sheet").scrollTop=0; $("closeSheet").focus({preventScroll:true}); $("closeSheet").onclick=closeSheet;
  $("favBtn").onclick=e=>{const b=e.currentTarget; S.fav.has(id)?S.fav.delete(id):S.fav.add(id); b.setAttribute("aria-pressed",S.fav.has(id));};}
/* ---------- remplacer une activité d'une journée ---------- */
async function alternatives(i,id){const P=S.plan, x=P.days[i], vieux=POI[id], b=budget(), rmax=rayon(b), oa=originAlt(P.area,P.origin);
  const pris=new Set(P.days.filter(y=>!y.free).flatMap(y=>y.loop.stops));
  const source=vieux.cat==="gastronomie"?P.area.gas:P.area.pois;
  const candidats=source.filter(p=>!pris.has(p.id)&&hav(P.origin,p)>0.4&&hav(P.origin,p)<=rmax&&!(oa!=null&&p.alt!=null&&Math.abs(p.alt-oa)>b.d*0.6));
  const missing=candidats.filter(p=>p.cat!=="gastronomie"&&!Number.isFinite(p.freq?.[dateKey(x.d)]?.t));
  await pool(missing,4,p=>fluxFrequentation(p,x.d,1));
  const C=candidats
    .map(p=>{const d=hav(vieux,p), acc=P.acces&&P.acces.get(p.id);
      return {p,d,meme:p.cat===vieux.cat,s:(p.cat===vieux.cat?1:0)+S.prefs[p.cat]/100+(S.liked.has(p.id)?0.6:0)+(acc?0.4*acc.note:0)+(p.img?0.1:0)-d/4-0.5*tension(p,x.d)};})
    .sort((a,c)=>c.s-a.s);
  // on reste dans le même secteur que l'activité remplacée quand il y a assez de choix
  const proches=C.filter(c=>c.d<=8); if(proches.length>=3) C.splice(0,C.length,...proches);
  // trois activités du même type, puis une idée d'un autre type pour changer
  const out=C.filter(c=>c.meme).slice(0,3); const autre=C.find(c=>!c.meme); if(autre) out.push(autre);
  return out.length>=2?out:C.slice(0,4);}
async function ouvrirRemplacement(i,id){const view=++replacementView, P=S.plan, x=P.days[i], vieux=POI[id]; lastFocus=document.activeElement;
  $("sheet").innerHTML=`<div class="sheethead"><div><h2 id="sTitle">Changer d’activité</h2><div class="cat">${cap(fmtDay(x.d))} : à la place de ${esc(vieux.nom)}</div></div></div>
    <div id="altMsg" class="flux" role="status" hidden></div>
    <div id="altList" class="flux" role="status">Prévisions d’affluence en cours…</div>
    <button class="btn ghost" id="closeSheet" style="margin-top:12px">Garder l’activité actuelle</button>`;
  scrim.classList.add("on"); document.body.classList.add("sheet-open"); $("sheet").scrollTop=0; $("closeSheet").focus({preventScroll:true}); $("closeSheet").onclick=closeSheet;
  const alts=await alternatives(i,id);
  if(view!==replacementView||S.plan!==P||!scrim.classList.contains("on")) return;
  $("altList").outerHTML=`<div id="altList">${alts.length?alts.map((a,k)=>{const lv=level(tension(a.p,x.d)), acc=P.acces&&P.acces.get(a.p.id);
      return `<div class="alt">${a.p.img?`<img src="${esc(a.p.img)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">`:`<div class="mk" style="background:${CATCOL(a.p.cat)};width:64px;height:64px;border-radius:12px">${picto(pictoKey(a.p))}</div>`}
        <div><b>${esc(a.p.nom)}</b><div class="cat">${CATS[a.p.cat]}, ${esc(a.p.commune)}, à ${a.d.toFixed(1)} km de l’activité actuelle</div>
        <span class="pill ${lv}">${LVL[lv]}</span>${acc?` <span class="pill ${niveauAcces(acc)}">${libelleAcces(acc)}</span>`:""}
        <div><button type="button" class="btn small" data-alt="${k}" style="margin-top:8px">Choisir</button></div></div></div>`;}).join(""):`<p class="kv">Aucune autre activité de saison n’est disponible à portée de vélo pour cette journée.</p>`}</div>`;
  $("sheet").querySelectorAll("[data-alt]").forEach(bt=>bt.onclick=()=>remplacer(i,id,alts[+bt.dataset.alt].p,false));}
async function remplacer(i,id,nouveau,force){const P=S.plan, x=P.days[i], b=budget(), msg=$("altMsg"), list=$("altList");
  msg.hidden=false; msg.textContent=`Calcul de la nouvelle boucle avec ${nouveau.nom}…`; list.querySelectorAll("button").forEach(bt=>bt.disabled=true);
  const stops=x.loop.stops.map(s=>s===id?nouveau.id:s).map(s=>POI[s]).sort((p,q)=>bearing(P.origin,p)-bearing(P.origin,q));
  let r=x.essai&&x.essai.id===nouveau.id?x.essai.r:null;
  if(!r){ try{ r=await route(P.origin,stops); }catch(e){ msg.textContent="GéoVélo ne répond pas. Réessayez dans un instant."; list.querySelectorAll("button").forEach(bt=>bt.disabled=false); return; } }
  if(!force&&(r.km>b.km||r.dplus>b.d)){ x.essai={id:nouveau.id,r};
    msg.innerHTML=`Avec ${esc(nouveau.nom)}, la journée passerait à <b>${r.km} km</b> et <b>${r.dplus} m</b> de dénivelé, au-delà de votre limite (${b.km} km, ${b.d} m). <div class="actions" style="margin-top:8px"><button type="button" class="btn small" id="altForce">Choisir quand même</button></div>`;
    list.querySelectorAll("button").forEach(bt=>bt.disabled=false); $("altForce").onclick=()=>remplacer(i,id,nouveau,true); return; }
  x.essai=null; const ancien=POI[id];
  x.loop={...r,stops:stops.map(p=>p.id),id:stops.map(p=>p.id).join("-"),score:x.loop.score};
  x.t=loopT(x.loop,x.d); x.modifie=true; x.msg=`Vous avez remplacé ${ancien.nom} par ${nouveau.nom}. La boucle a été recalculée.`;
  x.warningVoies=Boolean(r.voies&&r.voies.deconseillee>0.1);
  // le remplacement manuel entre dans l'historique transmis aux ajustements suivants
  x.versions.push({feedback:`Remplacement manuel de ${ancien.nom} par ${nouveau.nom}`,loop:x.loop,resume:x.msg});
  closeSheet(); renderProgramme(); openDay(i); }

function closeSheet(){replacementView++;scrim.classList.remove("on"); document.body.classList.remove("sheet-open"); lastFocus&&lastFocus.focus({preventScroll:true})}
scrim.onclick=e=>{if(e.target===scrim) closeSheet()};
document.addEventListener("keydown",e=>{if(e.key==="Escape"){closeSheet();closeMenu()}});

/* ---------- vue territoire ---------- */
function renderTerritory(){const P=S.plan; if(!P||P.loading){$("kpis").innerHTML=`<div class="kpi" style="grid-column:1/-1"><span>Créez un séjour pour voir son effet sur le territoire.</span></div>`;$("bars").innerHTML="";return}
  const ls=P.days.filter(x=>!x.free); const km=ls.reduce((a,x)=>a+x.loop.km,0);
  const shops=new Set(ls.flatMap(x=>x.loop.stops).filter(s=>POI[s].cat==="gastronomie")).size;
  const moved=ls.filter(x=>x.msg).length; const spend=P.n*P.pers*68;
  $("kpis").innerHTML=`<div class="kpi"><b>${Math.round(km)} km</b><span>parcourus à vélo, sans voiture</span></div>
   <div class="kpi"><b>${moved}</b><span>visite${moved>1?"s":""} décalée${moved>1?"s":""} ou réorientée${moved>1?"s":""} vers un moment plus calme</span></div>
   <div class="kpi"><b>${shops}</b><span>commerce${shops>1?"s":""} ${shops>1?"locaux":"local"} sur les parcours</span></div>
   <div class="kpi"><b>${spend.toLocaleString("fr-FR")} €</b><span>de dépense estimée sur le territoire (${P.n} j × ${P.pers} pers.)</span></div>`;
  $("bars").innerHTML=ls.map(x=>{const lv=level(x.t);return `<div class="barrow"><span>${cap(new Intl.DateTimeFormat("fr-FR",{weekday:"short",day:"numeric"}).format(x.d))}</span><div class="track"><div class="fill" style="width:${Math.round(x.t*100)}%;background:${LVLC[lv]}"></div></div><span class="cat">${LVL[lv].replace("Affluence ","")}</span></div>`}).join("");}
