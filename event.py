"""Event entity : dernier remplissage VALIDÉ par l'utilisateur."""
from __future__ import annotations

from typing import Any, Optional

from homeassistant.components.event import EventEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import PelletCoordinator
from .__init__ import PelletConfigEntry


async def async_setup_entry(hass, entry: PelletConfigEntry, async_add_entities) -> None:
    async_add_entities([PelletDernierRemplissage(entry.runtime_data, entry)])


class PelletDernierRemplissage(EventEntity):
    """Se déclenche uniquement quand un sac est VALIDÉ.

    Réponses qui déclenchent : Acquitter (comptage auto confirmé),
    Sac complet, Fin de sac. Une correction, un sac partiel ou une
    notification sans réponse ne déclenchent jamais : l'état reflète
    la date du dernier sac réellement utilisé, pas les détections
    (un faux positif corrigé ne pollue pas la date).
    """

    _attr_name = "Dernier remplissage"
    _attr_has_entity_name = True
    _attr_event_types = [f"{DOMAIN}_remplissage"]

    def __init__(self, coordinator: PelletCoordinator, entry: PelletConfigEntry) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_dernier_remplissage"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
        )
        self._attr_event_type = None
        self._attr_event_attributes: dict[str, Any] | None = None
        self._dernier_ts: float | None = None  # anti-doublon : timestamp du dernier event émis
        # Restauration du dernier remplissage validé (sans le re-émettre)
        dernier = coordinator.dernier_remplissage_valide
        if dernier:
            self._dernier_ts = dernier.get("timestamp")
            self._attr_event_type = f"{DOMAIN}_remplissage"
            self._attr_event_attributes = self._attributs(dernier)
        self._unsub_update: Any = None

    async def async_added_to_hass(self) -> None:
        """Abonnement au coordinateur une fois l'entité réellement ajoutée.

        S'abonner dans __init__ laisserait des callbacks morts si l'ajout
        échouait : une mise à jour du coordinateur déclencherait alors
        async_write_ha_state sur une entité sans hass
        (« Attribute hass is None »).
        """
        self._unsub_update = self.coordinator.on_update(self._on_update)

    async def async_will_remove_from_hass(self) -> None:
        """Désabonnement : le coordinateur ne garde pas de référence morte."""
        if self._unsub_update is not None:
            self._unsub_update()
            self._unsub_update = None

    def _attributs(self, dernier: dict) -> dict[str, Any]:
        """Attributs de l'événement, en niveau brut comme à la saisie."""
        return {
            "delta_pct": dernier.get("delta"),
            "delta_niveau": self.coordinator.convertisseur.delta_pct_vers_niveau(
                dernier.get("delta") or 0.0
            ),
            "decision": str(dernier.get("decision")),
            "reponse": dernier.get("reponse") or "prevalide",  # None = prévalidé (acquittement en attente)
            "niveau_avant": dernier.get("niveau_avant"),
            "niveau_apres": dernier.get("niveau_apres"),
            "rempli_le": dernier.get("rempli_le"),
        }

    def _on_update(self) -> None:
        dernier = self.coordinator.dernier_remplissage_valide
        if not dernier:
            return
        attrs = self._attributs(dernier)
        if (dernier.get("timestamp") or 0) > (self._dernier_ts or 0):
            # NOUVEAU remplissage : prévalidé à la détection AUTO, ou
            # validé par Sac complet / Fin de sac → déclenchement de l'event.
            self._trigger_event(f"{DOMAIN}_remplissage", attrs)
        elif attrs != self._attr_event_attributes:
            # Même remplissage (acquittement) ou ANNULATION de prévalidation
            # (Correction : retour à la date précédente) : état mis à jour
            # silencieusement, SANS re-déclencher l'event (les automations
            # ne voient pas de faux remplissage).
            self.async_write_ha_state()
        self._dernier_ts = dernier.get("timestamp")
        self._attr_event_attributes = attrs
