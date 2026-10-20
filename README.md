# Pellet Tracker — intégration Home Assistant

Suivi de la consommation de granulés d'un poêle à partir d'un capteur de
niveau de remplissage (%, typiquement ESPHome avec filtre médian).
L'intégration détecte les remplissages, compte les sacs, estime l'autonomie
et apprend la valeur « % gagné par sac » spécifique de votre installation.

## Installation

1. Copier le dossier de l'intégration dans `config/custom_components/pellet_tracker/`
   (le dossier doit contenir directement `manifest.json`, `__init__.py`, etc.).
2. Redémarrer Home Assistant.
3. Paramètres → Appareils et services → Ajouter une intégration → « Pellet Tracker ».

## Configuration

L'assistant demande :

| Champ | Description | Défaut |
|---|---|---|
| Capteur de niveau | `entity_id` du capteur % de remplissage | — |
| Service de notification | ex. `notify.mobile_app_pixel` | `notify.mobile_app_mon_tel` |
| Delta d'un sac | % gagné pour 1 sac de 15 kg (calibration terrain) | 8.0 |
| Sacs initiaux | estimation de sacs déjà consommés au premier lancement | 0 |

Options (Configurer → Pellet Tracker) : seuil de bruit, durée de
stabilisation, fenêtre de hausse rapide, notification, coefficient EMA,
fenêtre d'écart-type, tolérance minimale.

## Fonctionnement

- Une hausse rapide (> seuil de bruit, sur ≤ fenêtre de hausse) suivie
  d'une stabilisation (silence de la durée configurée) est un remplissage.
- Delta ≈ 1 sac (tolérance adaptative) → **AUTO** : compté, apprentissage.
- Delta partiel → notification mobile avec boutons « Oui, 1 sac » / « Non ».
- Les baisses du niveau (hors remplissage) alimentent le % consommé cumulé.
- Compteurs, apprentissage et historique (200 événements max) sont
  persistés dans `.storage` et survivent aux redémarrages.

## Entités créées (par appareil « Suivi granulés »)

- `sensor` Niveau de remplissage (%), Sacs consommés, Sacs restants estimés
- `binary_sensor` Remplissage en cours
- `event` Dernier remplissage (delta, décision, niveaux)

## Services

| Service | Description |
|---|---|
| `pellet_tracker.add_bag` | Compte manuellement des sacs (nombre, 1–50) |
| `pellet_tracker.reset_counter` | Remet à zéro compteurs et % consommé |
| `pellet_tracker.reset_learning` | RAZ de l'apprentissage (optionnel : nouveau delta d'un sac) |

## Tests

Le module `detector.py` est volontairement sans dépendance Home Assistant :

```bash
pytest tests/                  # ou :
python tests/test_detector.py  # exécution autonome sans pytest
```
