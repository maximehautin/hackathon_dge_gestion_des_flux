---------------------------------------------
  ### Télécharger les données gtfs Loopi ###
  ---------------------------------------------
  
library(httr2)

request("https://transport.loopi.fr/api/v1/datas/loopi/gtfs.zip") |>
  req_headers(Authorization = "Bearer m3B0vQvpxi-L1TjwKRaeOQ") |>
  req_perform(path = "loopi.zip")

unzip("loopi.zip", exdir = "loopi_gtfs")
stops <- read.csv("loopi_gtfs/stops.txt")



---------------------------------------------
  ### Exemple de calcul d'itinéraire
---------------------------------------------
  
library(httr2)
library(jsonlite)

# --- Coordonnées à modifier ici (longitude, latitude) ---
point_depart  <- c(5.72921, 45.164059)  #cité de l'Arlequin, Grenoble
point_arrivee <- c(5.327656375375591, 45.83711769976123)   #Château d'Amblérieu


base_url <- "https://api.loopi.fr/1.0"

# 1. Connexion
resp_login <- request(paste0(base_url, "/user/login")) |>
  req_body_json(list(
    email    = "hackathon@loopi.fr",
    password =  "Mot de passe"     #Mot de passe pour le hackathon dispo dans l'excel données à disposition      
  ), auto_unbox = TRUE) |>
  req_perform()

token <- resp_body_json(resp_login)$accessToken

# 2. Itinéraire recommandé en vélo   
    ### Privilégie les aménagements cyclables, et ajoute la variante rapide quand elle fait gagner du temps.

body <- list(
  coordinates = list(point_depart, point_arrivee),
  langue      = "fr",
  type        = "velo",
  steps       = TRUE,
  debug       = TRUE
)

resp <- request(paste0(base_url, "/route/recommande")) |>    #endpoint à modifier selon ce qu'on souhaite calculer (cf.documentation API)
  req_headers(Authorization = paste("Bearer", token)) |>
  req_body_json(body, auto_unbox = TRUE) |>
  req_error(is_error = \(r) FALSE) |>
  req_perform()

cat("Statut HTTP :", resp_status(resp), "\n")
resultat <- resp_body_json(resp)
write_json(resultat, "itineraire.json", auto_unbox = TRUE, pretty = TRUE)     #L'itinéraire apparaît dans les fichiers au format json
str(resultat, max.level = 2)
