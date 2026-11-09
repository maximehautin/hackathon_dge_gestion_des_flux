# ----------------------------------------------------------------------
# Exemple d'utilisation de l'API Biodivsport pour les zones sensibles 
# Voir toutes les possibilités : https://biodiv-sports.fr/api/v2/#operations-tag-sensitivearea
# ----------------------------------------------------------------------


library(httr2)
library(sf)
library(dplyr)

# -----------------------------------------------------------------------------
### Récupérer les zones sensibles sur l'Isère en français au format geojson ###
# -----------------------------------------------------------------------------

# 1. Télécharger toutes les zones sensibles Biodiv'Sports
url_api <- "https://biodiv-sports.fr/api/v2/sensitivearea/"

reponse <- request(url_api) |>
  req_url_query(
    format = "geojson",
    language = "fr"
  ) |>
  req_perform()

resp_check_status(reponse)

# Importer les données GeoJSON
fichier_temp <- tempfile(fileext = ".geojson")
writeLines(resp_body_string(reponse), fichier_temp, useBytes = TRUE)

zones <- st_read(fichier_temp, quiet = TRUE)


# 2. Charger les contours administratifs des départements
url_departements <- paste0(
  "https://etalab-datasets.geo.data.gouv.fr/",
  "contours-administratifs/2025/geojson/",
  "departements-100m.geojson"
)

departements <- st_read(url_departements, quiet = TRUE)


# 3. Extraire le contour de l'Isère (code INSEE 38)
Isere <- departements |>
  filter(code == "38")


# 4. Harmoniser les systèmes de coordonnées
Isere <- st_transform(Isere, st_crs(zones))

# Corriger les éventuelles géométries invalides
zones <- st_make_valid(zones)
Isere <- st_make_valid(Isere)


# 5. Garder les zones Biodiv'Sports qui intersectent l'Isère
zones_isere <- st_filter(
  zones,
  Isere,
  .predicate = st_intersects
)


# 6. Afficher les résultats
cat("Nombre de zones en intersection avec l'Isère :",
    nrow(zones_isere), "\n")

plot(
  st_geometry(Isere),
  col = "grey95",
  border = "black",
  main = "Zones sensibles Biodiv'Sports en Isère"
)

plot(
  st_geometry(zones_isere),
  add = TRUE,
  col = "lightblue",
  border = "blue"
)



