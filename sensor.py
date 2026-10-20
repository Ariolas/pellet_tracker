"""Entités sensor : niveau %, sacs consommés, sacs restants."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorStateClass,
)
from homeassistant.const import PERCENTAGE

from .const import CONF_SACS_INIT
from .coordinator import PelletCoordinator
from .__init__ import PelletConfigEntry


async def async_setup_entry(hass, entry: PelletConfigEntry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    async_add_entities([
        PelletNiveauSensor(coordinator),
        PelletSacsConsommesSensor(coordinator, entry),
        PelletSacsRestantsSensor(coordinator, entry),
    ])


class _PelletSensor(SensorEntity):
    """Base commune : actualisation sur callback du coordinateur."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: PelletCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_native_value = None
        coordinator.on_update(self._on_update)

    def _on_update(self) -> None:
        self._attr_native_value = self._calcul()
        self.async_write_ha_state()

    def _calcul(self) -> Any:
        raise NotImplementedError


class PelletNiveauSensor(_PelletSensor):
    """Miroir enrichi du niveau de remplissage (%)."""
    _attr_name = "Niveau de remplissage"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY  # % avec icône adaptée
    _attr_state_class = SensorStateClass.MEASUREMENT

    def _calcul(self) -> float | None:
        # `is not None` : un niveau de 0 % est une valeur valide (cuve vide)
        niveau = self.coordinator.detecteur.niveau_actuel
        return round(niveau, 1) if niveau is not None else None


class PelletSacsConsommesSensor(_PelletSensor):
    """Nombre de sacs consommés (compteur cumulatif, persistant)."""
    _attr_name = "Sacs consommés"
    _attr_native_unit_of_measurement = "sacs"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: PelletCoordinator, entry: PelletConfigEntry) -> None:
        super().__init__(coordinator)
        self._sacs_init = entry.data.get(CONF_SACS_INIT, 0)

    def _calcul(self) -> float | None:
        # Consommation estimée + sacs initiaux déclarés au lancement
        return round(self._sacs_init + self.coordinator.sacs_consommes, 2)


class PelletSacsRestantsSensor(_PelletSensor):
    """Autonomie estimée en nombre de sacs."""
    _attr_name = "Sacs restants estimés"
    _attr_native_unit_of_measurement = "sacs"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def _calcul(self) -> float | None:
        restants = self.coordinator.sacs_restants
        return round(restants, 2) if restants is not None else None