"""Bouton : envoyer une notification de test sur les cibles configurées."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import PelletCoordinator
from .__init__ import PelletConfigEntry


async def async_setup_entry(hass, entry: PelletConfigEntry, async_add_entities) -> None:
    async_add_entities([
        PelletTesterNotificationButton(entry.runtime_data, entry),
        PelletResetLearningButton(entry.runtime_data, entry),
    ])


class PelletTesterNotificationButton(ButtonEntity):
    """Envoie une notification de test aux appareils sélectionnés.

    Utile juste après la configuration pour vérifier que les cibles de
    notification choisies (sélection multiple) reçoivent bien les
    messages de l'intégration.
    """

    _attr_name = "Tester la notification"
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:bell-badge"

    def __init__(self, coordinator: PelletCoordinator, entry: PelletConfigEntry) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_test_notification"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
        )

    async def async_press(self) -> None:
        await self.coordinator.async_test_notification()


class PelletResetLearningButton(ButtonEntity):
    """Réinitialise l'apprentissage du delta d'un sac.

    Avertissements d'usage : efface les deltas confirmés (la tolérance
    adaptative repart de zéro) et réinitialise le delta appris au delta
    de base. À utiliser après un remplacement de capteur, un changement
    d'unité ou une recalibration des bornes niveau bas / niveau haut —
    pas en cours de routine. Le retour se fait par notification
    (si des cibles sont configurées).
    """

    _attr_name = "Réinitialiser l'apprentissage"
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:restart-alert"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: PelletCoordinator, entry: PelletConfigEntry) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_reset_learning"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
        )

    async def async_press(self) -> None:
        await self.coordinator.async_reset_learning()
