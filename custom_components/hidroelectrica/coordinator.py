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
            _LOGGER.debug("Procesare %s conturi", len(accounts))
            
            for acc in accounts:
                uan = acc.get("UtilityAccountNumber")
                acc_num = acc.get("AccountNumber")
                
                if not uan or not acc_num:
                    _LOGGER.warning("Cont ignorat (lipsă UAN sau AccountNumber): %s", acc)
                    continue

                _LOGGER.debug("Preluare date pentru UAN: %s, Account: %s", uan, acc_num)
                
                # Preluăm datele în paralel pentru eficiență
                results = await asyncio.gather(
                    self.api.get_current_bill(uan, acc_num),
                    self.api.get_usage(uan, acc_num),
                    self.api.get_meter_history(uan),
                    return_exceptions=True
                )
                
                bill = results[0] if not isinstance(results[0], Exception) else None
                usage = results[1] if not isinstance(results[1], Exception) else None
                meter_history = results[2] if not isinstance(results[2], Exception) else []

                if isinstance(results[0], Exception):
                    _LOGGER.error("Eroare bill %s: %s", uan, results[0])
                if isinstance(results[1], Exception):
                    _LOGGER.warning("Eroare usage %s: %s", uan, results[1])
                if isinstance(results[2], Exception):
                    _LOGGER.error("Eroare history %s: %s", uan, results[2])

                _LOGGER.debug("Istoric contor pentru %s: %s intrări", uan, len(meter_history))
                
                # Creăm un dicționar cu ultimele citiri pentru fiecare RegisterCode
                registers = {}
                if meter_history and isinstance(meter_history, list):
                    for entry in meter_history:
                        if not isinstance(entry, dict):
                            continue
                        reg_code = entry.get("RegisterCode")
                        if reg_code and reg_code not in registers:
                            registers[reg_code] = entry

                data[uan] = {
                    "account_info": acc,
                    "bill": bill,
                    "meter": registers.get("1.8.0") or registers.get("1.8.1") or (meter_history[0] if meter_history else {}),
                    "registers": registers,
                    "meter_history": meter_history,
                    "usage": usage,
                }

            _LOGGER.debug("Update finalizat pentru %s POD-uri", len(data))
            return data

        except Exception as err:
            _LOGGER.exception("Eroare la actualizarea datelor: %s", err)
            raise UpdateFailed(f"Eroare comunicare API: {err}") from err
