"""Config flow for Hidroelectrica integration."""

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD

from .api import HidroelectricaApiClient
from .const import (
    CONF_USERNAME,
    DOMAIN,
    CONF_SELECTED_ACCOUNTS,
    CONF_ACCOUNT_METADATA,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class HidroelectricaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hidroelectrica."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Nu permite configurarea aceluiași cont de două ori
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()

            try:
                api = HidroelectricaApiClient(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
                
                if await api.async_login():
                    accounts = await api.async_fetch_utility_accounts()
                    
                    selected_accounts = []
                    account_metadata = {}
                    
                    for acc in accounts:
                        uan = acc.get("contractAccountID")
                        if uan:
                            selected_accounts.append(uan)
                            account_metadata[uan] = acc

                    user_input[CONF_SELECTED_ACCOUNTS] = selected_accounts
                    user_input[CONF_ACCOUNT_METADATA] = account_metadata
                    user_input["token_data"] = api.export_token_data()

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
