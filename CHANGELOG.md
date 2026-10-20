# Changelog — pellet_tracker

Suivi des évolutions de l'intégration. Chaque entrée contient la synthèse
des changements effectués. Format inspiré de Keep a Changelog (version +
date), antichronologique.

## [0.2.0] — 2026-10-20

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
