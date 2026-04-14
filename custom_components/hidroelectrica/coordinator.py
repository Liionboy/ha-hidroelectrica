"""DataUpdateCoordinator for Hidroelectrica integration."""

import logging
from datetime import timedelta
from typing import Any, Dict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HidroelectricaAPI
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class HidroelectricaDataUpdateCoordinator(DataUpdateCoordinator):
    """Clasă pentru gestionarea actualizărilor de date de la Hidroelectrica."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: HidroelectricaAPI,
        update_interval: timedelta,
    ) -> None:
        """Inițializare coordinator."""
        self.api = api
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from API."""
        try:
            # Asigurăm autentificarea (login-ul se face o singură dată sau re-login dacă e nevoie)
            # În mod real, ar trebui să verificăm dacă token-ul e valid, 
            # dar pentru simplitate încercăm login-ul dacă nu avem auth_header.
            if not self.api._auth_header:
                if not await self.api.login():
                    raise UpdateFailed("Autentificare eșuată")

            # 1. Obținem conturile (POD-urile)
            accounts = await self.api.get_accounts()
            if not accounts:
                _LOGGER.warning("Nu am găsit conturi Hidroelectrica")
                return {}

            data = {}
            for acc in accounts:
                uan = acc.get("UtilityAccountNumber")
                acc_num = acc.get("AccountNumber")
                
                if not uan:
                    continue

                # 2. Obținem factura curentă
                bill = await self.api.get_current_bill(uan, acc_num)
                
                # 3. Obținem istoricul indicilor pentru a extrage ultimul index
                meter_history = await self.api.get_meter_history(uan)
                
                # Creăm un dicționar cu ultimele citiri pentru fiecare RegisterCode
                # iHidro trimite de obicei o listă în care cele mai recente sunt la început.
                registers = {}
                if meter_history:
                    for entry in meter_history:
                        reg_code = entry.get("RegisterCode")
                        if reg_code and reg_code not in registers:
                            registers[reg_code] = entry

                # 4. Obținem datele de consum (usage)
                usage = await self.api.get_usage(uan, acc_num)

                data[uan] = {
                    "account_info": acc,
                    "bill": bill,
                    "meter": registers.get("1.8.0") or registers.get("1.8.1") or (meter_history[0] if meter_history else {}),
                    "registers": registers,
                    "meter_history": meter_history,
                    "usage": usage,
                }

            return data

        except Exception as err:
            _LOGGER.exception("Eroare la actualizarea datelor: %s", err)
            raise UpdateFailed(f"Eroare comunicare API: {err}") from err
