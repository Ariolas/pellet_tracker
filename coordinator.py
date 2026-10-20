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
    CONF_TOLERANCE_MIN,
    DEFAULT_SEUIL_BRUIT, DEFAULT_DUREE_STABILISATION,
    DEFAULT_FENETRE_HAUSSE, DEFAULT_ALPHA_EMA, DEFAULT_FENETRE_STD,
    DEFAULT_TOLERANCE_MIN, DEFAULT_DELTA_UN_SAC,
    EVENT_MOBILE_APP_ACTION, ACTION_CONFIRM, ACTION_CANCEL,
)
from .detector import (
    ApprentissageAdaptatif, Decision, DetecteurRemplissage,
    Etat, EvenementRemplissage, ResultatRemplissage,
)
from .storage import PelletStorage

_LOGGER = logging.getLogger(__name__)


class PelletCoordinator:
    """Centralise toute la logique de suivi pour une config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.storage = PelletStorage(hass, entry.entry_id)

        # Paramètres de la config entry (avec valeurs par défaut)
        self.notify_target = entry.options.get(CONF_NOTIFY, entry.data.get(CONF_NOTIFY))
        seuil_bruit = entry.options.get(CONF_SEUIL_BRUIT, DEFAULT_SEUIL_BRUIT)
        duree_stab = entry.options.get(CONF_DUREE_STABILISATION, DEFAULT_DUREE_STABILISATION)
        fenetre_hausse = entry.options.get(CONF_FENETRE_HAUSSE, DEFAULT_FENETRE_HAUSSE)
        alpha = entry.options.get(CONF_ALPHA_EMA, DEFAULT_ALPHA_EMA)
        fenetre_std = entry.options.get(CONF_FENETRE_STD, DEFAULT_FENETRE_STD)
        tolerance_min = entry.options.get(CONF_TOLERANCE_MIN, DEFAULT_TOLERANCE_MIN)
        delta_initial = entry.data.get("delta_un_sac", DEFAULT_DELTA_UN_SAC)

        self.data: dict[str, Any] = {}
        self.apprentissage = ApprentissageAdaptatif(
            delta_un_sac=delta_initial,
            alpha=alpha,
            fenetre_std=fenetre_std,
            tolerance_min=tolerance_min,
        )
        self.detecteur = DetecteurRemplissage(
            delta_un_sac=delta_initial,
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
                self.detecteur.traiter_mesure(float(etat_capteur.state), time.time())
            except ValueError:
                pass
        _LOGGER.info("pellet_tracker actif, capteur écouté : %s", capteur)

    async def async_unload(self) -> None:
        self._gerer_timer_annulation()
        for off in self._listeners:
            off()
        self._listeners.clear()
        # Les entités sont déjà déchargées à ce stade : on lâche leurs callbacks
        self._update_callbacks.clear()

    # -------------------------------------------------- entités (rAF pattern)
    @callback
    def on_update(self, cb: Any) -> None:
        """Enregistre un callback d'actualisation d'entité."""
        self._update_callbacks.append(cb)

    @callback
    def _notify_entities(self) -> None:
        for cb in self._update_callbacks:
            cb()

    # -------------------------------------------------- écoute du capteur
    @callback
    def _on_capteur(self, event: Event) -> None:
        """Chaque changement d'état du capteur alimente la machine à états."""
        ancien: Optional[State] = event.data.get("old_state")
        nouveau: Optional[State] = event.data.get("new_state")
        if nouveau is None or nouveau.state in ("unknown", "unavailable"):
            return
        try:
            niveau = float(nouveau.state)
        except ValueError:
            return

        maintenant = time.time()
        ancien_niveau = float(ancien.state) if ancien and ancien.state not in ("unknown", "unavailable") else niveau
        variation = niveau - ancien_niveau

        # --- Suivi de la consommation (baisse hors remplissage) ---
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
        """Historise un remplissage confirmé et applique la décision."""
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
            "delta": evenement.delta,
            "decision": evenement.decision.value,
            "niveau_avant": evenement.niveau_avant,
            "niveau_apres": evenement.niveau_apres,
            "confirme": evenement.confirme,
        }

        if evenement.decision == Decision.AUTO:
            # delta ≈ 1 sac → comptage automatique + apprentissage
            self._compter_sac(source="auto")
            self.apprentissage.confirmer(evenement.delta)
            self._persister_delta_appris()
            ev_dict["confirme"] = True
            self.data["evenements"].append(ev_dict)
            self.hass.async_create_task(self._sauver_et_notifier(evenement, auto=True))
        elif evenement.decision == Decision.PARTIEL:
            # delta partiel → notification avec boutons Oui / Non
            action_id = f"pellet_{secrets.token_hex(4)}"
            self.data["attente_confirmation"] = {
                "action_id": action_id,
                "delta": evenement.delta,
                "timestamp": maintenant,
                # Index de l'événement concerné dans l'historique : la
                # réponse ne doit marquer que cet événement, même si
                # d'autres sont ajoutés entre-temps.
                "evenement_index": len(self.data["evenements"]),
            }
            self.data["evenements"].append(ev_dict)
            self.hass.async_create_task(self._notifier_partiel(evenement, action_id))
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

    async def _sauver_et_notifier(self, evenement: EvenementRemplissage, auto: bool) -> None:
        await self.storage.async_sauver(self.data)
        if self.notify_target:
            await self.hass.services.async_call(
                "notify",
                self.notify_target.removeprefix("notify."),
                {
                    "title": "Poêle à granulés",
                    "message": (
                        f"Remplissage détecté : +{evenement.delta:.1f}% "
                        f"(≈ 1 sac) compté automatiquement."
                        if auto else
                        f"Remplissage confirmé : +{evenement.delta:.1f}%."
                    ),
                },
                blocking=True,
            )

    async def _notifier_partiel(self, evenement: EvenementRemplissage, action_id: str) -> None:
        """Notification avec boutons « Oui, 1 sac » / « Non »."""
        await self.storage.async_sauver(self.data)
        if not self.notify_target:
            _LOGGER.warning("Aucun service notify configuré pour la confirmation")
            return
        await self.hass.services.async_call(
            "notify",
            self.notify_target.removeprefix("notify."),
            {
                "title": "Poêle à granulés : remplissage partiel",
                "message": (
                    f"Hausse de {evenement.delta:.1f}% détectée "
                    f"(≈ {evenement.delta / max(self.apprentissage.delta_un_sac, 0.1):.1f} sac). "
                    "Compter 1 sac ?"
                ),
                "data": {
                    "tag": action_id,
                    "actions": [
                        {"action": f"{ACTION_CONFIRM}:{action_id}", "title": "Oui, 1 sac"},
                        {"action": f"{ACTION_CANCEL}:{action_id}", "title": "Non"},
                    ],
                },
            },
            blocking=True,
        )

    @callback
    def on_notification_action(self, event: Event) -> None:
        """Gère la réponse aux boutons (event mobile_app_notification_action)."""
        action: str = event.data.get("action", "")
        if not action.startswith((ACTION_CONFIRM, ACTION_CANCEL)):
            return
        _, _, action_id = action.partition(":")
        attente = self.data.get("attente_confirmation")
        if not attente or attente["action_id"] != action_id:
            return  # réponse périmée ou déjà traitée
        self.data["attente_confirmation"] = None
        index = attente.get("evenement_index")
        evenements = self.data.get("evenements", [])
        if index is not None and 0 <= index < len(evenements):
            # Trace la réponse de l'utilisateur sur l'événement correspondant
            evenements[index]["confirme"] = action.startswith(ACTION_CONFIRM)
        if action.startswith(ACTION_CONFIRM):
            delta = attente["delta"]
            self._compter_sac(source="confirmation")
            # Confirmation utilisateur → apprentissage sur ce delta partiel
            self.apprentissage.confirmer(delta)
            self._persister_delta_appris()
            _LOGGER.info("Remplissage partiel confirmé (+%.2f%%) → 1 sac compté", delta)
        else:
            _LOGGER.info("Remplissage partiel refusé par l'utilisateur")
        self.hass.async_create_task(self.storage.async_sauver(self.data))
        self._notify_entities()

    # -------------------------------------------------- données calculées
    @property
    def sacs_consommes(self) -> float:
        """Sacs consommés estimés : % cumulé consommé / % par sac."""
        delta = max(self.apprentissage.delta_un_sac, 0.1)
        return round(self.data.get("niveau_consome_pct", 0.0) / delta, 2)

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
        """Service pellet_tracker.reset_learning : repart de la calibration."""
        self.apprentissage.reinitialiser(delta_un_sac or self.entry.data.get("delta_un_sac", DEFAULT_DELTA_UN_SAC))
        self._persister_delta_appris()
        self.data["deltas_confirmes"] = []
        await self.storage.async_sauver(self.data)
        self._notify_entities()
