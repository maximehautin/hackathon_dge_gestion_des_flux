install.packages(c("httr2", "jsonlite"))

library(httr2)
library(jsonlite)

# ============================================================
# API GEOVELO - CALCUL D'ITINERAIRE A VELO
# ============================================================


# 1. PARAMETRES A MODIFIER
# ------------------------------------------------------------

# URL de l'API
url_api <- "https://backend.geovelo.fr/api/v2/computedroutes"

# Cle API : remplacer par ta propre cle
cle_api <- "Ma clé"  #Clé pour le hackathon dispo dans l'excel données à disposition


# Coordonnees du depart
depart_lat <- 45.367018
depart_lon <- 5.593923
depart_nom <- "Musée Mainssieux - Voiron"

# Coordonnees de l'arrivee
arrivee_lat <- 44.816186
arrivee_lon <- 5.522818
arrivee_nom <- "Monument du Pas de l'Aiguille - Chichilianne"

# Options de calcul
profil_velo <- "MEDIAN"   #Remplacer le profil par "RIDE" pour n'avoir que l'itinéraire touristique en résultat
type_velo <- "TRADITIONAL"
vitesse_moyenne <- 15

instructions <- FALSE
elevations <- FALSE
geometry <- TRUE
single_result <- FALSE
show_ride_itinerary <- TRUE   #à ajouter pour voir l'itinéraire touristique


# 2. CONSTRUCTION DU CORPS JSON
# ------------------------------------------------------------

corps <- list(
  
  waypoints = list(
    
    list(
      latitude = depart_lat,
      longitude = depart_lon,
      title = depart_nom
    ),
    
    list(
      latitude = arrivee_lat,
      longitude = arrivee_lon,
      title = arrivee_nom
    )
    
  ),
  
  bikeDetails = list(
    profile = profil_velo,
    bikeType = type_velo,
    averageSpeed = vitesse_moyenne
  ),
  
  transportModes = c("BIKE", "PEDESTRIAN")
  
)


# 3. CONSTRUCTION DE LA REQUETE
# ------------------------------------------------------------

requete <- request(url_api) |>
  req_url_query(
    instructions = tolower(as.character(instructions)),
    elevations = tolower(as.character(elevations)),
    geometry = tolower(as.character(geometry)),
    single_result = tolower(as.character(single_result))
  ) |>
  req_headers(
    `Content-Type` = "application/json",
    `Api-Key` = cle_api
  ) |>
  req_body_json(corps, auto_unbox = TRUE)


# 4. ENVOI DE LA REQUETE
# ------------------------------------------------------------

reponse <- req_perform(requete)


# 5. LECTURE DE LA REPONSE
# ------------------------------------------------------------

# Afficher le code HTTP
print(resp_status(reponse))

# Lire la reponse JSON dans R
resultat <- resp_body_json(
  reponse,
  simplifyVector = FALSE
)

# Afficher la structure complete
str(resultat)

# Afficher le contenu complet
print(resultat)
