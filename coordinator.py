"""Coordonnateur : écoute le capteur, anime le détecteur, déclenche les
notifications et met à jour les données exposées aux entités."""
from __future__ import annotations

import logging
import secrets
import time
from typing import Any, Optional

from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)

from .const import (
    CONF_NOTIFY, CONF_SEUIL_BRUIT, CONF_FENETRE_HAUSSE,
    CONF_DUREE_STABILISATION, CONF_ALPHA_EMA, CONF_FENETRE_STD,
    CONF_TOLERANCE_MIN, CONF_VALEUR_VIDE, CONF_VALEUR_PLEINE,
    CONF_DELTA_UN_SAC,
    DEFAULT_SEUIL_BRUIT, DEFAULT_DUREE_STABILISATION,
    DEFAULT_FENETRE_HAUSSE, DEFAULT_ALPHA_EMA, DEFAULT_FENETRE_STD,
    DEFAULT_TOLERANCE_MIN, DEFAULT_DELTA_UN_SAC,
    DEFAULT_VALEUR_VIDE, DEFAULT_VALEUR_PLEINE,
    EVENT_MOBILE_APP_ACTION,
    ACTION_ACQUITTER, ACTION_CORRECTION,
    ACTION_SAC_COMPLET, ACTION_SAC_PARTIEL, ACTION_FIN_DE_SAC,
)
from .detector import (
    ApprentissageAdaptatif, ConvertisseurNiveau, Decision,
    DetecteurRemplissage, Etat, EvenementRemplissage, ResultatRemplissage,
)
from .storage import PelletStorage

_LOGGER = logging.getLogger(__name__)

# Actions de notification attendues, avec leur effet sur le comptage.
_ACTIONS = (ACTION_ACQUITTER, ACTION_CORRECTION,
            ACTION_SAC_COMPLET, ACTION_SAC_PARTIEL, ACTION_FIN_DE_SAC)


def _cibles_notify(valeur: Any) -> list[str]:
    """Normalise la valeur de CONF_NOTIFY en liste de cibles.

    Historique : la valeur était une chaîne unique ; les flows récents
    produisent une liste (sélection multiple).
    """
    if valeur is None:
        return []
    if isinstance(valeur, str):
        return [valeur]
    return list(valeur)


class PelletCoordinator:
    """Centralise toute la logique de suivi pour une config entry.

    Modèle de comptage : un sac consommé est compté quand son
    REMPLISSAGE est constaté (détecté avec confiance → comptage auto,
    ou confirmé via les boutons de notification). La baisse du niveau
    n'est qu'une estimation, elle n'incrémente jamais le compteur.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.storage = PelletStorage(hass, entry.entry_id)

        # Paramètres de la config entry (avec valeurs par défaut)
        self.notify_targets = _cibles_notify(
            entry.options.get(CONF_NOTIFY, entry.data.get(CONF_NOTIFY))
        )
        seuil_bruit = entry.options.get(CONF_SEUIL_BRUIT, DEFAULT_SEUIL_BRUIT)
        duree_stab = entry.options.get(CONF_DUREE_STABILISATION, DEFAULT_DUREE_STABILISATION)
        fenetre_hausse = entry.options.get(CONF_FENETRE_HAUSSE, DEFAULT_FENETRE_HAUSSE)
        alpha = entry.options.get(CONF_ALPHA_EMA, DEFAULT_ALPHA_EMA)
        fenetre_std = entry.options.get(CONF_FENETRE_STD, DEFAULT_FENETRE_STD)
        tolerance_min = entry.options.get(CONF_TOLERANCE_MIN, DEFAULT_TOLERANCE_MIN)
        # Le capteur peut être un télémètre : la mesure brute est convertie
        # en % de remplissage avant d'alimenter la machine à états.
        valeur_vide = entry.options.get(
            CONF_VALEUR_VIDE, entry.data.get(CONF_VALEUR_VIDE, DEFAULT_VALEUR_VIDE)
        )
        valeur_pleine = entry.options.get(
            CONF_VALEUR_PLEINE, entry.data.get(CONF_VALEUR_PLEINE, DEFAULT_VALEUR_PLEINE)
        )
        self.convertisseur = ConvertisseurNiveau(valeur_vide, valeur_pleine)
        # Le delta d'un sac est saisi en NIVEAU BRUT (mesurable directement :
        # niveau avant/après remplissage) et converti en % interne.
        delta_initial = entry.options.get(
            CONF_DELTA_UN_SAC, entry.data.get(CONF_DELTA_UN_SAC, DEFAULT_DELTA_UN_SAC)
        )
        delta_initial_pct = self.convertisseur.delta_niveau_vers_pct(delta_initial)

        self.data: dict[str, Any] = {}
        self.apprentissage = ApprentissageAdaptatif(
            delta_un_sac=delta_initial_pct,
            alpha=alpha,
            fenetre_std=fenetre_std,
            tolerance_min=tolerance_min,
        )
        self.detecteur = DetecteurRemplissage(
            delta_un_sac=delta_initial_pct,
            seuil_bruit_pct=seuil_bruit,
            duree_stabilisation_s=duree_stab,
            fenetre_hausse_s=fenetre_hausse,
            apprentissage=self.apprentissage,
        )
        self._listeners: list[Any] = []
        self._update_callbacks: list[Any] = []
        self._unsub_timer: Any = None  # timer de confirmation (capteur silencieux)

    # ------------------------------------------------------------------ setup
    async def async_setup(self) -> None:
        """Charge la persistance, restaure l'apprentissage, écoute le capteur."""
        self.data = await self.storage.async_charger()
        if self.data.get("delta_un_sac") is not None:
            # La valeur persistée est en % interne (apprentissage), pas en
            # niveau brut : elle se réapplique telle quelle.
            self.apprentissage.delta_un_sac = self.data["delta_un_sac"]
        self.apprentissage.deltas_confirmes = self.data.get("deltas_confirmes", [])

        capteur = self.entry.data["sensor_niveau"]
        self._listeners.append(
            async_track_state_change_event(self.hass, [capteur], self._on_capteur)
        )
        # Amorçage avec l'état courant du capteur : sans cela, le niveau
        # resterait None/0 jusqu'au premier changement d'état après redémarrage
        etat_capteur = self.hass.states.get(capteur)
        if etat_capteur is not None and etat_capteur.state not in ("unknown", "unavailable"):
            try:
                self.detecteur.traiter_mesure(
                    self.convertisseur.en_pct(float(etat_capteur.state)), time.time()
                )
            except ValueError:
                pass
        _LOGGER.info("pellet_tracker actif, capteur écouté : %s (vide=%s, pleine=%s)",
                     capteur, self.convertisseur.valeur_vide,
                     self.convertisseur.valeur_pleine)

    async def async_unload(self) -> None:
        self._gerer_timer_annulation()
        for off in self._listeners:
            off()
        self._listeners.clear()
        # Les entités sont déjà déchargées à ce stade : on lâche leurs callbacks
        self._update_callbacks.clear()

    # -------------------------------------------------- entités (rAF pattern)
    @callback
    def on_update(self, cb: Any) -> Any:
        """Enregistre un callback d'actualisation d'entité.

        Retourne la fonction de désabonnement : les entités s'abonnent
        dans async_added_to_hass et se désabonnent dans
        async_will_remove_from_hass, pour ne jamais laisser de callback
        mort (entité non ajoutée ou retirée) dans la boucle.
        """
        self._update_callbacks.append(cb)

        @callback
        def _unsub() -> None:
            try:
                self._update_callbacks.remove(cb)
            except ValueError:
                pass  # déjà retiré

        return _unsub

    @callback
    def _notify_entities(self) -> None:
        for cb in self._update_callbacks:
            cb()

    # -------------------------------------------------- écoute du capteur
    @callback
    def _on_capteur(self, event: Event) -> None:
        """Chaque changement d'état du capteur alimente la machine à états.

        La mesure brute (distance pour un télémètre) est convertie en %
        de remplissage AVANT tout traitement : c'est le % qui baisse quand
        la cuve se vide, jamais la valeur brute.
        """
        ancien: Optional[State] = event.data.get("old_state")
        nouveau: Optional[State] = event.data.get("new_state")
        if nouveau is None or nouveau.state in ("unknown", "unavailable"):
            return
        try:
            niveau = self.convertisseur.en_pct(float(nouveau.state))
        except ValueError:
            return

        maintenant = time.time()
        if ancien and ancien.state not in ("unknown", "unavailable"):
            try:
                ancien_niveau = self.convertisseur.en_pct(float(ancien.state))
            except ValueError:
                ancien_niveau = niveau
        else:
            ancien_niveau = niveau
        variation = niveau - ancien_niveau

        # --- Suivi indicatif de la consommation (ne compte PAS les sacs :
        # seul un remplissage constaté incrémente le compteur) ---
        if not self.detecteur.remplissage_en_cours and variation < 0:
            self.data["niveau_consome_pct"] = self.data.get("niveau_consome_pct", 0.0) - variation
            self.hass.async_create_task(self.storage.async_sauver(self.data))

        # --- Machine à états + (re)planification du timer de confirmation ---
        resultat = self.detecteur.traiter_mesure(niveau, maintenant)
        self._gerer_timer(maintenant)
        if resultat is not None:
            self._traiter_resultat(resultat, maintenant)
        self._notify_entities()

    def _traiter_resultat(self, resultat: ResultatRemplissage, maintenant: float) -> None:
        """Historise un remplissage confirmé, compte et notifie selon la décision."""
        evenement = EvenementRemplissage(
            niveau_avant=resultat.niveau_avant,
            niveau_apres=resultat.niveau_apres,
            delta=resultat.delta,
            decision=resultat.decision,
            timestamp=maintenant,
        )
        # ATTENTION : pas d'Enum dans le dict persisté (le .storage est du
        # JSON, une Enum y lèverait TypeError) → on stocke .value
        ev_dict = {
            "timestamp": evenement.timestamp,
            "delta": evenement.delta,  # % interne
            "decision": evenement.decision.value,
            "niveau_avant": evenement.niveau_avant,
            "niveau_apres": evenement.niveau_apres,
            "confirme": evenement.confirme,
        }

        if evenement.decision == Decision.AUTO:
            # Hausse ≈ 1 sac avec confiance (fenêtre de tolérance) :
            # comptage immédiat + apprentissage, notification affirmant
            # le comptage avec boutons Acquitter / Correction.
            self._compter_sac(source="auto")
            self.apprentissage.confirmer(evenement.delta)
            self._persister_delta_appris()
            ev_dict["confirme"] = True
            self.data["evenements"].append(ev_dict)
            attente = {
                "action_id": f"pellet_{secrets.token_hex(4)}",
                "delta": evenement.delta,
                "timestamp": maintenant,
                "evenement_index": len(self.data["evenements"]) - 1,
                "type": "auto",
                "compte": 1,  # sacs déjà comptés par la décision AUTO
            }
            self.data["attente_confirmation"] = attente
            # Prévalidation (confiance haute) : la date de détection est
            # inscrite IMMÉDIATEMENT comme dernier remplissage ; une
            # Correction via la notification la restaurera (rollback).
            # Le silence ne fait rien : acceptation par défaut.
            self.data["precedent_remplissage_valide"] = self.data.get("dernier_remplissage_valide")
            self.data["dernier_remplissage_valide"] = {
                "timestamp": maintenant,
                "rempli_le": evenement.timestamp,
                "delta": evenement.delta,
                "decision": "auto",
                "niveau_avant": evenement.niveau_avant,
                "niveau_apres": evenement.niveau_apres,
                "reponse": None,  # prévalidé : acquittement en attente
            }
            self.hass.async_create_task(
                self._notifier_remplissage(evenement, attente["action_id"], auto=True)
            )
        elif evenement.decision == Decision.PARTIEL:
            # Hausse ≠ 1 sac ou doute : rien n'est compté, la notification
            # propose Sac complet / Sac partiel / Fin de sac.
            self.data["evenements"].append(ev_dict)
            attente = {
                "action_id": f"pellet_{secrets.token_hex(4)}",
                "delta": evenement.delta,
                "timestamp": maintenant,
                "evenement_index": len(self.data["evenements"]) - 1,
                "type": "partiel",
                "compte": 0,  # rien compté tant que l'utilisateur n'a pas répondu
            }
            self.data["attente_confirmation"] = attente
            self.hass.async_create_task(
                self._notifier_remplissage(evenement, attente["action_id"], auto=False)
            )
        else:
            _LOGGER.info("Remplissage ignoré (delta %.2f%% ≈ bruit)", evenement.delta)

    def _persister_delta_appris(self) -> None:
        """Synchronise le delta appris dans les données persistées.

        Sans cela, data["delta_un_sac"] resterait None et l'apprentissage
        serait perdu à chaque redémarrage.
        """
        self.data["delta_un_sac"] = self.apprentissage.delta_un_sac

    # -------------------------------------------------- timer de confirmation
    def _gerer_timer(self, maintenant: float) -> None:
        """(Re)planifie le timer : le capteur peut cesser d'émettre après
        le remplissage (heartbeat ESPHome), la confirmation ne doit pas
        dépendre de l'arrivée d'une nouvelle mesure."""
        self._gerer_timer_annulation()
        if self.detecteur.etat == Etat.HAUSSE:
            delai = self.detecteur.duree_stabilisation - (
                maintenant - self.detecteur.t_derniere_variation
            )
            self._unsub_timer = async_call_later(
                self.hass, max(delai, 1.0), self._on_timer
            )

    def _gerer_timer_annulation(self) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    @callback
    def _on_timer(self, _now: Any) -> None:
        """Fin de la durée de stabilisation sans nouvelle mesure → confirmation."""
        self._unsub_timer = None
        resultat = self.detecteur.confirmer_si_stable(time.time())
        if resultat is not None:
            self._traiter_resultat(resultat, time.time())
            self._notify_entities()

    # -------------------------------------------------- actions
    def _confirmer_delta(self, delta: float, reponse: str, rempli_le: float) -> None:
        """Mémorise le dernier delta confirmé (événement d'apprentissage).

        Nourrit le diagnostic « Dernier remplissage confirmé » : la hausse
        détectée est inscrite UNIQUEMENT à la confirmation d'un événement
        qui a fait apprendre l'intégration — Acquitter (AUTO confirmé) ou
        Sac complet. Jamais sur Correction, Fin de sac (compté sans
        apprentissage), Sac partiel ou silence.
        """
        self.data["dernier_delta_confirme"] = {
            "delta": delta,  # % interne
            "reponse": reponse,
            "rempli_le": rempli_le,
            "timestamp": time.time(),  # date de confirmation
        }

    def _compter_sac(self, source: str = "manuel", nombre: int = 1) -> None:

        """Incrémente le compteur de sacs (auto, confirmation ou service)."""
        if source == "auto":
            self.data["sacs_ajoutes"] = self.data.get("sacs_ajoutes", 0) + nombre
        elif source == "confirmation":
            self.data["sacs_confirmes"] = self.data.get("sacs_confirmes", 0) + nombre
        else:
            self.data["sacs_manuels"] = self.data.get("sacs_manuels", 0) + nombre
        _LOGGER.info("Sac compté (%s) — total auto=%s confirmes=%s manuels=%s",
                     source, self.data.get("sacs_ajoutes", 0),
                     self.data.get("sacs_confirmes", 0),
                     self.data.get("sacs_manuels", 0))

    async def _notifier(self, title: str, message: str,
                        data: Optional[dict[str, Any]] = None) -> None:
        """Envoie une notification sur toutes les cibles configurées."""
        if not self.notify_targets:
            _LOGGER.warning("Aucune cible de notification configurée")
            return
        for cible in self.notify_targets:
            service_data: dict[str, Any] = {"title": title, "message": message}
            if data:
                service_data["data"] = data
            await self.hass.services.async_call(
                "notify",
                cible.removeprefix("notify."),
                service_data,
                blocking=True,
            )

    async def _notifier_remplissage(self, evenement: EvenementRemplissage,
                                    action_id: str, auto: bool) -> None:
        """Notification de remplissage avec boutons de réponse.

        - AUTO (confiance haute, déjà compté) : Acquitter / Correction.
        - PARTIEL (rien compté) : Sac complet / Sac partiel / Fin de sac.
        """
        # Le delta interne (%) est affiché en niveau brut, comme saisi
        # à la configuration : plus parlant pour l'utilisateur.
        delta_niveau = self.convertisseur.delta_pct_vers_niveau(evenement.delta)
        if auto:
            message = (
                f"Remplissage détecté : +{delta_niveau:.1f} de niveau "
                f"(≈ 1 sac) compté automatiquement."
            )
            actions = [
                {"action": f"{ACTION_ACQUITTER}:{action_id}", "title": "Acquitter"},
                {"action": f"{ACTION_CORRECTION}:{action_id}", "title": "Correction (-1 sac)"},
            ]
        else:
            ratio = evenement.delta / max(self.apprentissage.delta_un_sac, 0.1)
            message = (
                f"Hausse de {delta_niveau:.1f} de niveau détectée (≈ {ratio:.1f} sac). "
                "Compter un sac ?"
            )
            actions = [
                {"action": f"{ACTION_SAC_COMPLET}:{action_id}", "title": "Sac complet"},
                {"action": f"{ACTION_SAC_PARTIEL}:{action_id}", "title": "Sac partiel"},
                {"action": f"{ACTION_FIN_DE_SAC}:{action_id}", "title": "Fin de sac"},
            ]
        await self.storage.async_sauver(self.data)
        await self._notifier(
            "Poêle à granulés",
            message,
            data={"tag": action_id, "actions": actions},
        )

    async def async_test_notification(self) -> None:
        """Notification de test sur toutes les cibles configurées.

        Utilisée par le bouton « Tester la notification ».
        """
        await self._notifier(
            "Poêle à granulés",
            "Notification de test de pellet_tracker : tout fonctionne.",
        )

    @callback
    def on_notification_action(self, event: Event) -> None:
        """Gère les réponses aux boutons des notifications.

        AUTO (compté d'office) :
          - Acquitter  → comptage validé, rien à faire ;
          - Correction → retire le sac compté (l'apprentissage EMA,
            déjà intégré, n'est pas réversible).
        PARTIEL (rien compté d'office) :
          - Sac complet → compte le sac ET apprend sur ce delta ;
          - Sac partiel → ne compte rien, n'apprend rien ;
          - Fin de sac  → compte le sac SANS apprentissage (le delta
            ne représente pas un sac entier : fin de sac entamé).
        """
        action: str = event.data.get("action", "")
        if not action.startswith(_ACTIONS):
            return
        action_name, _, action_id = action.partition(":")
        attente = self.data.get("attente_confirmation")
        if not attente or attente.get("action_id") != action_id:
            return  # réponse périmée ou déjà traitée

        reponse = None
        if attente.get("type") == "auto":
            if action_name == ACTION_ACQUITTER:
                reponse = "acquitte"
                # La prévalidation devient définitive : date de détection
                # conservée (pas de nouvelle écriture), backup libéré.
                self.data["precedent_remplissage_valide"] = None
                if isinstance(self.data.get("dernier_remplissage_valide"), dict):
                    self.data["dernier_remplissage_valide"]["reponse"] = "acquitte"
                self._confirmer_delta(attente["delta"], "acquitte", attente["timestamp"])
            elif action_name == ACTION_CORRECTION:
                reponse = "correction"
                compte = attente.get("compte", 1)
                self.data["sacs_ajoutes"] = max(0, self.data.get("sacs_ajoutes", 0) - compte)
                # Annulation de la prévalidation : retour au dernier
                # remplissage précédent (l'entité event revient à la date
                # antérieure sans re-déclencher d'event).
                self.data["dernier_remplissage_valide"] = self.data.get("precedent_remplissage_valide")
                self.data["precedent_remplissage_valide"] = None
                _LOGGER.info(
                    "Correction utilisateur : %s sac(s) retiré(s) du comptage auto, prévalidation annulée",
                    compte,
                )
        elif attente.get("type") == "partiel":
            delta = attente["delta"]
            if action_name == ACTION_SAC_COMPLET:
                reponse = "sac_complet"
                self._compter_sac(source="confirmation")
                self.apprentissage.confirmer(delta)
                self._persister_delta_appris()
                self._confirmer_delta(delta, "sac_complet", attente["timestamp"])
                _LOGGER.info("Remplissage partiel confirmé « sac complet » "
                             "(+%.2f%%) → 1 sac compté, apprentissage", delta)
            elif action_name == ACTION_FIN_DE_SAC:
                reponse = "fin_de_sac"
                self._compter_sac(source="confirmation")
                _LOGGER.info("Remplissage « fin de sac » (+%.2f%%) → 1 sac compté, "
                             "sans apprentissage", delta)
            elif action_name == ACTION_SAC_PARTIEL:
                reponse = "sac_partiel"
                _LOGGER.info("Remplissage partiel : l'utilisateur n'a pas compté de sac")

        if reponse is None:
            # type inconnu (ancien format) ou action non pertinente : on purge
            self.data["attente_confirmation"] = None
            return
        self.data["attente_confirmation"] = None

        # Trace la réponse de l'utilisateur sur l'événement correspondant
        index = attente.get("evenement_index")
        evenements = self.data.get("evenements", [])
        ev = (
            evenements[index]
            if index is not None and 0 <= index < len(evenements)
            else {}
        )
        if ev:
            ev["reponse"] = reponse
            ev["confirme"] = reponse in ("acquitte", "sac_complet", "fin_de_sac")

        # Sac complet / Fin de sac : création de la validation à la date de
        # la réponse (pas de prévalidation pour les partiels). Acquitter
        # n'entre pas ici : la prévalidation AUTO est déjà en place.
        if reponse in ("sac_complet", "fin_de_sac"):
            self.data["dernier_remplissage_valide"] = {
                "timestamp": time.time(),      # date de validation
                "rempli_le": ev.get("timestamp"),  # date du remplissage détecté
                "delta": attente.get("delta", ev.get("delta")),
                "decision": ev.get("decision"),
                "niveau_avant": ev.get("niveau_avant"),
                "niveau_apres": ev.get("niveau_apres"),
                "reponse": reponse,
            }


        self.hass.async_create_task(self.storage.async_sauver(self.data))
        self._notify_entities()

    # -------------------------------------------------- données calculées
    @property
    def sacs_consommes(self) -> float:
        """Sacs consommés : total COMPTÉ, pas estimé.

        Un sac est consommé quand son remplissage est constaté :
        détection automatique à confiance haute, confirmation par
        bouton de notification, ou service add_bag manuel.
        """
        return (
            self.data.get("sacs_ajoutes", 0)
            + self.data.get("sacs_confirmes", 0)
            + self.data.get("sacs_manuels", 0)
        )

    @property
    def sacs_restants(self) -> Optional[float]:
        """Autonomie : niveau actuel / % gagné par sac (None avant 1re mesure)."""
        delta = max(self.apprentissage.delta_un_sac, 0.1)
        niveau = self.detecteur.niveau_actuel
        if niveau is None:
            return None
        return round(niveau / delta, 2)

    @property
    def dernier_evenement(self) -> Optional[dict]:
        evts = self.data.get("evenements", [])
        return evts[-1] if evts else None

    @property
    def delta_initial(self) -> float:
        """Delta d'un sac de base, en NIVEAU BRUT (saisie configuration)."""
        return self.entry.options.get(
            CONF_DELTA_UN_SAC,
            self.entry.data.get(CONF_DELTA_UN_SAC, DEFAULT_DELTA_UN_SAC),
        )

    @property
    def delta_initial_pct(self) -> float:
        """Delta d'un sac de base, converti en % interne."""
        return self.convertisseur.delta_niveau_vers_pct(self.delta_initial)

    @property
    def dernier_remplissage_valide(self) -> Optional[dict]:
        """Dernier remplissage VALIDÉ par l'utilisateur (ou None).

        Mis à jour uniquement sur Acquitter / Sac complet / Fin de sac :
        l'entité event « Dernier remplissage » se déclenche dessus, pas sur
        les détections (un faux positif corrigé ne doit pas polluer la date).
        """
        return self.data.get("dernier_remplissage_valide")

    @property
    def dernier_delta_confirme(self) -> Optional[dict]:
        """Dernier delta confirmé, ayant déclenché un apprentissage.

        Diagnostique « Dernier remplissage confirmé » : uniquement sur
        Acquitter (AUTO confirmé) ou Sac complet. None tant qu'aucune
        confirmation d'apprentissage n'a eu lieu.
        """
        return self.data.get("dernier_delta_confirme")

    # -------------------------------------------------- services
    async def async_add_bag(self, nombre: int = 1) -> None:
        """Service pellet_tracker.add_bag."""
        self._compter_sac(source="manuel", nombre=nombre)
        await self.storage.async_sauver(self.data)
        self._notify_entities()

    async def async_reset_counter(self) -> None:
        """Service pellet_tracker.reset_counter."""
        self.data.update({
            "sacs_ajoutes": 0,
            "sacs_confirmes": 0,
            "sacs_manuels": 0,
            "niveau_consome_pct": 0.0,
        })
        await self.storage.async_sauver(self.data)
        self._notify_entities()

    async def async_reset_learning(self, delta_un_sac: Optional[float] = None) -> None:
        """Service pellet_tracker.reset_learning : repart de la calibration.

        Le paramètre optionnel est en NIVEAU BRUT (comme à la configuration)
        et converti en % interne.
        """
        delta_pct = (
            self.convertisseur.delta_niveau_vers_pct(delta_un_sac)
            if delta_un_sac else self.delta_initial_pct
        )
        self.apprentissage.reinitialiser(delta_pct)
        self._persister_delta_appris()
        self.data["deltas_confirmes"] = []
        await self.storage.async_sauver(self.data)
        self._notify_entities()

        # Retour utilisateur : l'action efface l'historique d'apprentissage,
        # on le confirme par notification (si des cibles sont configurées).
        await self._notifier(
            "Poêle à granulés",
            (
                "Apprentissage réinitialisé : le delta repart de la base "
                f"({self.convertisseur.delta_pct_vers_niveau(self.apprentissage.delta_un_sac):.1f} "
                "de niveau par sac). Les deltas confirmés sont effacés."
            ),
        )
