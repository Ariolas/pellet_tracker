"""Tests du convertisseur capteur → % (télémètre, capteur inversé, identité).

Exécution :
    pytest tests/                      # si pytest est installé
    python tests/test_conversion.py    # exécution autonome, sans pytest
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from detector import (  # noqa: E402
    ApprentissageAdaptatif, ConvertisseurNiveau, Decision,
    DetecteurRemplissage, formater_niveau,
)

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


# ------------------------------------------------------------------ deltas niveau
def test_delta_niveau_vers_pct():
    """Un delta saisi en niveau brut (ex. cm) devient un % interne."""
    c = ConvertisseurNiveau(valeur_vide=120.0, valeur_pleine=20.0)  # étendue 100
    assert c.delta_niveau_vers_pct(8.0) == 8.0
    c2 = ConvertisseurNiveau(valeur_vide=110.0, valeur_pleine=20.0)  # étendue 90
    assert c2.delta_niveau_vers_pct(9.0) == 10.0
    # le signe du delta importe peu : c'est une magnitude
    assert c.delta_niveau_vers_pct(-8.0) == 8.0


def test_delta_pct_vers_niveau():
    """Un delta interne (%) est restitué en niveau brut pour l'affichage."""
    c = ConvertisseurNiveau(valeur_vide=120.0, valeur_pleine=20.0)  # étendue 100
    assert c.delta_pct_vers_niveau(8.0) == 8.0
    c2 = ConvertisseurNiveau(valeur_vide=110.0, valeur_pleine=20.0)  # étendue 90
    assert c2.delta_pct_vers_niveau(10.0) == 9.0
    assert c2.delta_pct_vers_niveau(-10.0) == 9.0


def test_delta_aller_retour():
    """Niveau → % → niveau : l'aller-retour est stable (ex. capteur poids)."""
    c = ConvertisseurNiveau(valeur_vide=0.0, valeur_pleine=30.0)  # peson, étendue -30
    for delta in (5.0, 7.5, 12.0):
        pct = c.delta_niveau_vers_pct(delta)
        assert c.delta_pct_vers_niveau(pct) == delta


def test_delta_bornes_egales_garde_fou():
    c = ConvertisseurNiveau(valeur_vide=50.0, valeur_pleine=50.0)
    assert c.delta_niveau_vers_pct(8.0) == 8.0
    assert c.delta_pct_vers_niveau(8.0) == 8.0


def test_scenario_telemetre_avec_delta_niveau():
    """Bout en bout : delta saisi en cm, détection toujours correcte."""
    c = ConvertisseurNiveau(valeur_vide=120.0, valeur_pleine=20.0)
    # Un sac fait gagner 10 cm de niveau (delta saisi en cm)
    apprentissage = ApprentissageAdaptatif(
        delta_un_sac=c.delta_niveau_vers_pct(10.0), alpha=1.0
    )
    d = DetecteurRemplissage(
        delta_un_sac=c.delta_niveau_vers_pct(10.0), seuil_bruit_pct=1.5,
        duree_stabilisation_s=STAB, fenetre_hausse_s=120.0,
        apprentissage=apprentissage,
    )
    d.traiter_mesure(c.en_pct(80.0), T0)    # 40 %
    d.traiter_mesure(c.en_pct(70.0), T0 + 10)  # +10 cm = +10 % → 1 sac
    resultat = d.traiter_mesure(c.en_pct(70.0), T0 + 10 + STAB + 1)
    assert resultat.decision == Decision.AUTO
    assert resultat.delta == 10.0
    # l'apprentissage appris reste cohérent, restitué en cm il vaut 10
    assert apprentissage.delta_un_sac == 10.0
    assert c.delta_pct_vers_niveau(apprentissage.delta_un_sac) == 10.0


# ------------------------------------------------------------------ formatage
def test_formater_niveau_precision_adaptive():
    """Jusqu'à 3 décimales, zéros finaux retirés (petites unités capteur)."""
    assert formater_niveau(3.7) == "3.7"
    assert formater_niveau(0.032) == "0.032"
    assert formater_niveau(8.0) == "8"
    assert formater_niveau(0.37) == "0.37"
    assert formater_niveau(0.0376) == "0.038"  # arrondi à 3 décimales


def test_formater_niveau_zero_et_negligeable():
    assert formater_niveau(0.0) == "0"
    assert formater_niveau(0.0004) == "0"  # sous la précision d'affichage


def test_formater_niveau_scenario_notification():
    """Le cas qui a motivé la fonction : hausse de 6 % d'une cuve de 0,5."""
    c = ConvertisseurNiveau(valeur_vide=0.5, valeur_pleine=0.0)
    hausse_niveau = c.delta_pct_vers_niveau(6.0)  # 6 % de la cuve → 0.03
    assert hausse_niveau == 0.03
    texte = f"Hausse de {formater_niveau(hausse_niveau)} de niveau détectée"
    assert "0.03" in texte  # lisible, pas « 0.0 »
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
    print(f"{len(tests) - echecs}/{len(tests)} tests OK")
