# ============================================================
#        RÉCUPÉRATION DE DONNÉES OPENSTREETMAP
# ============================================================
install.packages("osmdata")

library(osmdata)
library(sf)

# ----------- PARAMÈTRES À MODIFIER --------------------------

# Zone géographique
zone <- getbb(
  "Isère, Auvergne-Rhône-Alpes, France",
  format_out = "osm_type_id"
)

# Tag OpenStreetMap
cle <- "amenity"              #A modifier
valeur <- "restaurant"        #A modifier

# ------------------------------------------------------------



requete <- opq(bbox = zone) |>
  add_osm_feature(
    key = cle,
    value = valeur,
  )

donnees <- osmdata_sf(requete)

# Les objets sont répartis selon leur géométrie :
# Points
points <- donnees$osm_points

# Lignes
lignes <- donnees$osm_lines

# Polygones
polygones <- donnees$osm_polygons

# Multipolygones
multipolygones <- donnees$osm_multipolygons

# ------------------------------------------------------------
# Affichage
# ------------------------------------------------------------

plot(polygones["name"])
plot(multipolygones["name"])
plot(points["name"])



# ------------------------------------------------------------
# Exporter
# ------------------------------------------------------------

install.packages("writexl")
library(writexl)

# Export Excel
couches <- c(
  "osm_points", "osm_lines", "osm_multilines",
  "osm_polygons", "osm_multipolygons"
)

fichier_excel <- lapply(couches, function(nom) {
  couche <- donnees[[nom]]
  
  if (is.null(couche) || nrow(couche) == 0) {
    return(NULL)
  }
  
  as.data.frame(st_drop_geometry(couche))
})

names(fichier_excel) <- couches
fichier_excel <- Filter(Negate(is.null), fichier_excel)

write_xlsx(fichier_excel, "resultat_Isere.xlsx")