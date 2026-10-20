"""Event entity : dernier événement de remplissage (delta, décision)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import PelletCoordinator
from .__init__ import PelletConfigEntry


async def async_setup_entry(hass, entry: PelletConfigEntry, async_add_entities) -> None:
    async_add_entities([PelletDernierRemplissage(entry.runtime_data, entry)])


class PelletDernierRemplissage(EventEntity):
    """Émet un event à chaque remplissage confirmé ; l'état conserve
    la date et les attributs le détail (delta, décision, niveaux)."""

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
        # Restauration du dernier événement persisté (sans le re-émettre)
        dernier = coordinator.dernier_evenement
        if dernier:
            self._dernier_ts = dernier.get("timestamp")
            self._attr_event_type = f"{DOMAIN}_remplissage"
            self._attr_event_attributes = dernier
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

    def _on_update(self) -> None:
        dernier = self.coordinator.dernier_evenement
        # Ne déclencher que pour un NOUVEL événement : sinon chaque mesure de
        # consommation re-émettrait indéfiniment le même event
        if not dernier or dernier.get("timestamp") == self._dernier_ts:
            return
        self._dernier_ts = dernier["timestamp"]
        self._trigger_event(
            f"{DOMAIN}_remplissage",
            {
                "delta_pct": dernier["delta"],
                "delta_niveau": self.coordinator.convertisseur.delta_pct_vers_niveau(
                    dernier["delta"]
                ),
                "decision": str(dernier["decision"]),
                "niveau_avant": dernier["niveau_avant"],
                "niveau_apres": dernier["niveau_apres"],
                "confirme": dernier.get("confirme"),
            },
        )
        self.async_write_ha_state()
