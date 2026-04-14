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
                
                # Căutăm ultimul index de consum (1.8.0) și injecție (2.8.0 / 1.8.0_P)
                # iHidro trimite de obicei o listă, primul element fiind cel mai recent.
                latest_reading = {}
                if meter_history:
                    # Sortăm (just in case) după dată descrescător dacă există câmp de dată
                    # De obicei vin deja sortate.
                    latest_reading = meter_history[0]

                data[uan] = {
                    "account_info": acc,
                    "bill": bill,
                    "meter": latest_reading,
                    "meter_history": meter_history,
                }

            return data

        except Exception as err:
            _LOGGER.exception("Eroare la actualizarea datelor: %s", err)
            raise UpdateFailed(f"Eroare comunicare API: {err}") from err
