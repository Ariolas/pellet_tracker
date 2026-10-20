"""Config flow : sélection du capteur + calibration initiale + options."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow, ConfigFlowResult, OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector, EntitySelectorConfig,
)

from .const import (
    DOMAIN, CONF_SENSOR_NIVEAU, CONF_NOTIFY, CONF_SEUIL_BRUIT,
    CONF_DUREE_STABILISATION, CONF_FENETRE_HAUSSE, CONF_SACS_INIT,
)

STEP_USER_SCHEMA = vol.Schema({
    vol.Required(CONF_SENSOR_NIVEAU): EntitySelector(
        EntitySelectorConfig(domain="sensor")
    ),
    vol.Required(CONF_NOTIFY, default="notify.mobile_app_mon_tel"): str,
    vol.Required("delta_un_sac", default=8.0): vol.All(
        vol.Coerce(float), vol.Range(min=0.1, max=100)
    ),
    vol.Required(CONF_SACS_INIT, default=0): vol.All(
        vol.Coerce(int), vol.Range(min=0, max=500)
    ),
})


class PelletTrackerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Flow de configuration : un capteur de niveau par entry."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            # Un seul tracker par capteur de niveau
            await self.async_set_unique_id(user_input[CONF_SENSOR_NIVEAU])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Suivi granulés",
                data=user_input,
                options={
                    CONF_SEUIL_BRUIT: 1.5,
                    CONF_DUREE_STABILISATION: 180,
                    CONF_FENETRE_HAUSSE: 120,
                },
            )
        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return PelletTrackerOptionsFlow(config_entry)


class PelletTrackerOptionsFlow(OptionsFlow):
    """Options : seuils de détection ajustables après calibration terrain."""

    def __init__(self, config_entry) -> None:
        # API moderne : l'entry est passée au constructeur (self.config_entry
        # est déprécié dans les versions récentes de HA)
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_SEUIL_BRUIT,
                    default=self._config_entry.options.get(CONF_SEUIL_BRUIT, 1.5)
                ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=10)),
                vol.Required(CONF_DUREE_STABILISATION,
                    default=self._config_entry.options.get(CONF_DUREE_STABILISATION, 180)
                ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                vol.Required(CONF_FENETRE_HAUSSE,
                    default=self._config_entry.options.get(CONF_FENETRE_HAUSSE, 120)
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
            }),
        )