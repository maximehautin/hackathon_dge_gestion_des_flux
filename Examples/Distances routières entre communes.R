#Cette première partie est faite pour récupérer le fichier dans son emplacement
#sur datalab.sspcloud.fr de l'Insee (Onyxia). Il faut changer les clés d'accès
#selon ce qui est indiqué dans les paramètres d'emplacement du fichier communes d'Isere en .csv


install.packages("arrow", repos = "https://cloud.r-project.org")

Sys.setenv(AWS_PROFILE = "default")
library(arrow)

fs <- S3FileSystem$create(
  region = "us-east-1",
  endpoint_override = "minio.lab.sspcloud.fr",
  scheme = "https"
)

dataset <- open_dataset(
  "maximehautin/Communes-d_Isere.csv",
  filesystem = fs,
  format = "csv"
)

print(head(as.data.frame(dataset)))



#On va ici créer un premier dataset avec 2 colonnes, le code Insee et le nom de la commune


install.packages(c(
  "readxl",
  "writexl",
  "httr",
  "jsonlite",
  "dplyr",
  "osrm"
))

communes <- as.data.frame(dataset)

library(dplyr)

names(communes) <- c("code_insee", "commune")

head(communes)


#Cette partie permet d'aller chercher les coordonnées géographiques du centre de
#chacune des 512 communes d'Isère.
#C'est le centroïde géométrique de la commune, le centre du polygone formé par la commune


library(httr)
library(jsonlite)

get_coord <- function(code){
  
  url <- paste0(
    "https://geo.api.gouv.fr/communes/",
    code,
    "?fields=centre"
  )
  
  req <- GET(url)
  
  res <- fromJSON(content(req, "text", encoding = "UTF-8"))
  
  data.frame(
    lon = res$centre$coordinates[1],
    lat = res$centre$coordinates[2]
  )
}


#Dans cette partie on va ajouter au dataset une 3ème colonne contenant les coordonnées
#du centre de chacune des 512 communes. L'utilisation de map_dfr avec un sys.sleep
#a pour but de ralentir la vitesse de création du du fichier coords (50 secondes pour le tout)
#car quand ça allait trop vite ça buggait

library(purrr)

coords <- map_dfr(
  communes$code_insee,
  ~{
    Sys.sleep(0.1)
    get_coord(.x)
  }
)

communes <- bind_cols(communes, coords)



#On va ensuite chercher les données de distance routière (et non à vol d'oiseau) entre chaque point
#Les données routières sont celles de openstreetmap


library(osrm)

options(osrm.server = "https://router.project-osrm.org/")
options(osrm.profile = "car")

pts <- data.frame(
  id = communes$commune,
  lon = communes$lon,
  lat = communes$lat
)


#On va créer une colonne géométrie ici combinant longitude et latitude pour être 
#dans le même format que les données OpenStreetMap


library(sf)

pts <- st_as_sf(
  pts,
  coords = c("lon", "lat"),
  crs = 4326
)


#On crée une boucle pour aller créer une matrice contenant la distance des 512 
#communes selon les 511 autres communes

n <- nrow(pts)

matrice <- matrix(
  NA,
  nrow = n,
  ncol = n,
  dimnames = list(pts$id, pts$id)
)

taille_bloc <- 50

for(i in seq(1, n, by = taille_bloc)){
  
  i2 <- min(i + taille_bloc - 1, n)
  
  cat("Lignes", i, "à", i2, "\n")
  
  for(j in seq(1, n, by = taille_bloc)){
    
    j2 <- min(j + taille_bloc - 1, n)
    
    cat("Colonnes", j, "à", j2, "\n")
    
    res <- osrmTable(
      src = pts[i:i2, ],
      dst = pts[j:j2, ],
      measure = "distance"
    )
    
    matrice[i:i2, j:j2] <- res$distances
  }
}



#On exporte cette matrice dans un fichier excel

library(writexl)

write_xlsx(
  as.data.frame(matrice),
  "Distances_routieres_Isere.xlsx"
)