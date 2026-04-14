"""Inițializarea integrării Hidroelectrica România."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import HidroelectricaApiClient
from .const import (
    CONF_ACCOUNT_METADATA,
    CONF_PASSWORD,
    CONF_SELECTED_ACCOUNTS,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import HidroelectricaCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class HidroelectricaRuntimeData:
    """Structură tipizată pentru datele runtime ale integrării."""

    coordinators: dict[str, HidroelectricaCoordinator] = field(default_factory=dict)
    api_client: HidroelectricaApiClient | None = None


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Configurează integrarea globală Hidroelectrica România."""
    _LOGGER.debug("Inițializare globală integrare: %s", DOMAIN)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configurează integrarea pentru o intrare specifică (config entry)."""
    _LOGGER.info("Se configurează integrarea %s (entry_id=%s).", DOMAIN, entry.entry_id)

    hass.data.setdefault(DOMAIN, {})

    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    update_interval = entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)

    # Conturi selectate
    selected_accounts = entry.data.get(CONF_SELECTED_ACCOUNTS, [])
    if not selected_accounts:
        _LOGGER.error("Nu există conturi selectate pentru %s (entry_id=%s).", DOMAIN, entry.entry_id)
        return False

    # Un singur client API partajat per entry (un set de credențiale)
    api_client = HidroelectricaApiClient(username, password)

    # Injectăm token-ul salvat (persistent, pentru restart HA)
    if entry.data.get("token_data"):
        api_client.inject_token(entry.data["token_data"])
        _LOGGER.debug("Token injectat din config_entry.data pentru %s.", username)

    # Metadatele conturilor
    account_metadata = entry.data.get(CONF_ACCOUNT_METADATA, {})

    # Creăm câte un coordinator per cont selectat
    coordinators: dict[str, HidroelectricaCoordinator] = {}

    for uan in selected_accounts:
        meta = account_metadata.get(uan, {})
        acc_number = meta.get("accountNumber", "")

        _LOGGER.info("Inițializare coordinator UAN=%s, AccountNumber='%s'.", uan, acc_number)

        coordinator = HidroelectricaCoordinator(
            hass,
            api_client=api_client,
            uan=uan,
            account_number=acc_number,
            update_interval=update_interval,
            config_entry=entry,
        )

        try:
            await coordinator.async_config_entry_first_refresh()
        except UpdateFailed as err:
            _LOGGER.error("Prima actualizare eșuată (UAN=%s): %s", uan, err)
            continue
        except Exception as err:
            _LOGGER.exception("Eroare neașteptată la prima actualizare (UAN=%s): %s", uan, err)
            continue

        coordinators[uan] = coordinator

    if not coordinators:
        _LOGGER.error("Niciun coordinator inițializat cu succes.")
        return False

    # Salvăm datele runtime
    entry.runtime_data = HidroelectricaRuntimeData(
        coordinators=coordinators,
        api_client=api_client,
    )

    # Încărcăm platformele
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listener pentru modificarea opțiunilor
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reîncarcă integrarea când opțiunile se schimbă."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descărcarea integrării."""
    _LOGGER.info("Se descarcă integrarea %s (entry_id=%s).", DOMAIN, entry.entry_id)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrare de la versiuni vechi la versiunea curentă (v3)."""
    _LOGGER.debug("Migrare config entry %s de la versiunea %s.", config_entry.entry_id, config_entry.version)

    if config_entry.version < 3:
        old_data = dict(config_entry.data)
        new_data = {
            CONF_USERNAME: old_data.get(CONF_USERNAME, old_data.get("username", "")),
            CONF_PASSWORD: old_data.get(CONF_PASSWORD, old_data.get("password", "")),
            CONF_UPDATE_INTERVAL: old_data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            CONF_SELECTED_ACCOUNTS: old_data.get(CONF_SELECTED_ACCOUNTS, []),
            CONF_ACCOUNT_METADATA: old_data.get(CONF_ACCOUNT_METADATA, {}),
        }

        if old_data.get("token_data"):
            new_data["token_data"] = old_data["token_data"]

        hass.config_entries.async_update_entry(config_entry, data=new_data, options={}, version=3)
        return True

    return False
