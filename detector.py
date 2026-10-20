"""Machine à états de détection de remplissage + apprentissage adaptatif.

Ce module ne contient AUCUN import de Home Assistant : il est testable
unitairement (pytest) en manipulant directement des mesures et timestamps.

Principe :
  IDLE ──(hausse > bruit)──► HAUSSE ──(plus de variation pendant
  duree_stabilisation)──► evenement « remplissage » avec delta
  Un delta ≈ delta_un_sac (tolérance adaptative) → comptage automatique.
  Un delta partiel (> bruit, hors fenêtre) → décision "partiel" (notification).
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class Etat(Enum):
    """États de la machine à états."""
    VEILLE = auto()        # suivi passif du niveau
    HAUSSE = auto()        # hausse rapide détectée, on attend la stabilisation
    STABILISATION = auto() # plus de hausse, chrono de confirmation lancé


class Decision(str, Enum):
    """Décision prise pour un événement de remplissage."""
    AUTO = "auto"        # delta ≈ 1 sac → comptage automatique
    PARTIEL = "partiel"   # delta hors fenêtre → notification avec boutons
    BRUIT = "bruit"      # delta finalement trop faible → ignoré


@dataclass
class ResultatRemplissage:
    """Émis quand un remplissage est confirmé (fin de stabilisation)."""
    niveau_avant: float   # % au moment où la hausse a commencé
    niveau_apres: float   # % à la confirmation
    delta: float         # variation en %
    decision: Decision


@dataclass
class EvenementRemplissage(ResultatRemplissage):
    """Événement persisté : date + décision + niveaux."""
    timestamp: float = field(default_factory=time.time)
    confirme: Optional[bool] = None  # None=auto, True/False = réponse utilisateur


class DetecteurRemplissage:
    """Machine à états unique de détection de remplissage.

    Args:
        delta_un_sac: % gagné pour un sac (valeur calibrée, affinée ensuite).
        seuil_bruit_pct: variations ≤ seuil considérées comme du bruit.
        duree_stabilisation_s: silence requis (s) avant de confirmer.
        fenetre_hausse_s: la hausse doit se produire sur ≤ cette durée.
    """

    def __init__(
        self,
        delta_un_sac: float,
        seuil_bruit_pct: float = 1.5,
        duree_stabilisation_s: float = 180.0,
        fenetre_hausse_s: float = 120.0,
        apprentissage: Optional["ApprentissageAdaptatif"] = None,
    ) -> None:
        self.delta_un_sac = delta_un_sac
        self.seuil_bruit = seuil_bruit_pct
        self.duree_stabilisation = duree_stabilisation_s
        self.fenetre_hausse_s = fenetre_hausse_s
        self.apprentissage = apprentissage or ApprentissageAdaptatif(delta_un_sac)

        self._etat = Etat.VEILLE
        self._initialise = False                     # une première mesure a-t-elle été reçue ?
        self._niveau_avant: float = 0.0   # référence au début de la hausse
        self._dernier_niveau: float = 0.0  # dernier niveau vu
        self._t_debut_hausse: float = 0.0
        self._t_derniere_variation: float = 0.0

    # --- État courant (exposé au binary_sensor) ---
    @property
    def remplissage_en_cours(self) -> bool:
        return self._etat != Etat.VEILLE

    @property
    def etat(self) -> Etat:
        return self._etat

    @property
    def niveau_actuel(self) -> Optional[float]:
        """Dernier niveau valide vu (None avant la première mesure)."""
        return self._dernier_niveau if self._initialise else None

    @property
    def t_derniere_variation(self) -> float:
        """Horodatage de la dernière hausse (pour planifier le timer)."""
        return self._t_derniere_variation

    def confirmer_si_stable(self, timestamp: Optional[float] = None) -> Optional[ResultatRemplissage]:
        """Confirmation par timer : appelé même si le capteur n'émet plus.

        Le capteur ESPHome (heartbeat + median) peut cesser d'émettre après
        la stabilisation ; sans ce point d'entrée pour un timer externe,
        l'événement ne serait jamais confirmé.
        """
        if timestamp is None:
            timestamp = time.time()
        if self._etat != Etat.HAUSSE:
            return None
        if timestamp - self._t_derniere_variation >= self.duree_stabilisation:
            return self._confirmer(self._dernier_niveau, timestamp)
        return None

    # --- Classification d'un delta ---
    def classer_delta(self, delta: float) -> Decision:
        """Classe un delta confirmé grâce à la tolérance adaptative."""
        if delta <= self.seuil_bruit:
            return Decision.BRUIT
        tolerance = self.apprentissage.tolerance()
        if abs(delta - self.apprentissage.delta_un_sac) <= tolerance:
            return Decision.AUTO
        return Decision.PARTIEL

    # --- Alimentation de la machine ---
    def traiter_mesure(self, niveau_pct: float, timestamp: Optional[float] = None) -> Optional[ResultatRemplissage]:
        """Traite une nouvelle mesure du niveau (%).

        Retourne un ResultatRemplissage quand un remplissage est confirmé,
        sinon None. `timestamp` en epoch secondes (monotone côté appelant).
        """
        if timestamp is None:
            timestamp = time.time()
        niveau = float(niveau_pct)
        # Ignorer les valeurs invalides du capteur (indisponible, NaN)
        if niveau < 0 or niveau > 100 or math.isnan(niveau):
            return None

        # Première mesure : initialisation de la référence
        # (flag plutôt que `== 0.0` : un niveau réel de 0 % est valide)
        if not self._initialise:
            self._initialise = True
            self._dernier_niveau = niveau
            return None

        variation = niveau - self._dernier_niveau
        self._dernier_niveau = niveau

        if self._etat == Etat.VEILLE:
            if variation > self.seuil_bruit:
                # Début d'une hausse rapide potentielle
                self._etat = Etat.HAUSSE
                self._niveau_avant = niveau - variation
                self._t_debut_hausse = timestamp
                self._t_derniere_variation = timestamp
            return None

        if self._etat == Etat.HAUSSE:
            if variation > 0:
                # La hausse continue : on note et on repousse le chrono
                self._t_derniere_variation = timestamp
                if timestamp - self._t_debut_hausse > self.fenetre_hausse_s:
                    # Hausse trop lente : dérive lente tolérée, retour au repos
                    self._etat = Etat.VEILLE
                return None
            if timestamp - self._t_derniere_variation >= self.duree_stabilisation:
                # Hausse arrêtée et stable depuis assez longtemps → confirmation
                return self._confirmer(niveau, timestamp)
            return None

        return None  # (état STABILISATION non utilisé séparément, réservé)

    def _confirmer(self, niveau_apres: float, timestamp: float) -> ResultatRemplissage:
        """Confirme un remplissage et réinitialise la machine."""
        delta = niveau_apres - self._niveau_avant
        decision = self.classer_delta(delta)
        self._etat = Etat.VEILLE
        resultat = ResultatRemplissage(
            niveau_avant=self._niveau_avant,
            niveau_apres=niveau_apres,
            delta=round(delta, 2),
            decision=decision,
        )
        return resultat


class ApprentissageAdaptatif:
    """Apprentissage de `delta_un_sac` par EMA + tolérance adaptative.

    - delta_un_sac affiné par moyenne mobile exponentielle (EMA, alpha).
    - tolérance = max(plancher, k * écart-type glissant des N derniers deltas
      confirmés) → fenêtre adaptative autour de delta_un_sac.
    """

    def __init__(
        self,
        delta_un_sac: float,
        alpha: float = 0.30,
        fenetre_std: int = 10,
        tolerance_min: float = 1.5,
        facteur_std: float = 2.0,
    ) -> None:
        self.delta_un_sac = float(delta_un_sac)
        self.alpha = float(alpha)
        self.fenetre_std = int(fenetre_std)
        self.tolerance_min = float(tolerance_min)
        self.facteur_std = float(facteur_std)
        self.deltas_confirmes: list[float] = []

    def confirmer(self, delta: float) -> float:
        """Enregistre un delta confirmé (sac réel) et affine l'EMA.

        Retourne la nouvelle valeur de delta_un_sac.
        """
        delta = float(delta)
        # EMA : la valeur apprise glisse lentement vers le delta observé
        self.delta_un_sac = round(
            self.alpha * delta + (1 - self.alpha) * self.delta_un_sac, 3
        )
        self.deltas_confirmes.append(delta)
        if len(self.deltas_confirmes) > self.fenetre_std:
            self.deltas_confirmes.pop(0)
        return self.delta_un_sac

    def tolerance(self) -> float:
        """Tolérance courante : plancher minimal OU k * écart-type glissant."""
        if len(self.deltas_confirmes) < 2:
            return self.tolerance_min
        moy = sum(self.deltas_confirmes) / len(self.deltas_confirmes)
        var = sum((d - moy) ** 2 for d in self.deltas_confirmes) / len(self.deltas_confirmes)
        return max(self.tolerance_min, round(self.facteur_std * math.sqrt(var), 3))

    def reinitialiser(self, delta_un_sac: float) -> None:
        """Réinitialise l'apprentissage (service reset_learning)."""
        self.delta_un_sac = float(delta_un_sac)
        self.deltas_confirmes.clear()