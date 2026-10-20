"""Tests du convertisseur capteur → % (télémètre, capteur inversé, identité).

Exécution :
    pytest tests/                      # si pytest est installé
    python tests/test_conversion.py    # exécution autonome, sans pytest
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from detector import ConvertisseurNiveau, Decision, DetecteurRemplissage  # noqa: E402

T0 = 1_000_000.0
STAB = 180.0


# ------------------------------------------------------------------ conversion
def test_telemetre_distance():
    """Télémètre : plus la cuve se vide, plus la distance augmente."""
    c = ConvertisseurNiveau(valeur_vide=120.0, valeur_pleine=20.0)
    assert c.en_pct(120.0) == 0.0   # cuve vide
    assert c.en_pct(20.0) == 100.0  # cuve pleine
    assert c.en_pct(70.0) == 50.0   # à mi-hauteur
    # le sens est bien inversé : distance qui monte → % qui baisse
    assert c.en_pct(90.0) < c.en_pct(60.0)


def test_bornage_hors_plage():
    """Mesures au-delà des bornes physiques : % borné à [0, 100]."""
    c = ConvertisseurNiveau(valeur_vide=120.0, valeur_pleine=20.0)
    assert c.en_pct(200.0) == 0.0    # plus loin que « vide »
    assert c.en_pct(0.0) == 100.0   # plus près que « pleine »


def test_identite_pour_capteur_en_pourcent():
    """Avec (0, 100), un capteur qui expose déjà un % n'est pas modifié."""
    c = ConvertisseurNiveau(valeur_vide=0.0, valeur_pleine=100.0)
    assert c.en_pct(55.0) == 55.0
    assert c.en_pct(0.0) == 0.0
    assert c.en_pct(100.0) == 100.0


def test_ordre_inverse_poids():
    """Capteur dont la valeur monte quand la cuve se remplit (ex. poids)."""
    c = ConvertisseurNiveau(valeur_vide=0.0, valeur_pleine=100.0)
    assert c.en_pct(0.0) == 0.0
    assert c.en_pct(100.0) == 100.0
    assert c.en_pct(50.0) == 50.0


def test_valeurs_egales_garde_fou():
    c = ConvertisseurNiveau(valeur_vide=50.0, valeur_pleine=50.0)
    assert c.en_pct(42.0) == 42.0  # pas de division par zéro


# ------------------------------------------------------------------ bout en bout
def test_scenario_telemetre_consommation_puis_remplissage():
    """Cuve pilotée par télémètre : la distance remonte quand on consomme,
    et chute brutalement quand on remplit → remplissage AUTO détecté."""
    c = ConvertisseurNiveau(valeur_vide=120.0, valeur_pleine=20.0)
    d = DetecteurRemplissage(
        delta_un_sac=8.0, seuil_bruit_pct=1.5,
        duree_stabilisation_s=STAB, fenetre_hausse_s=120.0,
    )

    # Consommation : la distance augmente (70 → 78 cm), le % baisse
    assert d.traiter_mesure(c.en_pct(70.0), T0) is None
    assert d.traiter_mesure(c.en_pct(78.0), T0 + 3600) is None
    assert d.niveau_actuel == 42.0  # (120-78)/100*100

    # Remplissage d'un sac : la distance chute (78 → 70), le % saute de 42 à 50
    assert d.traiter_mesure(c.en_pct(70.0), T0 + 3600 + 10) is None
    assert d.remplissage_en_cours is True
    resultat = d.traiter_mesure(c.en_pct(70.0), T0 + 3600 + 10 + STAB + 1)
    assert resultat is not None
    assert resultat.decision == Decision.AUTO
    assert resultat.delta == 8.0
    assert resultat.niveau_avant == 42.0
    assert resultat.niveau_apres == 50.0


def test_scenario_telemetre_rien_quand_distance_stable():
    """Un télémètre silencieux ne déclenche rien."""
    c = ConvertisseurNiveau(valeur_vide=120.0, valeur_pleine=20.0)
    d = DetecteurRemplissage(
        delta_un_sac=8.0, seuil_bruit_pct=1.5,
        duree_stabilisation_s=STAB, fenetre_hausse_s=120.0,
    )
    for t in range(5):
        assert d.traiter_mesure(c.en_pct(75.0), T0 + t * 3600) is None
    assert d.remplissage_en_cours is False


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
