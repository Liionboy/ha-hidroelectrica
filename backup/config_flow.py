"""Config flow for Hidroelectrica integration."""

import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HidroelectricaAPI
from .const import CONF_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class HidroelectricaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hidroelectrica."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.FlowResult:
        """Handle the initial step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                session = async_get_clientsession(self.hass)
                api = HidroelectricaAPI(
                    session,
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
                
                if await api.login():
                    return self.async_create_entry(
                        title=f"iHidro ({user_input[CONF_USERNAME]})",
                        data=user_input,
                    )
                else:
                    errors["base"] = "invalid_auth"
            except Exception: # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
