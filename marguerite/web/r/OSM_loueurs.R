# ============================================================
#   LOUEURS ET RÉPARATEURS DE VÉLOS EN ISÈRE - OPENSTREETMAP
#   Adapté du script OSM.R du hackathon (paquet osmdata).
#   Produit loueurs_osm.geojson, à intégrer avec :
#     python pipeline/build_loueurs_osm.py loueurs_osm.geojson src/catalogue.json
# ============================================================
# install.packages(c("osmdata", "sf", "dplyr"))
library(osmdata)
library(sf)
library(dplyr)

zone <- getbb("Isère, Auvergne-Rhône-Alpes, France", format_out = "osm_type_id")

# Une requête par combinaison de tags
requetes <- list(
  opq(bbox = zone, timeout = 90) |> add_osm_feature(key = "amenity", value = "bicycle_rental"),
  opq(bbox = zone, timeout = 90) |> add_osm_features(features = list("shop" = "bicycle", "service:bicycle:rental" = "yes")),
  opq(bbox = zone, timeout = 90) |> add_osm_features(features = list("shop" = "sports",  "service:bicycle:rental" = "yes")),
  opq(bbox = zone, timeout = 90) |> add_osm_features(features = list("shop" = "bicycle", "service:bicycle:repair" = "yes"))
)

# Points, et centre des bâtiments quand le commerce est dessiné en polygone
vers_points <- function(q) {
  d <- osmdata_sf(q)
  couches <- list(d$osm_points, d$osm_polygons, d$osm_multipolygons)
  couches <- couches[!vapply(couches, function(x) is.null(x) || nrow(x) == 0, logical(1))]
  if (length(couches) == 0) return(NULL)
  couches <- lapply(couches, function(x) {
    x <- suppressWarnings(st_centroid(st_make_valid(x)))
    x |> mutate(across(-geometry, as.character))
  })
  bind_rows(couches)
}

resultat <- bind_rows(lapply(requetes, vers_points))

# On ne garde que les objets nommés, sans doublon, et les tags utiles
tags <- c("osm_id", "name", "brand", "operator", "amenity", "shop", "rental", "bicycle_rental",
          "service:bicycle:rental", "service:bicycle:repair", "service:bicycle:electric",
          "opening_hours", "phone", "contact:phone", "website", "contact:website", "addr:city")
resultat <- resultat |>
  filter(!is.na(name) | !is.na(brand) | !is.na(operator)) |>
  distinct(osm_id, .keep_all = TRUE) |>
  select(any_of(tags))

message(nrow(resultat), " loueurs, stations et réparateurs trouvés dans OpenStreetMap")
st_write(st_transform(resultat, 4326), "loueurs_osm.geojson", delete_dsn = TRUE)
