# Interface Nuxt — équipe 2

Migration de la maquette V3 en Nuxt 4, Vue 3 et TypeScript. Depuis ce dossier :

```sh
npm ci
npm run dev
```

Ouvrir http://localhost:3000. Node.js 24.15.0 ou plus récent dans la série 24 (voir `.nvmrc`) requis. Autres commandes :

```sh
npm test
npm run typecheck
npm run build
npm run preview
```

## Organisation

- `app/pages/index.vue` : composition de l'écran.
- `app/components/` : en-tête, semaine, courbe horaire, réglage des seuils.
- `app/composables/useDashboard.ts` : sélection du site, dates, disponibilité et état réactif.
- `app/utils/forecast.ts` : règles de dates et seuils, calcul de la courbe illustrative.
- `app/data/` : fixtures, catalogue des sites et instantanés des calendriers.
- `app/assets/css/main.css` : styles de la maquette, adaptations mobiles.
- `tests/` : limites de prévision, seuils et cohérence des valeurs affichées.

## Comportements

Les semaines vont du lundi au dimanche. Seuls aujourd'hui (date de Paris) et les six jours suivants sont sélectionnables ; les autres jours restent indisponibles. Le bouton « Revenir à aujourd'hui » apparaît seulement hors de la semaine actuelle. Les badges signalent les jours fériés et vacances zone A. Les seuils valides s'appliquent immédiatement ; une saisie incohérente conserve les dernières valeurs valides.

Les données Herretang sont simulées ; les autres sites et les archives affichent un état vide, sans réutiliser les résultats de l'Herretang. Les modifications restent en mémoire de la page.

## Raccordement backend

Aucun backend NestJS n'est présent sur la branche de départ. Aucun service supplémentaire n'est créé ici. Remplacer les fixtures du composable par des appels à l'API lorsque son contrat est validé ; conserver les dates ISO, unités et états indisponibles explicites.

Le pipeline Python voisin produit actuellement des **passages par jour**. La courbe horaire, la météo et la référence historique de cette interface sont illustratives : ne pas répartir arbitrairement une prévision journalière pour la présenter comme une prévision horaire réelle. Les seuils de cette maquette portent sur les passages horaires et doivent être harmonisés avec le futur contrat API.

Calendriers embarqués : jours fériés issus de https://calendrier.api.gouv.fr/jours-feries/metropole.json ; vacances Grenoble, populations élèves/commune, issues de https://data.education.gouv.fr/explore/dataset/fr-en-calendrier-scolaire/ (périodes 2025–2027). Dates locales, début inclus et fin exclue. Actualiser les instantanés avant un usage sur une autre période.

La période Ascension 2027 de l’instantané source a une fin égale au début : elle est écartée tant que la source n’est pas corrigée.
