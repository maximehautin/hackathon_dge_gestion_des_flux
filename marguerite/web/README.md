# Marguerite – parcours v2 (des envies vers le camp de base)

Cette variante est intégrée à Flux Isère et accessible sur `/marguerite/v2`. Le parcours historique reste accessible sur `/marguerite`.

## Ce qui change par rapport à `marguerite/src/`

Le visiteur ne choisit plus sa commune au départ. Il exprime ses envies, et l'application en déduit où loger.

1. **Votre séjour** : nom, type de groupe (pictogrammes solo, couple, famille, groupe), destination (Isère seule pour la démonstration), dates, vélo, distance à vélo par jour. Un compteur indique le nombre d'activités de saison accessibles avec cette distance.
2. **Qu'est-ce qui vous tente ?** : swipe adaptatif sur des activités réelles de toute l'Isère, limitées à celles qui sont de saison et à portée de vélo d'une commune où l'on peut loger. Les réponses servent au profil et aux notes ; elles ne sont pas affichées ensuite.
3. **Vos envies** : profil déduit, curseurs ajustables.
4. **Où poser vos valises ?** : 348 communes comparées. Note fondée sur le nombre d'activités au goût du visiteur accessibles à vélo, la qualité des aménagements cyclables (itinéraires GéoVélo réels), l'offre d'hébergement Apidae et la capacité à remplir le séjour.
5. **Le séjour** : boucles quotidiennes depuis la commune retenue, puis depuis l'hébergement Apidae choisi.
6. **Changer une activité** : dans le détail d'une journée, bouton « Changer » sur chaque étape. Jusqu'à quatre alternatives de saison, proches de l'activité remplacée ; la boucle est recalculée, avec un avertissement si elle dépasse la distance quotidienne.
7. **Les professionnels du vélo aux alentours** : écran accessible à la fin du programme et depuis le menu. Carte et fiches numérotées en trois rubriques : où louer un vélo, où loger avec des vélos fournis, qui appeler en cas de pépin mécanique.

Autres évolutions :
- **Itinéraire touristique GéoVélo (profil `RIDE`) partout**, avec le profil de voirie de chaque journée (voie verte, piste, bande, rue apaisée, route ordinaire, route déconseillée) et le tracé coloré par type de voie.
- **Accès cyclable de chaque lieu évalué avant de composer les boucles** ; les lieux accessibles surtout par des routes déconseillées sont écartés (seuil plus strict en famille).
- **Catalogue de 2 426 activités** intégré à la page (`src/catalogue.json`), élargi aux randonnées balisées, sites VTT et équipements de plein air d'Apidae, nettoyé des fiches de clubs géolocalisées au siège.
- **Saisonnalité** : pas de raquettes ni de ski hors saison de neige, pas de baignade hors belle saison, et respect des périodes d'ouverture Apidae du type « Du 15/12 au 31/03 ».

## Professionnels du vélo : sources

| Source | Ce qu'elle apporte | Volume en Isère |
|---|---|---|
| DATAtourisme | Commerces de location, périodes d'ouverture, label Accueil Vélo, tarifs | 19 loueurs en activité, 4 réparateurs labellisés |
| Apidae, commerces et services (211906, 211908) | Type structuré « Loueur de vélos ou VTT » | 4 loueurs |
| Apidae, hébergements (211890) | Prestations déclarées : prêt, location, abri à vélos | 160 hébergements prêtent ou louent des vélos, 1 402 ont un abri |
| OpenStreetMap (Overpass) | `amenity=bicycle_rental`, `shop=bicycle` avec `service:bicycle:rental=yes`, magasins qui réparent | Interrogé en direct par l'application, dans un rayon de 20 km |

- Un loueur est retenu s'il est **en activité** : période d'ouverture en cours, à venir ou close depuis moins d'un an, ou fiche mise à jour depuis le début de l'année.
- Le menu de choix de l'hébergement signale ceux qui prêtent ou louent des vélos, ou qui ont un abri.
- OpenStreetMap est appelé depuis le navigateur. Si Overpass ne répond pas, l'écran s'affiche avec les autres sources. **Cet appel n'a été testé qu'avec une réponse simulée**, les serveurs Overpass n'étant pas accessibles depuis l'environnement de développement.
- Pour une liste figée, `r/OSM_loueurs.R` (adapté du script OSM.R du hackathon, non exécuté) ou un export Overpass Turbo produisent un fichier que `pipeline/build_loueurs_osm.py` intègre au catalogue.

## Lancer

```bash
cd web
python pipeline/build_app.py            # génère app/index.html sans clé (non versionné)
# sur une autre origine que Flux Isère, définir FLUX_API_URL avant le build
# ex. FLUX_API_URL=https://flux-isere.antoine42.com python pipeline/build_app.py
# en production, la page est servie sur /marguerite/v2 et utilise la même origine

# Facultatif : reconstruire src/catalogue.json (chaque script ne remplace que sa partie)
python pipeline/build_catalogue.py            # activités et communes, depuis Apidae
python pipeline/build_hebergements_velo.py    # hébergements qui prêtent ou louent des vélos, depuis Apidae
export DATATOURISME_API_KEY=...
python pipeline/build_loueurs.py              # loueurs et réparateurs en activité, depuis DATAtourisme et Apidae
python pipeline/build_loueurs_osm.py export.geojson   # complément à partir d'un export OpenStreetMap
```

## Intégration à Flux Isère : faite

La page `/marguerite/v2` utilise les relais serveur Apidae et GéoVélo, les prévisions d'affluence Flux Isère et ne contient pas de clé d'API.

Fonctionnalités de la v1 qui restent à porter :

- conseil horaire ;
- lieux similaires pour les alternatives ;
- ajustement libre d'une journée.

## Limites connues

- L'agglomération grenobloise arrive souvent en tête des camps de base (densité d'activités, relief plat, réseau cyclable).
- En montagne, le nombre de journées annoncé pour un camp de base est parfois optimiste.
- Les règles de saison par nom sont approximatives.
- Quelques fiches Apidae restent géolocalisées à l'adresse du prestataire.
- Professionnels du vélo : distances à vol d'oiseau ; 23 loueurs pour tout le département, certains secteurs n'en ont aucun ; la présence de vélos électriques est déduite du texte des fiches ; OpenStreetMap n'indique pas si un commerce est toujours en activité.
