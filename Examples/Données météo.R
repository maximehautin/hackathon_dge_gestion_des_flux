#### 1986-2024 ####


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



mon_schema <- schema(
  NUM_POSTE = string(),
  NOM_USUEL = string(),
  LAT = float64(),
  LON = float64(),
  ALTI = float64(),
  AAAAMMJJ = int64(),
  RR = float64(),
  QRR = string(),
  TN = float64(),
  QTN = string(),
  HTN = string(),
  QHTN = string(),
  TX = float64(),
  QTX = string(),
  HTX = string(),
  QHTX = string(),
  TM = float64(),
  QTM = string(),
  TNTXM = string(),
  QTNTXM = string(),    
  TAMPLI = string(),
  QTAMPLI = string(),
  TNSOL  = string(),    
  QTNSOL = string(),      
  TN50 = string(),
  QTN50 = string(),
  DG            = string(),
  QDG           = string(),
  FFM           = string(),
  QFFM = string(),
  FF2M = string(),
  QFF2M = string(),
  FXY          = string(),
  QFXY         = string(),
  DXY = string(),
  QDXY         = string(),
  HXY = string(),
  QHXY = string(),
  FXI = string(),
  QFXI = string(),
  DXI = string(),
  QDXI = string(),
  HXI = string(),
  QHXI = string(),
  FXI2 = string(),
  QFXI2 = string(),
  DXI2 = string(),
  QDXI2 = string(),
  HXI2 = string(),
  QHXI2       = string(),
  FXI3S = string(),
  QFXI3S = string(),
  DXI3S = string(),
  QDXI3S = string(),
  HXI3S = string(),
  QHXI3S = string(),
  DRR = string(),
  QDRR = string(),
  STATUS_FXI3S = string(),
  STATUS_DXI3S = string(),
)


dataset <- open_dataset(
  "maximehautin/Q_38_previous-1950-2024_RR-T-Vent.csv.gz",
  filesystem = fs,
  format = "csv",
  delimiter = ";",
  schema = mon_schema,
  skip = 1
)





# ============================================================
# Filtrer les données Météo-France : 1986 à 2024
# ============================================================

# Afficher la structure du dataset
schema(dataset)


# ------------------------------------------------------------
# 1. Filtrer les dates
# ------------------------------------------------------------

# Filtrer les données entre 1986 et 2024
library(dplyr)


dataset_1986_2024 <- dataset |>
  dplyr::filter(
    AAAAMMJJ >= 19860101,
    AAAAMMJJ <= 20241231
  ) |>
  dplyr::select(
    NUM_POSTE,
    NOM_USUEL,
    LAT,
    LON,
    ALTI,
    AAAAMMJJ,
    RR,
    TN,
    TX,
    TM,
  )




# ------------------------------------------------------------
# 2. Vérifier le résultat
# ------------------------------------------------------------

# Afficher quelques lignes
dataset_1986_2024 |>
  head()


# ------------------------------------------------------------
# 3. Exporter le résultat
# ------------------------------------------------------------

donnees_meteo_1986_2024 <- dataset_1986_2024 |>
  dplyr::collect()


library(readr)

write_csv(
  donnees_meteo_1986_2024,
  "RR-T-Vent_1986-2024.csv"
)




rm(list=ls())












###### 1950-1985 #####

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



mon_schema <- schema(
  NUM_POSTE = string(),
  NOM_USUEL = string(),
  LAT = float64(),
  LON = float64(),
  ALTI = float64(),
  AAAAMMJJ = int64(),
  RR = float64(),
  QRR = string(),
  TN = float64(),
  QTN = string(),
  HTN = string(),
  QHTN = string(),
  TX = float64(),
  QTX = string(),
  HTX = string(),
  QHTX = string(),
  TM = float64(),
  QTM = string(),
  TNTXM = string(),
  QTNTXM = string(),    
  TAMPLI = string(),
  QTAMPLI = string(),
  TNSOL  = string(),    
  QTNSOL = string(),      
  TN50 = string(),
  QTN50 = string(),
  DG            = string(),
  QDG           = string(),
  FFM           = string(),
  QFFM = string(),
  FF2M = string(),
  QFF2M = string(),
  FXY          = string(),
  QFXY         = string(),
  DXY = string(),
  QDXY         = string(),
  HXY = string(),
  QHXY = string(),
  FXI = string(),
  QFXI = string(),
  DXI = string(),
  QDXI = string(),
  HXI = string(),
  QHXI = string(),
  FXI2 = string(),
  QFXI2 = string(),
  DXI2 = string(),
  QDXI2 = string(),
  HXI2 = string(),
  QHXI2       = string(),
  FXI3S = string(),
  QFXI3S = string(),
  DXI3S = string(),
  QDXI3S = string(),
  HXI3S = string(),
  QHXI3S = string(),
  DRR = string(),
  QDRR = string(),
  STATUS_FXI3S = string(),
  STATUS_DXI3S = string(),
)


dataset <- open_dataset(
  "maximehautin/Q_38_previous-1950-2024_RR-T-Vent.csv.gz",
  filesystem = fs,
  format = "csv",
  delimiter = ";",
  schema = mon_schema,
  skip = 1
)





# ============================================================
# Filtrer les données Météo-France : 1950 à 1985
# ============================================================

# Afficher la structure du dataset
schema(dataset)


# ------------------------------------------------------------
# 1. Filtrer les dates
# ------------------------------------------------------------

# Filtrer les données entre 1950 et 1985
library(dplyr)


dataset_1950_1985 <- dataset |>
  dplyr::filter(
    AAAAMMJJ >= 19500101,
    AAAAMMJJ <= 19851231
  ) |>
  dplyr::select(
    NUM_POSTE,
    NOM_USUEL,
    LAT,
    LON,
    ALTI,
    AAAAMMJJ,
    RR,
    TN,
    TX,
    TM,
  )




# ------------------------------------------------------------
# 2. Vérifier le résultat
# ------------------------------------------------------------

# Afficher quelques lignes
dataset_1950_1985 |>
  head()


# ------------------------------------------------------------
# 3. Exporter le résultat
# ------------------------------------------------------------

donnees_meteo_1950_1985 <- dataset_1950_1985 |>
  dplyr::collect()


library(readr)

write_csv(
  donnees_meteo_1950_1985,
  "RR-T-Vent_1950_1985.csv"
)




rm(list=ls())