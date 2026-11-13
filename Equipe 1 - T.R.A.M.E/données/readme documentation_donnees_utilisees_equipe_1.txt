Deux jeux de données métiers principaux ont été utilisées pendant ce hackathon:

- Les comptages journaliers des écocompteurs de l'Isere : s3://projet-hackathon-gestion-flux-isere/diffusion/Fréquentation/eco-compteur-Isère/comptages/comptages_journalier_2025_2026.csv 
- les données de parkings issus d'Open Street Map (position, capacité d'accueil) 

Sont également mis en avant  les fonds de cartes IGN et OSM suivants :
Plan IGN style simple :  https://fab-geocommuns.github.io/carte-facile-site/fr/
ADMIN EXPRESS : Limites administratives 
Chemins et sentiers balisés issus de OSM. 

Un filtrage des comptages journaliers a été réalisé en  selectionnant les comptages estivaux (juin, juillet, aout) lié à l'activité pedestre (pedestrian) . Ils ont été transformé en estimation voiture / jour en ramenant le chiffre une activité journaliere et en partant du principe que 2,5 pietons etaient dans une voiture.  

Les données parkings d'OSM ont été transformées en grille carrée sur l'Isère 500x500m en integrant la capacité théorique maximale (nombreb de places) et le nombre de parkings présents (en l'absence d'un nombre de place) 

Les jeux de données finaux produits sont disponibles dans le GitHub
