library(httr2)
library(jsonlite)
library(purrr)
library(dplyr)
library(tibble)

# ======================================================================================
# 1. CRITERES DE SELECTION #peut aussi être des aom par exemple, voir la documentation
# ======================================================================================

covered_area <- list(
  insee = "38",
  nom   = "Isère",
  type  = "departement"
)

# ==================================================
# 2. IMPORTER LE CATALOGUE DE L'API
# ==================================================

url_api <- "https://transport.data.gouv.fr/api/datasets"

reponse <- request(url_api) |>
  req_timeout(120) |>
  req_perform()

stopifnot(resp_status(reponse) == 200)

datasets <- fromJSON(
  resp_body_string(reponse),
  simplifyVector = FALSE
)

cat("Nombre total de jeux de données :", length(datasets), "\n")

# ==================================================
# 3. FILTRER LES JEUX DE DONNEES SUR L'ISERE
# ==================================================

datasets_isere <- keep(datasets, function(dataset) {
  
  zones <- dataset$covered_area
  
  if (is.null(zones) || length(zones) == 0) {
    return(FALSE)
  }
  
  any(map_lgl(zones, function(zone) {
    identical(as.character(zone$insee), covered_area$insee) &&
      identical(as.character(zone$nom), covered_area$nom) &&
      identical(as.character(zone$type), covered_area$type)
  }))
})

cat("Jeux de données couvrant l'Isère :",
    length(datasets_isere), "\n")

# ==================================================
# 4. CREER UN TABLEAU RECAPITULATIF
# ==================================================

resultats <- map_dfr(datasets_isere, function(dataset) {
  
  tibble(
    id = as.character(dataset$id),
    titre = dataset$title,
    type = dataset$type,
    url_page = dataset$page_url,
    nombre_ressources = length(dataset$resources)
  )
})

print(resultats)

# ==================================================
# 5. EXPORTER LE CATALOGUE FILTRE
# ==================================================

write.csv(
  resultats,
  "catalogue_transports_isere.csv",
  row.names = FALSE,
  fileEncoding = "UTF-8"
)