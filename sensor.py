"""Entités sensor : niveau %, sacs consommés, sacs restants."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_SACS_INIT, DOMAIN
from .coordinator import PelletCoordinator
from .__init__ import PelletConfigEntry


def _device_info(entry: PelletConfigEntry) -> DeviceInfo:
    """Appareil commun : regroupe toutes les entités de l'entry."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
    )


async def async_setup_entry(hass, entry: PelletConfigEntry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    async_add_entities([
        PelletNiveauSensor(coordinator, entry),
        PelletSacsConsommesSensor(coordinator, entry),
        PelletSacsRestantsSensor(coordinator, entry),
        PelletDeltaUnSacSensor(coordinator, entry),
    ])


class _PelletSensor(SensorEntity):
    """Base commune : actualisation sur callback du coordinateur."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: PelletCoordinator, entry: PelletConfigEntry) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_{self._cle_unique}"
        self._attr_device_info = _device_info(entry)
        self._attr_native_value = None
        coordinator.on_update(self._on_update)

    @property
    def _cle_unique(self) -> str:
        """Suffixe d'unique_id propre à chaque entité."""
        raise NotImplementedError

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

    @property
    def _cle_unique(self) -> str:
        return "niveau"

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
        super().__init__(coordinator, entry)
        self._sacs_init = entry.data.get(CONF_SACS_INIT, 0)

    @property
    def _cle_unique(self) -> str:
        return "sacs_consommes"

    def _calcul(self) -> float | None:
        # Consommation estimée + sacs initiaux déclarés au lancement
        return round(self._sacs_init + self.coordinator.sacs_consommes, 2)


class PelletSacsRestantsSensor(_PelletSensor):
    """Autonomie estimée en nombre de sacs."""
    _attr_name = "Sacs restants estimés"
    _attr_native_unit_of_measurement = "sacs"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def _cle_unique(self) -> str:
        return "sacs_restants"

    def _calcul(self) -> float | None:
        restants = self.coordinator.sacs_restants
        return round(restants, 2) if restants is not None else None


class PelletDeltaUnSacSensor(_PelletSensor):
    """Delta % appris pour un sac : suivi de la calibration en direct.

    Permet de surveiller la dérive de l'apprentissage EMA (et de détecter
    une calibration polluée par de mauvaises confirmations) directement
    depuis l'interface, sans ouvrir le .storage.
    """
    _attr_name = "Delta d'un sac (appris)"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:tune"

    @property
    def _cle_unique(self) -> str:
        return "delta_un_sac"

    def _calcul(self) -> float | None:
        return round(self.coordinator.apprentissage.delta_un_sac, 3)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Diagnostic de l'apprentissage : tolérance, deltas, calibration d'origine."""
        apprentissage = self.coordinator.apprentissage
        return {
            "tolerance_pct": apprentissage.tolerance(),
            "deltas_confirmes": len(apprentissage.deltas_confirmes),
            "delta_initial": self.coordinator.entry.data.get("delta_un_sac"),
        }
