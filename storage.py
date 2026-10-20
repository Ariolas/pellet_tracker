"""Persistance des données de l'intégration.

Utilise `homeassistant.helpers.storage.Store`, qui écrit dans
`<config>/.storage/pellet_tracker/<entry_id>` (JSON) et gère la migration
de version. Restauré à chaque démarrage de HA → compteur et apprentissage
survivent aux redémarrages.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_VERSION = 1
_MAX_EVENEMENTS = 200  # historique borné pour rester léger

_LOGGER = logging.getLogger(__name__)


class PelletStorage:
    """Chargeur / sauvegarde de l'état persistant d'une entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store[dict[str, Any]](hass, _VERSION, f"pellet_tracker/{entry_id}")

    async def async_charger(self) -> dict[str, Any]:
        """Charge l'état ou retourne l'état initial par défaut."""
        data = await self._store.async_load()
        if data is None:
            data = {
                "sacs_ajoutes": 0,       # compteur cumulatif de sacs ajoutés
                "sacs_manuels": 0,        # sacs comptés manuellement (service)
                "sacs_confirmes": 0,      # sacs comptés après confirmation mobile
                "niveau_consome_pct": 0.0,  # % consommé cumulé (baisses)
                "delta_un_sac": None,      # None → valeur de config au 1er lancement
                "deltas_confirmes": [],
                "evenements": [],          # historique des remplissages
                "attente_confirmation": None,  # notification en attente (delta, ts)
            }
        return data

    async def async_sauver(self, data: dict[str, Any]) -> None:
        """Sauvegarde l'état (tronque l'historique si besoin)."""
        if len(data.get("evenements", [])) > _MAX_EVENEMENTS:
            data["evenements"] = data["evenements"][-_MAX_EVENEMENTS:]
        await self._store.async_save(data)
        _LOGGER.debug("État pellet_tracker sauvegardé (%d événements)", len(data["evenements"]))
