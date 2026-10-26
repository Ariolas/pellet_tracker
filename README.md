# Pellet Tracker — intégration Home Assistant

Suivi de la consommation de granulés d'un poêle à partir d'un capteur de
niveau de remplissage. Le capteur peut être un télémètre (distance entre
le capteur et la surface des granulés) ou n'importe quel capteur linéaire :
l'intégration détecte les remplissages, **compte les sacs constatés**,
estime l'autonomie et apprend la valeur « niveau gagné par sac »
spécifique de votre installation.

> Ce document est la référence utilisateur complète : il est rendu par
> HACS dans Home Assistant (page du dépôt) et couvre l'installation, tous
> les champs de configuration avec leur mode de mesure, le fonctionnement
> et les services.

## Installation

### Copie manuelle

1. Copier le dossier de l'intégration dans `config/custom_components/pellet_tracker/`
   (le dossier doit contenir directement `manifest.json`, `__init__.py`, etc.).
2. Redémarrer Home Assistant.
3. Paramètres → Appareils et services → Ajouter une intégration → « Pellet Tracker ».

### Via HACS

Publié sur GitHub : https://github.com/Ariolas/pellet_tracker — l'ajouter comme
dépôt personnalisé de type intégration dans HACS avec cette URL (la structure
`hacs.json` avec `content_in_root` est déjà en place), puis installer et
redémarrer. La présente documentation est celle affichée par HACS.

---

## Champs de configuration — assistant initial

| Champ | Contraintes | Défaut | Rôle |
|---|---|---|---|
| Capteur de niveau | entité `sensor.*` existante | — | Le capteur suivi : distance (télémètre) ou niveau en %. Un seul tracker par capteur. |
| Appareils de notification | sélection multiple parmi les services `notify.*` de l'instance | vide | Appareils qui recevront les notifications (remplissages, tests). Vide = notifications désactivées. |
| Delta d'un sac | 0,1 à 100 (niveau brut) | 8,0 | Base de départ : différence de niveau brute apportée par un sac de 15 kg. Affinée ensuite par l'apprentissage. |
| Sacs initiaux | 0 à 500 | 0 | Sacs déjà consommés avant l'installation : point de départ du compteur « Sacs consommés ». |
| Niveau bas (cuve vide) | −10000 à 100000 (mesure brute) | 0 | Valeur du capteur quand la cuve est VIDE. |
| Niveau haut (cuve pleine) | −10000 à 100000 (mesure brute) | 100 | Valeur du capteur quand la cuve est PLEINE. |

Validation : « cuve vide » et « cuve pleine » doivent être **différentes**
(erreur sinon) ; un même capteur ne peut être suivi que par une seule
configuration.

## Champs de configuration — options

Toutes modifiables après installation (Paramètres → Appareils et services
→ Pellet Tracker → Configurer) ; l'entrée se recharge automatiquement.
Les valeurs saisies sont visibles sur l'appareil « Suivi granulés » dans
le bloc **Configuration** (lecture seule).

### Calibration

| Champ | Contraintes | Défaut | Rôle |
|---|---|---|---|
| Delta d'un sac (base) | 0,1 à 100 (niveau brut) | 8,0 | Même champ que l'assistant. C'est la **base de départ** : utilisée tant qu'aucun remplissage n'a été confirmé, et la valeur de retour du bouton « Réinitialiser l'apprentissage » et du service `reset_learning`. Ne remplace jamais le delta appris. |
| Niveau bas (cuve vide) | −10000 à 100000 | 0 | Valeur capteur cuve vide. Pour un télémètre : la distance la plus **grande**. |
| Niveau haut (cuve pleine) | −10000 à 100000 | 100 | Valeur capteur cuve pleine. Pour un télémètre : la distance la plus **courte**. |

### Détection des remplissages

| Champ | Contraintes | Défaut | Rôle |
|---|---|---|---|
| Seuil de bruit (%) | 0,2 à 20 | 1,5 | Variations en dessous de ce seuil (en % de la cuve) sont ignorées : fluctuation du capteur, tassement des granulés. Trop bas = fausses détections ; trop haut = petits remplissages ratés. |
| Durée de stabilisation (s) | 30 à 3600 | 180 | Silence requis (aucune nouvelle variation) après une hausse avant de confirmer le remplissage. Doit couvrir le temps que la surface des granulés se stabilise après versement. |
| Fenêtre de hausse rapide (s) | 10 à 3600 | 120 | La hausse doit se produire en moins de ce délai pour être qualifiée de remplissage. Une hausse plus lente est considérée comme une dérive (tassement) et ignorée. |

### Apprentissage (affinage du delta d'un sac)

| Champ | Contraintes | Défaut | Rôle |
|---|---|---|---|
| Coefficient EMA (alpha) | 0,05 à 1,0 | 0,30 | Vitesse d'affinage du delta appris à chaque confirmation : nouveau_delta = alpha × delta_constaté + (1 − alpha) × delta_actuel. Petit = lent et stable ; grand = rapide et nerveux. 1,0 = remplacement immédiat. |
| Fenêtre écart-type (deltas) | 2 à 50 | 10 | Nombre de derniers deltas confirmés servant au calcul de la tolérance glissante. |
| Tolérance minimale (%) | 0,1 à 10 | 1,5 | Plancher de la tolérance : un remplissage est « ≈ 1 sac » si son delta est à moins de max(plancher, 2 × écart-type glissant) du delta appris. Détermine la frontière entre comptage automatique et notification à boutons. |

### Notifications

| Champ | Contraintes | Défaut | Rôle |
|---|---|---|---|
| Appareils de notification | sélection multiple parmi les `notify.*` existants | valeur courante | Liste actualisée à chaque ouverture : seuls les services réellement enregistrés dans l'instance sont proposés. Vide = notifications désactivées. |

---

## Protocoles de mesure terrain

### Niveaux bas / haut (conversion des mesures)

1. Cuve vide : noter la valeur **brute** du capteur → « Niveau bas (cuve vide) ».
2. Cuve pleine : noter la valeur brute → « Niveau haut (cuve pleine) ».
3. L'ordre des deux valeurs est libre : le télémètre donnera
   vide > pleine (la distance augmente quand la cuve se vide), un
   peson l'inverse. Seule l'égalité est interdite.
4. Particularité : avec les défauts 0 / 100, un capteur qui expose déjà
   un niveau en % n'est pas transformé (conversion identité).

### Delta d'un sac

1. Noter le niveau brut affiché par le capteur.
2. Verser **exactement un sac** de 15 kg.
3. Noter le nouveau niveau.
4. Saisir la **différence** (valeur absolue) dans « Delta d'un sac ».
   Exemple : 58 → 50 en distance ⇒ delta = 8.

L'apprentissage affine ensuite cette base à chaque remplissage confirmé
(sac complet ou comptage automatique) — surveillez-la avec l'entité
« Delta d'un sac (appris) » (bloc Diagnostic).

### Réglages de détection (symptôme → remède)

- Fausses détections (notification pour du bruit) → augmenter le seuil
  de bruit, ou la fenêtre écart-type si les deltas confirmés sont dispersés.
- Remplissage non détecté (notification jamais reçue) → vérifier que le
  delta constaté dépasse le seuil de bruit ; baisser le seuil.
- Remplissage non confirmé (notification en retard ou jamais) → la durée
  de stabilisation doit être supérieure à l'intervalle d'émission du
  capteur ; vérifier aussi le bouton « Tester la notification ».

---

## Fonctionnement

- Une hausse rapide du % (> seuil de bruit, sur ≤ fenêtre de hausse) suivie
  d'une stabilisation (silence de la durée configurée) est un remplissage.
- **Sacs consommés = total compté par remplissages constatés.** La baisse
  du niveau n'est qu'un indicatif, elle n'incrémente jamais le compteur.
- Delta ≈ 1 sac (confiance haute, tolérance adaptative) → **comptage
  automatique** : sac compté et appris immédiatement, notification
  « Acquitter » (comptage validé) / « Correction (−1 sac) » (retire le
  sac compté ; l'apprentissage déjà intégré n'est pas réversible).
- Delta ≠ 1 sac ou doute → notification à trois boutons :
  « Sac complet » (compte le sac ET apprend sur ce delta),
  « Sac partiel » (ne compte rien, n'apprend rien),
  « Fin de sac » (compte le sac SANS apprentissage).
- Compteurs, apprentissage et historique (200 événements max) sont
  persistés dans `.storage` et survivent aux redémarrages.

## Entités créées (par appareil « Suivi granulés »)

- `sensor` Niveau de remplissage (%), Sacs consommés (entier), Sacs restants estimés (valeur exacte), Delta d un sac appris (niveau appris ; attributs : tolérance, deltas confirmés, base), Dernier remplissage confirmé (hausse constatée du dernier sac confirmé ; attributs : dates, réponse)
- `sensor` Bloc Diagnostic de l appareil (calibration, lecture seule) : Niveau bas (cuve vide), Niveau haut (cuve pleine), Delta d un sac (base) - regroupées avec Delta d un sac (appris)
- `button` Tester la notification (envoie un test aux appareils sélectionnés)
- `button` Réinitialiser l'apprentissage (efface les deltas confirmés, repart du delta de base — à réserver à un changement de capteur ou une recalibration)
- `event` Dernier remplissage VALIDÉ — se déclenche uniquement sur Acquitter / Sac complet / Fin de sac (attributs : delta, décision, réponse, niveaux, dates de remplissage et de validation)

## Services

| Service | Paramètres | Rôle |
|---|---|---|
| `pellet_tracker.add_bag` | `nombre` (1 à 50, défaut 1) | Compte manuellement des sacs (remplissage non détecté). |
| `pellet_tracker.reset_counter` | — | Remet à zéro les compteurs de sacs et l'indicatif « % consommé ». |
| `pellet_tracker.reset_learning` | `delta_un_sac` optionnel (0,1 à 100, **niveau brut**) | Efface les deltas confirmés et repart du delta fourni — ou de la base des options si vide. |

## Tests

Les modules `detector.py` (machine à états) et la conversion capteur → %
sont volontairement sans dépendance Home Assistant :

```bash
pytest tests/                  # ou :
python tests/test_detector.py        # exécution autonome sans pytest
python tests/test_conversion.py
```
