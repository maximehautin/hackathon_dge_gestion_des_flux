# Hackathon « Gestion des flux touristiques » en Isère

Pendant le hackathon de la DGE (9 et 10 novembre 2026), nous avons construit trois choses autour d'une même question : **comment mieux répartir les visiteurs entre les sites très fréquentés de l'Isère et leurs alternatives ?**

## Les liens

|  | Lien | En une phrase |
| :---- | :---- | :---- |
| 📚 **Documentation** | [hackathon-flux-touristique.vicode.fr](https://hackathon-flux-touristique.vicode.fr) | Le portail : données du SSP Cloud, 76 sources, fiches des sites, graphiques, matching, présentations. |
| 📱 **Plutôt là** (application) | [plutola.hackathon-flux-touristique.vicode.fr](https://plutola.hackathon-flux-touristique.vicode.fr) | L'application visiteur : un site est saturé ? Elle propose un autre lieu ou un autre créneau. |
| 🧩 **SDK du widget** | [sdk.hackathon-flux-touristique.vicode.fr](https://sdk.hackathon-flux-touristique.vicode.fr) | Le widget Plutôt là à intégrer sur le site d'un office de tourisme ou d'un partenaire. |
| 💻 **Code source** | [github.com/vguerand/hackathon-flux-touristique](https://github.com/vguerand/hackathon-flux-touristique) | Tout le dépôt : portail, application, widget, scripts de données. |

## Pour aller plus vite

- **Découvrir le hackathon** : [les problématiques](https://hackathon-flux-touristique.vicode.fr/problematiques) et [les propositions de projets](https://hackathon-flux-touristique.vicode.fr/propositions)  
- **Explorer les données** : [l'onglet DataViz](https://hackathon-flux-touristique.vicode.fr/dataviz) et [les données SSP Cloud](https://hackathon-flux-touristique.vicode.fr/donnees-ssp)  
- **Comprendre l'application** : [la documentation de Plutôt là](https://hackathon-flux-touristique.vicode.fr/plutotla)  
- **Intégrer le widget** : [le tutoriel](https://hackathon-flux-touristique.vicode.fr/widgets/integrer), [l'éditeur](https://sdk.hackathon-flux-touristique.vicode.fr/editor) et [les exemples](https://sdk.hackathon-flux-touristique.vicode.fr/examples)

Intégrer le widget sur un site tient en deux lignes :

```html
<script type="module" src="https://sdk.hackathon-flux-touristique.vicode.fr/embed/plutot-la-widget.js"></script>
<plutot-la-widget partenaire="alpes-isere" lieu="le-lac-de-paladru-38082"></plutot-la-widget>
```

Le code à vos couleurs se génère dans [l'éditeur](https://sdk.hackathon-flux-touristique.vicode.fr/editor).

## Bon à savoir

- Aucun compte, aucune donnée personnelle envoyée : les préférences du visiteur restent sur son téléphone.  
- Les chiffres calculés par le portail sont marqués « (déduit) » et chaque graphique cite sa source.