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
    CONF_ALPHA_EMA, CONF_FENETRE_STD, CONF_TOLERANCE_MIN,
    CONF_VALEUR_VIDE, CONF_VALEUR_PLEINE,
    DEFAULT_NOTIFY, DEFAULT_SEUIL_BRUIT, DEFAULT_DUREE_STABILISATION,
    DEFAULT_FENETRE_HAUSSE, DEFAULT_ALPHA_EMA, DEFAULT_FENETRE_STD,
    DEFAULT_TOLERANCE_MIN, DEFAULT_VALEUR_VIDE, DEFAULT_VALEUR_PLEINE,
)

STEP_USER_SCHEMA = vol.Schema({
    vol.Required(CONF_SENSOR_NIVEAU): EntitySelector(
        EntitySelectorConfig(domain="sensor")
    ),
    vol.Required(CONF_NOTIFY, default=DEFAULT_NOTIFY): str,
    vol.Required("delta_un_sac", default=8.0): vol.All(
        vol.Coerce(float), vol.Range(min=0.1, max=100)
    ),
    vol.Required(CONF_SACS_INIT, default=0): vol.All(
        vol.Coerce(int), vol.Range(min=0, max=500)
    ),
    # Mesures brutes du capteur aux extrêmes de la cuve. Pour un
    # télémètre, la valeur « cuve vide » est SUPÉRIEURE à « cuve pleine »
    # (plus de granulés = surface plus proche = distance plus courte).
    # Un capteur qui expose déjà un % garde les défauts 100 / 0.
    vol.Required(CONF_VALEUR_VIDE, default=DEFAULT_VALEUR_VIDE): vol.All(
        vol.Coerce(float), vol.Range(min=-10000, max=100000)
    ),
    vol.Required(CONF_VALEUR_PLEINE, default=DEFAULT_VALEUR_PLEINE): vol.All(
        vol.Coerce(float), vol.Range(min=-10000, max=100000)
    ),
})


class PelletTrackerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Flow de configuration : un capteur de niveau par entry."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_VALEUR_VIDE] == user_input[CONF_VALEUR_PLEINE]:
                errors["base"] = "valeurs_identiques"
            else:
                # Un seul tracker par capteur de niveau
                await self.async_set_unique_id(user_input[CONF_SENSOR_NIVEAU])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Suivi granulés",
                    data=user_input,
                    options={
                        CONF_SEUIL_BRUIT: DEFAULT_SEUIL_BRUIT,
                        CONF_DUREE_STABILISATION: DEFAULT_DUREE_STABILISATION,
                        CONF_FENETRE_HAUSSE: DEFAULT_FENETRE_HAUSSE,
                    },
                )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

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
        errors: dict[str, str] = {}
        options = self._config_entry.options
        if user_input is not None:
            if user_input[CONF_VALEUR_VIDE] == user_input[CONF_VALEUR_PLEINE]:
                errors["base"] = "valeurs_identiques"
            else:
                return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema({
                vol.Required(CONF_SEUIL_BRUIT,
                    default=options.get(CONF_SEUIL_BRUIT, DEFAULT_SEUIL_BRUIT)
                ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=10)),
                vol.Required(CONF_DUREE_STABILISATION,
                    default=options.get(CONF_DUREE_STABILISATION, DEFAULT_DUREE_STABILISATION)
                ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                vol.Required(CONF_FENETRE_HAUSSE,
                    default=options.get(CONF_FENETRE_HAUSSE, DEFAULT_FENETRE_HAUSSE)
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
                vol.Optional(CONF_NOTIFY,
                    default=options.get(CONF_NOTIFY, self._config_entry.data.get(CONF_NOTIFY))
                ): str,
                vol.Required(CONF_ALPHA_EMA,
                    default=options.get(CONF_ALPHA_EMA, DEFAULT_ALPHA_EMA)
                ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=1.0)),
                vol.Required(CONF_FENETRE_STD,
                    default=options.get(CONF_FENETRE_STD, DEFAULT_FENETRE_STD)
                ): vol.All(vol.Coerce(int), vol.Range(min=2, max=50)),
                vol.Required(CONF_TOLERANCE_MIN,
                    default=options.get(CONF_TOLERANCE_MIN, DEFAULT_TOLERANCE_MIN)
                ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10)),
                vol.Required(CONF_VALEUR_VIDE,
                    default=options.get(
                        CONF_VALEUR_VIDE,
                        self._config_entry.data.get(CONF_VALEUR_VIDE, DEFAULT_VALEUR_VIDE)
                    )
                ): vol.All(vol.Coerce(float), vol.Range(min=-10000, max=100000)),
                vol.Required(CONF_VALEUR_PLEINE,
                    default=options.get(
                        CONF_VALEUR_PLEINE,
                        self._config_entry.data.get(CONF_VALEUR_PLEINE, DEFAULT_VALEUR_PLEINE)
                    )
                ): vol.All(vol.Coerce(float), vol.Range(min=-10000, max=100000)),
            }),
        )
