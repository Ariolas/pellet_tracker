"""Constantes de l'intégration pellet_tracker."""
# Domaine de l'intégration
DOMAIN = "pellet_tracker"
PLATFORMS = ["sensor", "binary_sensor", "event"]

# --- Clés de configuration (config entry) ---
CONF_SENSOR_NIVEAU = "sensor_niveau"        # entity_id du capteur de niveau (%)
CONF_NOTIFY = "notify_service"              # ex. notify.mobile_app_pixel
CONF_SACS_INIT = "sacs_initiaux"            # sacs estimés au premier lancement
CONF_SEUIL_BRUIT = "seuil_bruit_pct"        # variation considérée comme du bruit
CONF_DUREE_STABILISATION = "duree_stabilisation_s"  # silence requis après la hausse
CONF_FENETRE_HAUSSE = "fenetre_hausse_s"     # durée max pour qualifier la hausse de "rapide"
CONF_TOLERANCE_MIN = "tolerance_min_pct"    # plancher de tolérance de détection
CONF_ALPHA_EMA = "alpha_ema"                 # coefficient de l'EMA
CONF_FENETRE_STD = "fenetre_std"            # nb de deltas confirmés pour l'écart-type

# --- Services ---
SERVICE_ADD_BAG = "add_bag"
SERVICE_RESET_COUNTER = "reset_counter"
SERVICE_RESET_LEARNING = "reset_learning"

# --- Notifications mobiles ---
EVENT_MOBILE_APP_ACTION = "mobile_app_notification_action"
ACTION_CONFIRM = "pellet_confirm_1sac"
ACTION_CANCEL = "pellet_annule"

# --- Valeurs par défaut (à ajuster au premier lancement) ---
DEFAULT_DELTA_UN_SAC = 8.0        # % gagné pour 1 sac de 15 kg (calibration terrain)
DEFAULT_SEUIL_BRUIT = 1.5         # % — filtrage median ESPHome + marge
DEFAULT_DUREE_STABILISATION = 180 # s sans variation > bruit → confirmation
DEFAULT_FENETRE_HAUSSE = 120      # s — la hausse doit se produire dans cette fenêtre
DEFAULT_TOLERANCE_MIN = 1.5       # % — plancher de tolérance
DEFAULT_ALPHA_EMA = 0.30          # lissage exponentiel
DEFAULT_FENETRE_STD = 10          # nb de derniers deltas pour l'écart-type glissant
DEFAULT_SACS_INIT = 0
DEFAULT_NOTIFY = "notify.mobile_app_mon_tel"
