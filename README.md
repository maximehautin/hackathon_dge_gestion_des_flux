# Hackathon — Gestion des flux touristiques

## Équipe 6

Réalisé pendant le hackathon de la DGE des **9 et 10 novembre 2026**, ce projet vise à mieux répartir les flux touristiques en **Isère** en proposant aux visiteurs des alternatives adaptées à leurs préférences.

La question centrale : **comment mieux répartir les visiteurs entre les sites très fréquentés de l’Isère et leurs alternatives ?**

## Objectifs

- Réorienter les flux touristiques d’un site à un autre.
- Prendre en compte les attentes et les préférences des visiteurs pour proposer des alternatives pertinentes.
- Proposer un autre lieu ou un autre créneau lorsqu’un site est saturé.

## Réalisations

Trois outils ont été construits pendant le hackathon :

| Outil | Description | Accès |
| :--- | :--- | :--- |
| **Portail de documentation** | Données du SSP Cloud, 76 sources, fiches des sites, graphiques, matching et présentations. | [Consulter le portail](https://hackathon-flux-touristique.vicode.fr) |
| **Plutôt là — application visiteur** | Propose un autre lieu ou un autre créneau lorsqu’un site est saturé. | [Ouvrir l’application](https://plutola.hackathon-flux-touristique.vicode.fr) |
| **SDK du widget Plutôt là** | Permet d’intégrer le widget sur le site d’un office de tourisme ou d’un partenaire. | [Découvrir le SDK](https://sdk.hackathon-flux-touristique.vicode.fr) |

Le code source du portail, de l’application, du widget et des scripts de données est disponible dans le [dépôt des réalisations](https://github.com/vguerand/hackathon-flux-touristique).

## Fonctionnement

La démarche repose sur trois étapes :

1. Prendre en compte les préférences et les besoins du visiteur.
2. Identifier des alternatives adaptées à ces préférences.
3. Proposer un autre site ou un autre créneau pour mieux répartir la fréquentation.

Selon la [présentation des réalisations](PARTAGE.md), aucun compte n’est nécessaire et aucune donnée personnelle n’est envoyée : les préférences du visiteur restent sur son téléphone. Les chiffres calculés par le portail sont marqués « (déduit) » et chaque graphique cite sa source.

## Résultat attendu

Aider les visiteurs à découvrir des alternatives pertinentes tout en favorisant une meilleure répartition de la fréquentation entre les sites touristiques.

## Explorer le projet

- **Voir la vidéo** : [regarder sur Google Drive](https://drive.google.com/file/d/1vC_3GZ53nj1inDqwUo5MWHkGotZrZEmD/view?usp=sharing).
- **Découvrir le hackathon** : [les problématiques](https://hackathon-flux-touristique.vicode.fr/problematiques) et [les propositions de projets](https://hackathon-flux-touristique.vicode.fr/propositions).
- **Explorer les données** : [DataViz](https://hackathon-flux-touristique.vicode.fr/dataviz) et [les données SSP Cloud](https://hackathon-flux-touristique.vicode.fr/donnees-ssp).
- **Comprendre l’application** : [la documentation de Plutôt là](https://hackathon-flux-touristique.vicode.fr/plutotla).
- **Intégrer le widget** : [le tutoriel](https://hackathon-flux-touristique.vicode.fr/widgets/integrer), [l’éditeur](https://sdk.hackathon-flux-touristique.vicode.fr/editor) et [les exemples](https://sdk.hackathon-flux-touristique.vicode.fr/examples).

## Intégrer le widget

Ajouter ces deux lignes à la page du site partenaire :

```html
<script type="module" src="https://sdk.hackathon-flux-touristique.vicode.fr/embed/plutot-la-widget.js"></script>
<plutot-la-widget partenaire="alpes-isere" lieu="le-lac-de-paladru-38082"></plutot-la-widget>
```

L’[éditeur du widget](https://sdk.hackathon-flux-touristique.vicode.fr/editor) permet de générer le code aux couleurs du partenaire.

## Contenu de ce dépôt

- [PARTAGE.md](PARTAGE.md) : présentation des réalisations et liens de partage.
- [Examples/](Examples/) : exemples de scripts R pour explorer les sources de données et les services utiles au projet.
- [Livrable intermédiaire](Livrables/Livrable%20intermédiaire.md) : document de travail du hackathon.

## Licence

Ce projet est distribué sous licence [MIT](LICENSE).
