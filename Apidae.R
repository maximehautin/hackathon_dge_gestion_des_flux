### Récupérer la sélection Apidae et les identifiants ###

library(httr2)
library(jsonlite)

projet_id <- 9657

requete <- list(
  projetId = projet_id,
  apiKey = "3Ch7iOsI"
)

reponse <- request(
  "https://api.apidae-tourisme.com/api/v002/referentiel/selections/"
) |>
  req_body_form(
    query = toJSON(requete, auto_unbox = TRUE)
  ) |>
  req_perform()

selections <- resp_body_json(reponse)

selections

### Visualiser la sélection possible dans le projet ###
str(selections)



### Ouvrir les jeux de données ###

# Installer les packages si nécessaire
install.packages(c("httr2", "jsonlite", "dplyr", "tibble"))

# Charger les packages
library(httr2)
library(jsonlite)
library(dplyr)
library(tibble)


# ---------------------------------------------------------
# 1. Informations de connexion Apidae
# ---------------------------------------------------------

projet_id <- 9657
selection_id <- list(211884,211888,211889,211890,211891,211892,211905,211906,211908,211911,211914,211999)   #Modifier ici la sélection
api_key <- "3Ch7iOsI"


# ---------------------------------------------------------
# 2. Construire la requête (ici sur les 100 premiers, à modifier)
# ---------------------------------------------------------

requete <- list(
  projetId = projet_id,
  apiKey = api_key,
  selectionIds = selection_id,
  count = 100,
  first = 0
)


# ---------------------------------------------------------
# 3. Interroger l'API Apidae
# ---------------------------------------------------------

url <- "https://api.apidae-tourisme.com/api/v002/recherche/list-objets-touristiques/"

reponse <- request(url) |>
  req_method("POST") |>
  req_body_form(
    query = toJSON(requete, auto_unbox = TRUE)
  ) |>
  req_error(is_error = function(resp) FALSE) |>
  req_perform()


# ---------------------------------------------------------
# 4. Récupérer les données
# ---------------------------------------------------------

donnees <- resp_body_json(reponse)


# Afficher la structure de la réponse
str(donnees)

names(donnees$objetsTouristiques[[1]]) #colonnes dispos