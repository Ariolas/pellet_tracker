"""Intégration pellet_tracker : suivi de consommation de granulés."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.event import async_track_event

from .const import (
    DOMAIN, PLATFORMS, EVENT_MOBILE_APP_ACTION,
    SERVICE_ADD_BAG, SERVICE_RESET_COUNTER, SERVICE_RESET_LEARNING,
)
from .coordinator import PelletCoordinator

_LOGGER = logging.getLogger(__name__)

# --- Schémas des services ---
SCHEMA_ADD_BAG = vol.Schema(
    {vol.Optional("nombre", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=50))}
)
SCHEMA_RESET_LEARNING = vol.Schema(
    {vol.Optional("delta_un_sac"): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=100))}
)

# Type retourné par async_setup_entry (API moderne)
type PelletConfigEntry = ConfigEntry[PelletCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: PelletConfigEntry) -> bool:
    """Installation d'une instance de l'intégration (une par capteur)."""
    coordinator = PelletCoordinator(hass, entry)
    await coordinator.async_setup()
    entry.runtime_data = coordinator

    # Écoute des réponses aux notifications mobiles (boutons Oui/Non)
    unsub_action = async_track_event(hass, EVENT_MOBILE_APP_ACTION, coordinator.on_notification_action)

    # Enregistrement des services (une seule fois pour le domaine)
    _register_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entry.async_on_unload(unsub_action)
    entry.async_on_unload(coordinator.async_unload)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info("pellet_tracker configuré pour %s", entry.data.get("sensor_niveau"))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PelletConfigEntry) -> bool:
    """Déchargement propre d'une config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: PelletConfigEntry) -> None:
    """Rechargement de l'entry quand les options changent."""
    await hass.config_entries.async_reload(entry.entry_id)


@callback
def _register_services(hass: HomeAssistant) -> None:
    """Enregistre les services du domaine (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_ADD_BAG):
        return

    def _coordinator() -> PelletCoordinator:
        # Une seule entry attendue ; sinon on prend la première active
        entries = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.state == "loaded" and not e.disabled_by
        ]
        return entries[0].runtime_data

    async def _add_bag(call: ServiceCall) -> None:
        await _coordinator().async_add_bag(call.data.get("nombre", 1))

    async def _reset_counter(call: ServiceCall) -> None:
        await _coordinator().async_reset_counter()

    async def _reset_learning(call: ServiceCall) -> None:
        await _coordinator().async_reset_learning(call.data.get("delta_un_sac"))

    hass.services.async_register(DOMAIN, SERVICE_ADD_BAG, _add_bag, SCHEMA_ADD_BAG)
    hass.services.async_register(DOMAIN, SERVICE_RESET_COUNTER, _reset_counter)
    hass.services.async_register(DOMAIN, SERVICE_RESET_LEARNING, _reset_learning, SCHEMA_RESET_LEARNING)