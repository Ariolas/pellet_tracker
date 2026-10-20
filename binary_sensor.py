"""Binary sensor : remplissage en cours (machine à états non en veille)."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass, BinarySensorEntity,
)
from .coordinator import PelletCoordinator
from .__init__ import PelletConfigEntry


async def async_setup_entry(hass, entry: PelletConfigEntry, async_add_entities) -> None:
    async_add_entities([PelletRemplissageEnCours(entry.runtime_data)])


class PelletRemplissageEnCours(BinarySensorEntity):
    """ON tant que la machine à états détecte une hausse en cours."""

    _attr_name = "Remplissage en cours"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY  # neutre
    _attr_should_poll = False

    def __init__(self, coordinator: PelletCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_is_on = False
        coordinator.on_update(self._on_update)

    def _on_update(self) -> None:
        self._attr_is_on = self.coordinator.detecteur.remplissage_en_cours
        self.async_write_ha_state()