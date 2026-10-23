"""Entités sensor : niveau %, sacs consommés, sacs restants, calibration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory

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
        # Bloc « Configuration » de l'appareil : calibration saisie
        PelletNiveauBasSensor(coordinator, entry),
        PelletNiveauHautSensor(coordinator, entry),
        PelletDeltaBaseSensor(coordinator, entry),
        # Bloc « Diagnostic » : valeur apprise
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
        self._unsub_update: Any = None

    @property
    def _cle_unique(self) -> str:
        """Suffixe d'unique_id propre à chaque entité."""
        raise NotImplementedError

    async def async_added_to_hass(self) -> None:
        """Abonnement au coordinateur une fois l'entité réellement ajoutée.

        S'abonner dans __init__ laisserait des callbacks morts si l'ajout
        échouait : une mise à jour du coordinateur déclencherait alors
        async_write_ha_state sur une entité sans hass
        (« Attribute hass is None »).
        """
        self._unsub_update = self.coordinator.on_update(self._on_update)
        # Calcul immédiat : les valeurs apparaissent sans attendre le
        # premier changement d'état du capteur.
        self._on_update()

    async def async_will_remove_from_hass(self) -> None:
        """Désabonnement : le coordinateur ne garde pas de référence morte."""
        if self._unsub_update is not None:
            self._unsub_update()
            self._unsub_update = None

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
    """Sacs consommés : total COMPTÉ (remplissages constatés), persistant."""
    _attr_name = "Sacs consommés"
    _attr_native_unit_of_measurement = "sacs"
    _attr_state_class = SensorStateClass.TOTAL  # une correction peut faire baisser le total

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


class _PelletConfigSensor(_PelletSensor):
    """Base des entités de configuration : valeur saisie, visible sur
    l'appareil dans le bloc « Configuration » (lecture seule — la saisie
    se fait dans les options de l'intégration)."""

    _attr_entity_category = EntityCategory.CONFIG


class PelletNiveauBasSensor(_PelletConfigSensor):
    """Valeur du capteur correspondant à la cuve VIDE (niveau bas)."""
    _attr_name = "Niveau bas (cuve vide)"
    _attr_icon = "mdi:arrow-collapse-down"

    @property
    def _cle_unique(self) -> str:
        return "niveau_bas"

    def _calcul(self) -> float:
        return self.coordinator.convertisseur.valeur_vide


class PelletNiveauHautSensor(_PelletConfigSensor):
    """Valeur du capteur correspondant à la cuve PLEINE (niveau haut)."""
    _attr_name = "Niveau haut (cuve pleine)"
    _attr_icon = "mdi:arrow-collapse-up"

    @property
    def _cle_unique(self) -> str:
        return "niveau_haut"

    def _calcul(self) -> float:
        return self.coordinator.convertisseur.valeur_pleine


class PelletDeltaBaseSensor(_PelletConfigSensor):
    """Delta d'un sac de base (niveau brut), tel que configuré."""
    _attr_name = "Delta d'un sac (base)"
    _attr_icon = "mdi:counter"

    @property
    def _cle_unique(self) -> str:
        return "delta_base"

    def _calcul(self) -> float:
        return self.coordinator.delta_initial


class PelletDeltaUnSacSensor(_PelletSensor):
    """Delta de NIVEAU appris pour un sac : suivi de la calibration en direct.

    Permet de surveiller la dérive de l'apprentissage EMA (et de détecter
    une calibration polluée par de mauvaises confirmations) directement
    depuis l'interface, sans ouvrir le .storage.
    """
    _attr_name = "Delta d'un sac (appris)"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:ruler"
    _attr_entity_category = EntityCategory.DIAGNOSTIC  # lecture seule : valeur apprise

    @property
    def _cle_unique(self) -> str:
        return "delta_un_sac"

    def _calcul(self) -> float:
        # La valeur interne est en % : restituée en niveau brut (l'unité
        # dans laquelle l'utilisateur a saisi la base).
        return self.coordinator.convertisseur.delta_pct_vers_niveau(
            self.coordinator.apprentissage.delta_un_sac
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Diagnostic de l'apprentissage : tolérance, deltas, base d'origine."""
        apprentissage = self.coordinator.apprentissage
        return {
            "tolerance_niveau": self.coordinator.convertisseur.delta_pct_vers_niveau(
                apprentissage.tolerance()
            ),
            "deltas_confirmes": len(apprentissage.deltas_confirmes),
            "delta_base": self.coordinator.delta_initial,
        }
