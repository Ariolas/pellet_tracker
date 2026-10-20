"""Tests unitaires du détecteur de remplissage (aucune dépendance Home Assistant).

Exécution :
    pytest tests/                      # si pytest est installé
    python tests/test_detector.py      # exécution autonome, sans pytest
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from detector import (  # noqa: E402
    ApprentissageAdaptatif,
    Decision,
    DetecteurRemplissage,
    Etat,
)

T0 = 1_000_000.0  # base de temps arbitraire (epoch s)
STAB = 180.0      # duree_stabilisation par défaut des tests


def detecteur(**kwargs) -> DetecteurRemplissage:
    """Détecteur avec valeurs de test (1 sac = 8 %)."""
    kwargs.setdefault("delta_un_sac", 8.0)
    kwargs.setdefault("seuil_bruit_pct", 1.5)
    kwargs.setdefault("duree_stabilisation_s", STAB)
    kwargs.setdefault("fenetre_hausse_s", 120.0)
    return DetecteurRemplissage(**kwargs)


# ------------------------------------------------------------------ initialisation
def test_premiere_mesure_initialise():
    d = detecteur()
    assert d.niveau_actuel is None
    assert d.traiter_mesure(50.0, T0) is None
    assert d.niveau_actuel == 50.0
    assert d.etat == Etat.VEILLE


def test_niveau_zero_est_valide():
    d = detecteur()
    d.traiter_mesure(0.0, T0)
    assert d.niveau_actuel == 0.0
    assert d.etat == Etat.VEILLE  # pas de faux départ de hausse


def test_mesures_invalides_ignorees():
    d = detecteur()
    d.traiter_mesure(50.0, T0)
    for invalide in (-5.0, 105.0, float("nan")):
        assert d.traiter_mesure(invalide, T0 + 10) is None
    assert d.niveau_actuel == 50.0


# ------------------------------------------------------------------ consommation
def test_baisse_ne_declenche_rien():
    d = detecteur()
    d.traiter_mesure(50.0, T0)
    assert d.traiter_mesure(48.0, T0 + 60) is None
    assert d.etat == Etat.VEILLE
    assert d.niveau_actuel == 48.0


# ------------------------------------------------------------------ remplissages
def test_remplissage_complet_auto():
    d = detecteur()
    d.traiter_mesure(50.0, T0)
    # Hausse franche de 8 % (> seuil de bruit) → HAUSSE
    assert d.traiter_mesure(58.0, T0 + 10) is None
    assert d.etat == Etat.HAUSSE
    assert d.remplissage_en_cours is True
    # Silence supérieur à la durée de stabilisation → confirmation AUTO
    resultat = d.traiter_mesure(58.0, T0 + 10 + STAB + 1)
    assert resultat is not None
    assert resultat.decision == Decision.AUTO
    assert resultat.delta == 8.0
    assert resultat.niveau_avant == 50.0
    assert resultat.niveau_apres == 58.0
    assert d.etat == Etat.VEILLE


def test_remplissage_partiel():
    d = detecteur()
    d.traiter_mesure(50.0, T0)
    d.traiter_mesure(53.0, T0 + 10)  # +3 % : ni bruit, ni 1 sac
    resultat = d.traiter_mesure(53.0, T0 + 10 + STAB + 1)
    assert resultat is not None
    assert resultat.decision == Decision.PARTIEL
    assert resultat.delta == 3.0


def test_hausse_lente_retourne_en_veille():
    d = detecteur()
    d.traiter_mesure(50.0, T0)
    d.traiter_mesure(52.0, T0 + 10)  # départ HAUSSE
    # La hausse traîne au-delà de la fenêtre (120 s) → dérive, pas un remplissage
    for i in range(1, 5):
        assert d.traiter_mesure(52.0 + i, T0 + 10 + i * 60) is None
    assert d.etat == Etat.VEILLE
    # Pas de confirmation possible ensuite
    assert d.confirmer_si_stable(T0 + 10_000) is None


def test_stabilisation_insuffisante_ne_confirme_pas():
    d = detecteur()
    d.traiter_mesure(50.0, T0)
    d.traiter_mesure(58.0, T0 + 10)
    # mesure avant la fin du silence → relance le chrono, pas de confirmation
    assert d.traiter_mesure(58.0, T0 + 30) is None
    assert d.etat == Etat.HAUSSE


def test_confirmation_par_timer_sans_nouvelle_mesure():
    """Le capteur peut se taire après la hausse : le timer doit pouvoir confirmer."""
    d = detecteur()
    d.traiter_mesure(50.0, T0)
    d.traiter_mesure(58.0, T0 + 10)
    assert d.confirmer_si_stable(T0 + 10 + STAB - 1) is None  # trop tôt
    resultat = d.confirmer_si_stable(T0 + 10 + STAB)
    assert resultat is not None
    assert resultat.decision == Decision.AUTO
    assert d.etat == Etat.VEILLE


def test_bruit_classe_directement():
    """classer_delta est aussi testé isolément (deltas ≤ seuil)."""
    d = detecteur()
    assert d.classer_delta(1.0) == Decision.BRUIT
    assert d.classer_delta(8.2) == Decision.AUTO
    assert d.classer_delta(3.0) == Decision.PARTIEL
    assert d.classer_delta(20.0) == Decision.PARTIEL


# ------------------------------------------------------------------ apprentissage
def test_ema_affine_le_delta():
    a = ApprentissageAdaptatif(delta_un_sac=8.0, alpha=0.3)
    assert a.confirmer(7.0) == round(0.3 * 7.0 + 0.7 * 8.0, 3)  # 7.3
    assert a.confirmer(7.0) == round(0.3 * 7.0 + 0.7 * 7.7, 3)  # 7.49
    assert a.deltas_confirmes == [7.0, 7.0]


def test_fenetre_glissante_bornee():
    a = ApprentissageAdaptatif(delta_un_sac=8.0, fenetre_std=3)
    for delta in (7.0, 7.5, 8.0, 9.0):
        a.confirmer(delta)
    assert a.deltas_confirmes == [7.5, 8.0, 9.0]  # les plus anciens éjectés


def test_tolerance_plancher_puis_ecart_type():
    a = ApprentissageAdaptatif(delta_un_sac=8.0, fenetre_std=10, tolerance_min=1.5, facteur_std=2.0)
    assert a.tolerance() == 1.5  # moins de 2 deltas → plancher
    a.confirmer(8.0)
    a.confirmer(9.0)
    # std de [8, 9] = 0.5 → tolérance = max(1.5, 2*0.5) = 1.5 (plancher)
    assert a.tolerance() == 1.5
    a.confirmer(6.0)
    # deltas [8, 9, 6] : moy=7.67, std≈1.247 → 2*std≈2.49 > plancher
    assert a.tolerance() == max(1.5, round(2.0 * math.sqrt(
        sum((d - 23.0 / 3) ** 2 for d in (8.0, 9.0, 6.0)) / 3), 3))


def test_reinitialisation():
    a = ApprentissageAdaptatif(delta_un_sac=8.0)
    a.confirmer(7.0)
    a.reinitialiser(9.0)
    assert a.delta_un_sac == 9.0
    assert a.deltas_confirmes == []


def test_tolerance_adaptative_suit_le_detecteur():
    """Après apprentissage, un delta appris devient AUTO."""
    apprentissage = ApprentissageAdaptatif(delta_un_sac=8.0, alpha=1.0)
    apprentissage.confirmer(6.0)  # alpha=1 : le delta appris saute à 6
    d = DetecteurRemplissage(
        delta_un_sac=8.0, seuil_bruit_pct=1.5,
        duree_stabilisation_s=STAB, fenetre_hausse_s=120.0,
        apprentissage=apprentissage,
    )
    d.traiter_mesure(50.0, T0)
    d.traiter_mesure(56.0, T0 + 10)  # +6 : serait PARTIEL avec delta=8
    resultat = d.traiter_mesure(56.0, T0 + 10 + STAB + 1)
    assert resultat.decision == Decision.AUTO


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    echecs = 0
    for nom, fn in tests:
        try:
            fn()
            print(f"PASS {nom}")
        except AssertionError as exc:
            echecs += 1
            print(f"FAIL {nom}: {exc}")
    print(f"\n{len(tests) - echecs}/{len(tests)} tests OK")
    sys.exit(1 if echecs else 0)
