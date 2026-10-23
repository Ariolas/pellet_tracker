# Changelog — pellet_tracker

Suivi des évolutions de l'intégration. Chaque entrée contient la synthèse
des changements effectués. Format inspiré de Keep a Changelog (version +
date), antichronologique.

## [0.9.0] — 2026-10-20

### Changement de modèle : sacs consommés = sacs COMPTÉS, plus estimés

- **Sémantique** — « Sacs consommés » n'est plus calculé par la baisse de
  niveau (estimation) : il est incrémenté uniquement quand un remplissage
  est constaté. La baisse de niveau reste suivie à titre indicatif
  (`niveau_consome_pct` persisté) mais n'incrémente jamais le compteur.
- **`coordinator.py`** — `sacs_consommes` = auto + confirmés + manuels.
- **`sensor.py`** — `state_class` de « Sacs consommés » passe de
  `TOTAL_INCREASING` à `TOTAL` : une correction peut faire baisser le
  total.

### Notifications à boutons remaniées

- **AUTO (delta ≈ 1 sac, confiance haute = fenêtre de tolérance)** :
  le sac est compté et appris immédiatement, notification affirmant le
  comptage avec deux boutons :
  - **Acquitter** : comptage validé, rien à faire ;
  - **Correction (-1 sac)** : retire le sac compté. Note : l'apprentissage
    EMA, déjà intégré, n'est pas réversible — il est conservé.
- **PARTIEL (delta ≠ 1 sac ou doute)** : rien n'est compté d'office,
  notification avec trois boutons :
  - **Sac complet** : compte le sac ET apprend sur ce delta ;
  - **Sac partiel** : ne compte rien, n'apprend rien ;
  - **Fin de sac** : compte le sac SANS apprentissage (le delta ne
    représente pas un sac entier : fin de sac entamé).
- **`const.py`** — Nouvelles actions `pellet_acquitter`,
  `pellet_correction`, `pellet_sac_complet`, `pellet_sac_partiel`,
  `pellet_fin_de_sac` (remplacent `pellet_confirm_1sac` /
  `pellet_annule`).
- **Traçabilité** — La réponse utilisateur est enregistrée sur
  l'événement (`reponse` : acquitte / correction / sac_complet /
  sac_partiel / fin_de_sac) en plus de `confirme`.
- Les notifications en attente (`attente_confirmation`) mémorisent leur
  type (`auto` / `partiel`) et le nombre de sacs déjà comptés ; une
  réponse périmée ou d'un ancien format est ignorée proprement.

### Notes de version

- **Migration** : le compteur « Sacs consommés » repartira de zéro si
  l'ancien comptage était basé sur la baisse de niveau — utiliser
  `sacs_initiaux` ou le service `add_bag` pour recaler, puis
  `reset_counter` au besoin.
- La détection et l'apprentissage ne changent pas : 27/27 tests verts.
- À valider dans l'instance : boutons des notifications (les trois
  réponses d'une même notification mobile sont exclusives — le premier
  appui l'emporte).

## [0.8.2] — 2026-10-20

### Correction bloquante (remontée par l'instance HA)

- **Abonnement des entités au coordinateur** — Appui sur le bouton
  « Réinitialiser l'apprentissage » : `Attribute hass is None for
  <entity unknown.unknown=unknown>`. Cause : chaque entité s'abonnait
  au coordinateur dans son `__init__` (avant d'être ajoutée à HA) et ne
  se désabonnait jamais ; une entité finalement non ajoutée laissait un
  callback mort, et le premier `_notify_entities` (déclenché par le
  bouton) appelait `async_write_ha_state` sur cette entité fantôme —
  sans `hass` ni `entity_id`. Un seul callback mort bloquait toute la
  boucle de mise à jour.
- **Correctif** — `coordinator.on_update` retourne maintenant une
  fonction de désabonnement ; les entités (`sensor.py`,
  `binary_sensor.py`, `event.py`) s'abonnent dans
  `async_added_to_hass` et se désabonnent dans
  `async_will_remove_from_hass`. Une entité jamais ajoutée ne s'abonne
  plus du tout : plus de fantôme possible, quelle que soit la cause.
- **Effet secondaire positif** — L'abonnement calcule immédiatement la
  valeur : les entités affichent leurs données dès l'ajout, sans
  attendre le premier changement d'état du capteur.

### Notes de version

- 27/27 tests verts (aucune logique de détection touchée).
- À déployer avec redémarrage complet de HA.

## [0.8.1] — 2026-10-20

### Correction bloquante (remontée par l'instance HA)

- **`sensor.py`, `button.py`** — `AttributeError: EntityCategory has no
  attribute 'CONFIGURATION'` au chargement de la plateforme `sensor` :
  l'attribut correct de l'enum HA est **`EntityCategory.CONFIG`**
  (les valeurs sont `CONFIG`, `DIAGNOSTIC`, `SYSTEM`). La plateforme
  `sensor` ne se chargeait pas du tout (boutons et configuration
  concernés). `DIAGNOSTIC`, utilisé ailleurs, était correct.
  L'erreur ne pouvait pas être détectée hors instance : la compilation
  ne vérifie pas les attributs d'un enum externe.

### Notes de version

- 27/27 tests verts (logique inchangée).
- Leçon de process : les attributs d'API HA (enums, constantes) doivent
  être vérifiés dans le code du core avant usage, comme cela a été fait
  pour les sélecteurs — c'est désormais implicite via le README de
  développement (AGENTS.md, vérifications).

## [0.8.0] — 2026-10-20

### Fonctionnalité : bouton « Réinitialiser l'apprentissage »

- **`button.py`** — Nouvelle entité bouton dans le bloc Configuration de
  l'appareil : exécute `reset_learning` sans passer par les outils de
  développement. Icône d'alerte (`mdi:restart-alert`). Effet : efface
  les deltas confirmés (la tolérance adaptative repart de zéro) et
  réinitialise le delta appris au delta de base.
- **`coordinator.py`** — `async_reset_learning` envoie désormais une
  notification de retour (si des cibles sont configurées) : elle
  confirme l'action et rappele la base de repart et l'effacement des
  deltas — l'avertissement d'usage accompagne l'action, puisque les
  entités bouton ne peuvent pas déclencher de dialogue de confirmation
  dans l'interface HA.
- **`translations/`** — La description des options porte l'avertissement :
  le bouton est à réserver à un changement de capteur ou à une
  recalibration des niveaux bas/haut (fr/en).
- **`README.md`** — Entité documentée avec son avertissement d'usage.

### Notes de version

- Décision de design (inchangée) : le cœur (machine à états, seuil de
  bruit, tolérance) reste en % interne ; seules la saisie et l'affichage
  sont en niveau brut (cf. 0.7.0).
- Compilation OK, 27/27 tests existants verts ; entité et notification
  à valider dans l'instance.

## [0.7.0] — 2026-10-20

### Fonctionnalité : « Delta d'un sac » exprimé en niveau (mesure brute)

- **Sémantique** — Le delta d'un sac n'est plus un pourcentage mais une
  **différence de niveau brute** (l'unité du capteur : cm pour un
  télémètre) : plus simple à mesurer — niveau avant remplissage, niveau
  après, la soustraction donne la valeur à saisir. Le champ de
  configuration (assistant + options), le service `reset_learning` et
  l'entité « Delta d'un sac (appris) » sont tous en niveau brut.
- **`detector.py`** — `ConvertisseurNiveau` gère la conversion aux
  frontières : `delta_niveau_vers_pct` (saisie → interne) et
  `delta_pct_vers_niveau` (interne → affichage). La machine à états, le
  seuil de bruit et la tolérance adaptative restent en % interne —
  aucun test du détecteur n'a changé, 5 nouveaux tests de conversion.
- **`coordinator.py`** — Le delta saisi est converti en % interne au
  chargement ; les notifications affichent le delta en niveau brut
  (« +12,5 de niveau ») ; `reset_learning` accepte un paramètre en
  niveau brut (converti). La valeur apprise persistée reste en % interne
  (réinterprétation inutile des données existantes).
- **`sensor.py`** — Nouvelles entités **dans le bloc « Configuration »
  de l'appareil** (catégorie HA `CONFIGURATION`, lecture seule — la
  saisie se fait dans les options) : « Niveau bas (cuve vide) »,
  « Niveau haut (cuve pleine) », « Delta d'un sac (base) ».
  « Delta d'un sac (appris) » (diagnostique) affiche désormais la
  valeur apprise en niveau brut, avec attributs `tolerance_niveau`,
  `deltas_confirmes`, `delta_base`.
- **`event.py`** — Attribut `delta_niveau` ajouté au dernier remplissage.
- **`services.yaml`, `translations/`** — Descriptions et libellés mis au
  pluriel des niveaux bruts (fr/en).

### Notes de version

- **Migration requise** : une installation existante doit resaisir son
  delta d'un sac en niveau brut dans les options (la valeur `8.0`
  stockée était en %). Avec des bornes (vide/pleine) d'étendue 100, la
  valeur numérique reste identique (coïncidence du changement d'unité).
- Vérifié hors HA : compilation, 15/15 tests détecteur + 12/12 tests
  conversion. Flows et entités à valider dans l'instance.

## [0.6.0] — 2026-10-20

### Fonctionnalité : sélection des appareils de notification

- **`config_flow.py`** — La cible de notification n'est plus un champ
  texte libre : c'est une **liste déroulante à sélection multiple**,
  alimentée dynamiquement par les services `notify.*` réellement
  enregistrés dans l'instance (assistant initial et options). Seules
  des cibles valides peuvent être choisies ; une sélection vide
  désactive simplement les notifications. Les cibles historiques
  disparues sont élaguées à l'ouverture des options (un service
  supprimé ne peut de toute façon plus être appelé).
- **`coordinator.py`** — `notify_targets` devient une liste : toutes les
  notifications (remplissage auto, partiel avec boutons, confirmation)
  partent vers **tous** les appareils sélectionnés. Normalisation de la
  valeur historique (chaîne unique → liste). Nouvelle méthode
  `async_test_notification()`.
- **`button.py`** — Nouvelle entité « Tester la notification »
  (plateforme `button` ajoutée à `PLATFORMS`) : un clic envoie une
  notification de test sur les appareils sélectionnés. Idiome HA
  standard — les fenêtres de configuration ne peuvent pas contenir de
  boutons cliquables. La description des options y renvoie.
- **`translations/`** — Libellés « Appareils de notification
  (sélection multiple) » + description des options (fr/en).

### Notes de version

- Vérifié avant implémentation : HA core n'expose pas de sélecteur
  « service notification » (`ServiceSelector` inexistant dans
  `homeassistant/helpers/selector.py`, contrairement à
  `SelectSelector(multiple=True)` — pattern officiel du core, 46 usages).
- Compatibilité : une configuration existante (chaîne unique) est
  normalisée en liste sans intervention ; le champ devient `Optional`
  (défaut vide) au lieu d'un texte pré-rempli factice
  (`notify.mobile_app_mon_tel`).
- Compilation OK, 22 tests existants verts ; flows et bouton non
  testables sans instance HA.
## [0.5.0] — 2026-10-20

### Fonctionnalité : « Delta d'un sac » modifiable dans les options

- **`config_flow.py`** — Le champ « Delta d'un sac » (base de départ :
  % gagné par sac de 15 kg, affiné ensuite par l'apprentissage EMA)
  existait uniquement dans l'assistant initial. Il est maintenant
  présent dans les options (modifiable sans réinstallation), en tête de
  liste. Validation identique (0,1 à 100).
- **`const.py`** — Clé `CONF_DELTA_UN_SAC` : la chaîne `"delta_un_sac"`
  n'est plus dupliquée en dur dans `config_flow.py` et `coordinator.py`.
- **`coordinator.py`** — Nouvelle propriété `delta_initial` (lecture
  options → data → défaut) ; le coordinateur et le service
  `reset_learning` s'y raccordent : la RAZ de l'apprentissage repart de
  la base actuelle, y compris si elle a été modifiée dans les options.
- **`sensor.py`** — L'entité « Delta d'un sac (appris) » passe en
  catégorie `DIAGNOSTIC` : lecture seule assumée dans l'interface
  (icône sous « Diagnostic », pas de personnalisation de la valeur).
  Son attribut `delta_initial` reflète la base effective (options
  incluses).
- **`translations/`** — Libellé fr/en du champ dans les options.

### Notes de version

- Sémantique inchangée : la base saisie ne remplace jamais la valeur
  apprise — elle sert de point de départ tant que l'apprentissage n'a
  pas produit de valeur confirmée (storage), et de référence pour le
  service `reset_learning`.
- Compilation et 22 tests existants verts ; logique machine à états non
  concernée.

## [0.4.0] — 2026-10-20

### Fonctionnalité : entité « Delta d'un sac (appris) »

- **`sensor.py`** — Nouvelle entité « Delta d'un sac (appris) » exposant
  la calibration EMA apprise, pour suivre l'apprentissage en direct et
  détecter une dérive sans ouvrir le `.storage`. Attributs de diagnostic :
  `tolerance_pct` (tolérance adaptative courante), `deltas_confirmes`
  (nombre de deltas dans la fenêtre glissante), `delta_initial`
  (calibration saisie à l'installation). Rattachée au même appareil,
  même mécanique unique_id/DeviceInfo.

### Corrections

- **`binary_sensor.py`** — Device class du « Remplissage en cours » :
  `OCCUPANCY` (présence d'une personne, sémantique trompeuse) remplacée
  par `UPDATE`, plus proche du sens « mise à jour de la cuve en cours ».
  Icône et libellés d'état HA adaptés en conséquence.
- **`manifest.json`** — Suppression des clés `documentation` et
  `issue_tracker` (URLs placeholders mortes) : les boutons « Documentation »
  et « Signaler un problème » disparaissent de la page de l'intégration au
  lieu d'ouvrir une erreur de navigateur. À rétablir avec de vraies URLs
  le jour où le projet est hébergé.

### Notes de version

- Entité purement additive (lecture seule) : aucun impact sur le stockage
  ou la détection. Compilation et 22 tests existants verts ; rien à
  tester côté machine à états (non concernée).

## [0.3.0] — 2026-10-20

### Fonctionnalité : support des capteurs de distance (télémètre)

Le capteur de niveau peut être un télémètre : il renvoie la distance entre
le capteur et la surface des granulés, donc **sa valeur augmente quand la
cuve se vide** — sens inverse d'un niveau classique. Jusqu'ici, toute la
logique supposait « valeur qui monte = remplissage » : pour un télémètre,
la consommation aurait été comptée comme un remplissage.

- **`detector.py`** — Nouvelle classe pure `ConvertisseurNiveau` :
  convertit la mesure brute en % de remplissage à partir des deux
  valeurs de référence (cuve vide / cuve pleine). Formule indépendante
  de l'ordre des bornes (fonctionne aussi pour un capteur dont la valeur
  monte quand la cuve se remplit, ex. peson), % borné à [0, 100],
  arrondi à 2 décimales, garde-fou si les deux valeurs sont égales.
- **`coordinator.py`** — La conversion est appliquée à chaque mesure
  (ancienne et nouvelle) AVANT tout traitement : suivi de consommation,
  machine à états, amorçage au démarrage. Le reste de l'intégration ne
  voit que du %.
- **`config_flow.py`** — Deux nouveaux champs dans la fenêtre de
  paramétrage : « valeur du capteur cuve vide » et « valeur du capteur
  cuve pleine » (assistant initial + options, modifiables sans
  réinstallation). Validation : les deux valeurs doivent différer.
- **`const.py`** — Clés `CONF_VALEUR_VIDE` / `CONF_VALEUR_PLEINE` et
  défauts `0 / 100` : pour un capteur qui expose déjà un niveau 0–100 %,
  la conversion est l'identité (comportement inchangé des installations
  existantes).
- **`translations/`** — Libellés fr/en des deux champs + message d'erreur.
- **`tests/test_conversion.py`** — 7 nouveaux tests : télémètre
  (distance/2 = mi-hauteur), bornage hors plage, identité capteur %,
  ordre inversé (poids), garde-fou valeurs égales, scénario bout en bout
  consommation puis remplissage AUTO, capteur silencieux.

### Notes de version

- Vérifié hors HA : compilation, 15/15 tests détecteur + 7/7 tests
  conversion.
- Non vérifié : chargement réel dans une instance Home Assistant. Pour un
  télémètre existant, saisir les deux distances aux extrêmes dans les
  options, sinon la conversion reste identité (0/100) et le comportement
  est celui de la 0.2.0.


### Corrections bloquantes

- **`__init__.py`** — Remplacement de `async_track_event` (fonction
  inexistante dans `homeassistant.helpers.event`) par
  `hass.bus.async_listen(EVENT_MOBILE_APP_ACTION, ...)`. L'import précédent
  levait une `ImportError` qui empêchait tout chargement de l'intégration.
- **Cycle de vie des services** — Les services du domaine
  (`add_bag`, `reset_counter`, `reset_learning`) sont maintenant retirés
  lorsque la dernière config entry est déchargée ; une
  `ServiceValidationError` explicite est levée si un service est appelé
  sans entry active (auparavant : `IndexError` silencieuse, services
  fantômes après suppression).

### Corrections majeures

- **`coordinator.py`** — Le delta appris (`delta_un_sac`) est désormais
  synchronisé dans les données persistées à chaque confirmation
  (`_persister_delta_appris`). Auparavant la valeur restait `None` dans le
  `.storage` et tout l'apprentissage EMA était perdu à chaque redémarrage.
- **`coordinator.py`** — `attente_confirmation` mémorise l'index de
  l'événement concerné : la réponse Oui/Non d'une notification marque le bon
  événement même si d'autres remplissages sont historisés entre-temps
  (auparavant : `evenements[-1]`, fragile).
- **`coordinator.py`** — Nouveau compteur `sacs_confirmes` distinct des
  `sacs_manuels` (service `add_bag`), pour distinguer confirmations mobiles
  et saisies manuelles.
- **`coordinator.py`** — Nettoyage des callbacks d'entités au déchargement
  (`async_unload`), plus de références mortes.
- **`storage.py`** — Valeur par défaut `sacs_confirmes: 0` ajoutée à l'état
  initial.
- **`translations/`** — Fichiers `fr.json` / `en.json` déplacés de
  `translations/translations/` vers `translations/` : Home Assistant
  n'aurait trouvé aucun libellé (traductions complètement ignorées).

### Fonctionnalités

- **Entités** (`sensor.py`, `binary_sensor.py`, `event.py`) — Ajout d'un
  `unique_id` par entité (`{entry_id}_{clé}`) et d'un `DeviceInfo` commun :
  les entités sont désormais enregistrées dans l'entity registry
  (personnalisation, statistics long terme) et regroupées sous un appareil
  « Suivi granulés ».
- **Options** (`config_flow.py`) — Valeurs par défaut importées depuis
  `const.py` (fin des 1.5 / 180 / 120 dupliqués en dur). Nouvelles options
  configurables après installation : cible de notification (modifiable sans
  réinstaller), `alpha_ema`, `fenetre_std`, `tolerance_min_pct` — ces
  paramètres existaient dans `const.py` mais n'étaient jamais câblés.
  Libellés fr/en ajoutés pour ces champs.

### Tests et documentation

- **`tests/test_detector.py`** — 15 tests unitaires de la machine à états
  et de l'apprentissage (initialisation, remplissages AUTO/PARTIEL, hausse
  lente, stabilisation, confirmation par timer sans nouvelle mesure,
  EMA, tolérance adaptative, réinitialisation). Exécutables avec pytest ou
  en autonome (`python tests/test_detector.py`), sans Home Assistant.
- **`README.md`** — Documentation : installation dans `custom_components`,
  configuration, fonctionnement, entités, services, lancement des tests.
- **`AGENTS.md`** — Règles de travail du projet (structure, conventions,
  vérifications, processus d'évolution).
- **`const.py`, `detector.py`** — Ajout du newline final manquant.

### Notes de version

- Vérifié hors HA : compilation des 10 modules, 15/15 tests, JSON valides.
- Non vérifié : chargement réel dans une instance Home Assistant (absente
  de l'environnement de travail). À valider au premier démarrage.

## [0.1.0] — 2026-10-20

### Import initial

Intégration `pellet_tracker` v0.1.0 (état d'origine) :

- Machine à états de détection de remplissage (`detector.py`) :
  VEILLE → HAUSSE → confirmation après stabilisation, apprentissage
  adaptatif EMA + tolérance glissante, conçue sans dépendance HA.
- Coordonnateur HA (`coordinator.py`) : écoute du capteur de niveau, timer
  de confirmation découplé des mesures, notifications mobiles avec boutons
  Oui/Non, suivi du % consommé cumulé.
- Persistance `.storage` (`storage.py`) : compteurs, apprentissage,
  historique borné à 200 événements.
- Config flow + options (`config_flow.py`), traductions fr/en.
- Entités : niveau %, sacs consommés, sacs restants (sensor), remplissage
  en cours (binary_sensor), dernier remplissage (event).
- Services : `add_bag`, `reset_counter`, `reset_learning` (`services.yaml`).
- Dépôt git local initialisé (branche `main`, commit `0e891f5`).
