# =====================================================================
#  Import de données DATAtourisme (API v1) dans R
#  Documentation : https://api.datatourisme.fr/v1/docs
# =====================================================================


# ---------------------------------------------------------------------
# 0. PACKAGES
# ---------------------------------------------------------------------
paquets   <- c("httr2", "dplyr", "purrr", "ggplot2", "leaflet")
manquants <- setdiff(paquets, rownames(installed.packages()))
if (length(manquants) > 0) install.packages(manquants)
invisible(lapply(paquets, library, character.only = TRUE))


# ---------------------------------------------------------------------
# 1. PARAMÈTRES  (✏️ = à modifier selon votre besoin)
# ---------------------------------------------------------------------

# ✏️ [1] CLÉ API ------------------------------------------------------
# Clé à obtenir sur https://www.datatourisme.fr/utiliser-les-donnees
# Possible d'utiliser celle déjà entrer, créée spécialement pour le hackathon

API_KEY <- "Ma clé"      #Clé pour le hackathon dispo dans l'excel données à disposition

BASE_URL <- "https://api.datatourisme.fr/v1"

# ✏️ [2] TYPE DE DONNÉES APPELÉES (endpoint) --------------------------
#   "catalog"               : tous les POI (lieux, événements, itinéraires, produits)
#   "placeOfInterest"       : lieux d'intérêt
#   "entertainmentAndEvent" : fêtes et manifestations
#   "tour"                  : itinéraires
#   "product"               : produits
ENDPOINT <- "placeOfInterest"

# ✏️ [2bis] TERRITOIRE : TOUJOURS L'ISÈRE ------------------------------
# Le filtre sur le département de l'Isère (INSEE 38) est appliqué.
DEPARTEMENT_INSEE <- "38"

# En option, restreindre à certaines communes et/ou communautés de communes
# d'Isère (laisser NULL pour couvrir tout le département). Les deux listes
# se cumulent (union). Les noms sont convertis en codes INSEE via l'API
# geo.api.gouv.fr (gratuite, sans clé) : pensez à vérifier les correspondances
# affichées dans la console au lancement.
COMMUNES          <- NULL   # ex. c("Grenoble", "Voiron", "Bourg-d'Oisans")
INTERCOMMUNALITES <- NULL   # ex. c("Le Grésivaudan", "Grenoble-Alpes-Métropole", "Pays Voironnais")
CODES_INSEE_COMMUNES <- NULL  # alternative/complément : codes INSEE directs, ex. c("38185", "38564")

# ✏️ [3] AUTRES FILTRES -------------------------------------------------
# Tous les paramètres ci-dessous sont optionnels : laisser NULL pour ignorer.

# Syntaxe : champ[opérateur]=valeur, combinables avec AND / OR / parenthèses.
# Opérateurs : eq, ne, gt, gte, lt, lte, in, nin, between, text, prefix, fuzzy, exists
# Exemples :
#   "isLocatedAt.address.postalCode[prefix]=382"                              (code postal)
#   "lastUpdate[gte]=2026-01-01"                                              (mis à jour depuis)
#   "type[eq]=Museum AND hasReview.hasReviewValue[gt]=3"
#   "type=Restaurant AND (isEquippedWith=Wifi OR isEquippedWith=CarPark)"
# Les valeurs possibles (Theme, Amenity...) s'obtiennent avec thesaurus("Theme").
FILTRES <- "type=Restaurant"

# Recherche de texte sur les noms et descriptions (ex. "château", "musée -art") -> un seul à la fois
RECHERCHE <- NULL

# Recherche géographique (une seule des deux à la fois, en général)
GEO_DISTANCE <- NULL   # "lat,lon,rayon"   ex. "48.1173,-1.6778,10km"
GEO_BOUNDING <- NULL   # "lat_haut_gauche,lon_haut_gauche,lat_bas_droite,lon_bas_droite"

# Tri (ex. "lastUpdate[desc]", "label", "_score[desc]")
TRI <- NULL

# Langue(s) des champs textuels : "fr", "fr,en" ou "*" pour toutes
LANGUES <- "fr"

# ✏️ [4] CHAMPS RETOURNÉS ---------------------------------------------
# NULL = sélection par défaut de l'API (nom, type, localisation, adresse,
# contact, description, dates de mise à jour...).
# ATTENTION : si vous renseignez FIELDS, il REMPLACE la sélection par défaut :
# il faut alors lister TOUS les champs voulus. Exemple pour des événements :
#   FIELDS <- "uuid,label,type,isLocatedAt,takesPlaceAt,lastUpdate"
FIELDS <- NULL

# ✏️ [5] COLONNES DU TABLEAU FINAL --------------------------------------
# nom_colonne = "chemin.dans.le.json"   (même syntaxe que dans l'API)
# On peut donner plusieurs chemins possibles : le premier non vide est retenu.
# Pour ajouter une colonne : ajouter une ligne (le champ doit être retourné par l'API,
# donc présent dans la sélection par défaut ou dans FIELDS).
COLONNES <- list(
  uuid        = "uuid",
  nom         = "label",
  type        = "type",
  commune     = c("isLocatedAt.address.hasAddressCity.label",
                  "isLocatedAt.address.addressLocality"),
  code_postal = "isLocatedAt.address.postalCode",
  adresse     = "isLocatedAt.address.streetAddress",
  latitude    = "isLocatedAt.geo.latitude",
  longitude   = "isLocatedAt.geo.longitude",
  maj         = "lastUpdate"
  # Pour les événements (nécessite FIELDS avec takesPlaceAt), décommenter :
  # , date_debut = "takesPlaceAt.startDate"
  # , date_fin   = "takesPlaceAt.endDate"
)

# ✏️ [6] VOLUME ET RESPECT DES QUOTAS -----------------------------------
# Limites de l'API : 1000 requêtes/heure, ~10 requêtes/seconde, 100 résultats max par page.
# => 1 page = 1 requête.
TAILLE_PAGE <- 100     # 1 à 100
MAX_PAGES   <- 5       # sécurité : nombre maximal de pages téléchargées
PAUSE       <- 0.2     # secondes entre deux requêtes

LANGUE_AFFICHEE <- "fr"  # langue retenue quand un champ est multilingue


# ---------------------------------------------------------------------
# 2. FONCTIONS  (en principe rien à modifier)
# ---------------------------------------------------------------------

# --- Territoire : Isère toujours, communes / communautés de communes en option ---

GEO_URL <- "https://geo.api.gouv.fr"

# Minuscules sans accents, pour comparer des noms
normaliser <- \(x) tolower(iconv(x, to = "ASCII//TRANSLIT"))

# Appel de l'API geo.api.gouv.fr (renvoie un data.frame, ou une liste vide)
appel_geo <- function(chemin, ...) {
  request(paste0(GEO_URL, chemin)) |>
    req_url_query(...) |>
    req_retry(max_tries = 3) |>
    req_perform() |>
    resp_body_json(simplifyVector = TRUE)
}

# Noms de communes -> codes INSEE (dans le département choisi uniquement)
codes_insee_communes <- function(noms) {
  unlist(lapply(noms, function(nom) {
    res <- appel_geo("/communes", nom = nom, codeDepartement = DEPARTEMENT_INSEE,
                     fields = "nom,code", limit = 5)
    if (length(res) == 0 || nrow(res) == 0) {
      warning("Commune introuvable dans le département ", DEPARTEMENT_INSEE, " : ", nom)
      return(NULL)
    }
    exact <- which(normaliser(res$nom) == normaliser(nom))
    choix <- if (length(exact) > 0) exact[1] else 1
    message(sprintf("Commune « %s » -> %s (%s)", nom, res$nom[choix], res$code[choix]))
    res$code[choix]
  }))
}

# Noms de communautés de communes / EPCI -> codes INSEE de leurs communes isèroises
codes_insee_epci <- function(noms) {
  unlist(lapply(noms, function(nom) {
    res <- appel_geo("/epcis", nom = nom, codeDepartement = DEPARTEMENT_INSEE,
                     fields = "nom,code", limit = 5)
    if (length(res) == 0 || nrow(res) == 0) {
      warning("Intercommunalité introuvable dans le département ", DEPARTEMENT_INSEE, " : ", nom)
      return(NULL)
    }
    partiel <- which(grepl(normaliser(nom), normaliser(res$nom), fixed = TRUE))
    choix   <- if (length(partiel) > 0) partiel[1] else 1
    message(sprintf("Intercommunalité « %s » -> %s (SIREN %s)%s", nom, res$nom[choix],
                    res$code[choix],
                    if (nrow(res) > 1) paste0(" ; autres candidats : ",
                                              paste(res$nom[-choix], collapse = ", ")) else ""))
    communes <- appel_geo(paste0("/epcis/", res$code[choix], "/communes"), fields = "nom,code")
    # on ne garde que les communes du département (une EPCI peut déborder)
    codes <- communes$code[startsWith(communes$code, DEPARTEMENT_INSEE)]
    message(sprintf("  %s commune(s) retenue(s) en Isère", length(codes)))
    codes
  }))
}

# Assemble le filtre final : Isère (toujours) + communes (option) + autres filtres (option)
construire_filtre_final <- function() {
  champ_dep   <- "isLocatedAt.address.hasAddressCity.isPartOfDepartment.insee"
  champ_ville <- "isLocatedAt.address.hasAddressCity.insee"
  
  filtres <- paste0(champ_dep, "[eq]=", DEPARTEMENT_INSEE)   # toujours appliqué
  
  codes <- unique(c(
    if (!is.null(COMMUNES))             codes_insee_communes(COMMUNES),
    if (!is.null(INTERCOMMUNALITES))    codes_insee_epci(INTERCOMMUNALITES),
    CODES_INSEE_COMMUNES
  ))
  if (!is.null(COMMUNES) || !is.null(INTERCOMMUNALITES) || !is.null(CODES_INSEE_COMMUNES)) {
    if (length(codes) == 0) stop("Aucune commune trouvée pour les noms demandés : import annulé.")
    filtres <- c(filtres, paste0(champ_ville, "[in]=", paste(codes, collapse = ",")))
  }
  if (!is.null(FILTRES)) filtres <- c(filtres, paste0("(", FILTRES, ")"))
  
  paste(filtres, collapse = " AND ")
}

# Construit la requête HTTP (1re page, ou page suivante si `url` est fournie)
construire_requete <- function(url = NULL) {
  if (is.null(url)) {
    req <- request(paste0(BASE_URL, "/", ENDPOINT)) |>
      req_url_query(
        page_size    = TAILLE_PAGE,
        lang         = LANGUES,
        filters      = FILTRE_FINAL,    # Isère + communes + autres filtres
        search       = RECHERCHE,
        fields       = FIELDS,
        sort         = TRI,
        geo_distance = GEO_DISTANCE,
        geo_bounding = GEO_BOUNDING     # les paramètres NULL sont ignorés
      )
  } else {
    req <- request(sub("^http://", "https://", url))  # lien "next" fourni par l'API
  }
  req |>
    req_headers(`X-API-Key` = API_KEY) |>   # méthode d'authentification recommandée
    req_user_agent("R - import DATAtourisme") |>
    req_retry(max_tries = 4,
              is_transient = \(r) resp_status(r) %in% c(429, 500, 502, 503, 504)) |>
    req_error(body = \(r) tryCatch(
      paste(unlist(resp_body_json(r)), collapse = " | "),
      error = \(e) "(pas de détail renvoyé par l'API)"
    ))
}

# Télécharge les pages successives en suivant meta$next (méthode recommandée par l'API)
recuperer_pois <- function() {
  objets <- list()
  url    <- NULL
  page   <- 0
  repeat {
    page  <- page + 1
    resp  <- req_perform(construire_requete(url))
    corps <- resp_body_json(resp, simplifyVector = FALSE)
    
    if (page == 1) {
      message(sprintf("%s résultats au total, soit %s pages de %s.",
                      corps$meta$total, corps$meta$total_pages, TAILLE_PAGE))
      if (!is.null(corps$meta$total_pages) && corps$meta$total_pages > MAX_PAGES)
        message(sprintf("Seules les %s premières pages seront téléchargées (MAX_PAGES).",
                        MAX_PAGES))
    }
    
    objets <- c(objets, corps$objects)
    message(sprintf("Page %s : %s POI cumulés", page, length(objets)))
    
    url <- corps$meta[["next"]]
    if (is.null(url) || page >= MAX_PAGES) break
    Sys.sleep(PAUSE)
  }
  objets
}

# Valeurs d'un thésaurus (utile pour construire des filtres)
# Codes : Theme, Amenity, PeopleAudience, LocomotionMode, DifficultyLevel, Rating, PointOfInterestClass
thesaurus <- function(code) {
  request(paste0(BASE_URL, "/thesaurus/", code)) |>
    req_headers(`X-API-Key` = API_KEY) |>
    req_perform() |>
    resp_body_json(simplifyVector = FALSE)
}

# Transforme une valeur JSON (texte, tableau, objet multilingue) en une chaîne
aplatir <- function(x) {
  if (is.null(x) || length(x) == 0) return(NA_character_)
  if (!is.list(x)) return(paste(x, collapse = " | "))
  if (!is.null(names(x))) {                       # objet, ex. {"fr": [...], "en": [...]}
    cle <- if (LANGUE_AFFICHEE %in% names(x)) LANGUE_AFFICHEE else names(x)[1]
    return(aplatir(x[[cle]]))
  }
  if (all(vapply(x, \(e) !is.list(e), logical(1))))  # tableau de valeurs simples
    return(paste(unlist(x), collapse = " | "))
  aplatir(x[[1]])                                  # tableau d'objets : on prend le 1er
}

# Va chercher "a.b.c" dans un POI ; essaie plusieurs chemins si on en donne plusieurs
extraire <- function(poi, chemins) {
  for (chemin in chemins) {
    x <- poi
    for (nom in strsplit(chemin, ".", fixed = TRUE)[[1]]) {
      if (!is.list(x)) { x <- NULL; break }
      if (is.null(names(x)) && length(x) > 0) x <- x[[1]]   # tableau -> 1er élément
      if (!is.list(x)) { x <- NULL; break }
      x <- x[[nom]]
      if (is.null(x)) break
    }
    val <- aplatir(x)
    if (!is.na(val)) return(val)
  }
  NA_character_
}

# Liste de POI -> tableau (data.frame)
vers_tableau <- function(objets) {
  df <- map_dfr(objets, \(o) as_tibble(map(COLONNES, \(ch) extraire(o, ch))))
  df |> mutate(across(any_of(c("latitude", "longitude")), as.numeric))
}


# ---------------------------------------------------------------------
# 3. IMPORT DES DONNÉES
# ---------------------------------------------------------------------
FILTRE_FINAL <- construire_filtre_final()
message("Filtre envoyé à l'API : ", FILTRE_FINAL)

pois_brut <- recuperer_pois()   # liste brute (JSON converti en listes R)
df        <- vers_tableau(pois_brut)

print(df)

# 👉 À faire une fois : inspecter la structure brute d'un POI pour vérifier
#    les chemins de COLONNES, ou pour repérer d'autres champs à extraire.
# str(pois_brut[[1]], max.level = 4)


# ---------------------------------------------------------------------
# 4. VISUALISATION  (✏️ choisir selon le type de données)
# ---------------------------------------------------------------------
#   "carte"       : carte interactive des POI (lieux, événements ayant une position)
#   "barres"      : nombre de POI par modalité d'une variable (commune, type...)
#   "chronologie" : nombre d'événements par mois (endpoint "entertainmentAndEvent",
#                   avec FIELDS et la colonne date_debut activés plus haut)
#   "aucune"      : pas de graphique
VISU <- "carte"

# Pour "barres" : variable à compter (nom d'une colonne de COLONNES) et nombre de modalités
VARIABLE_BARRES <- "commune"
TOP_N           <- 15

if (VISU == "carte") {
  
  df_geo <- df |> filter(!is.na(latitude), !is.na(longitude))
  carte <- leaflet(df_geo) |>
    addTiles() |>
    addCircleMarkers(
      lng = ~longitude, lat = ~latitude, radius = 4,
      popup = ~paste0("<b>", htmltools::htmlEscape(nom), "</b><br>",
                      htmltools::htmlEscape(commune)),
      clusterOptions = markerClusterOptions()
    )
  print(carte)
  
} else if (VISU == "barres") {
  
  g <- df |>
    filter(!is.na(.data[[VARIABLE_BARRES]])) |>
    count(across(all_of(VARIABLE_BARRES)), sort = TRUE) |>
    slice_head(n = TOP_N) |>
    ggplot(aes(x = reorder(.data[[VARIABLE_BARRES]], n), y = n)) +
    geom_col(fill = "steelblue") +
    coord_flip() +
    labs(x = NULL, y = "Nombre de POI",
         title = paste("POI par", VARIABLE_BARRES)) +
    theme_minimal()
  print(g)
  
} else if (VISU == "chronologie") {
  
  if (!"date_debut" %in% names(df))
    stop("Activez la colonne date_debut dans COLONNES (et FIELDS avec takesPlaceAt).")
  g <- df |>
    mutate(mois = as.Date(paste0(substr(date_debut, 1, 7), "-01"))) |>
    filter(!is.na(mois)) |>
    count(mois) |>
    ggplot(aes(x = mois, y = n)) +
    geom_col(fill = "steelblue") +
    labs(x = NULL, y = "Nombre d'événements",
         title = "Événements par mois de début") +
    theme_minimal()
  print(g)
  
}


# ---------------------------------------------------------------------
# 5. EXPORT (optionnel)  ✏️
# ---------------------------------------------------------------------
EXPORT_CSV <- NULL   # ex. "pois_datatourisme.csv"
if (!is.null(EXPORT_CSV))
  write.csv(df, EXPORT_CSV, row.names = FALSE, fileEncoding = "UTF-8")