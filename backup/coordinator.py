"""DataUpdateCoordinator for Hidroelectrica integration."""

import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict, List

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
            # Asigurăm autentificarea
            if not self.api._user_id:
                _LOGGER.debug("Nu avem UserID, încercăm login...")
                if not await self.api.login():
                    raise UpdateFailed("Autentificare la iHidro eșuată")

            # 1. Obținem conturile (POD-urile)
            accounts = await self.api.get_accounts()
            if not accounts:
                _LOGGER.warning("Nu am găsit conturi Hidroelectrica active")
                # Încercăm un re-login în caz că sesiunea a expirat silentios
                if await self.api.login():
                    accounts = await self.api.get_accounts()
                
                if not accounts:
                    return {}

            data = {}
            _LOGGER.debug("Procesare %s conturi iHidro", len(accounts))
            
            for acc in accounts:
                uan = acc.get("UtilityAccountNumber")
                acc_num = acc.get("AccountNumber")
                
                if not uan:
                    _LOGGER.warning("Cont ignorat (lipsă UtilityAccountNumber): %s", acc)
                    continue

                _LOGGER.debug("Preluare date pentru UAN: %s", uan)
                
                # Preluăm datele în paralel pentru eficiență
                # Notă: acc_num poate fi None pentru unele endpoint-uri, dar GetBill îl cere
                results = await asyncio.gather(
                    self.api.get_current_bill(uan, acc_num or ""),
                    self.api.get_usage(uan, acc_num or ""),
                    self.api.get_meter_history(uan),
                    return_exceptions=True
                )
                
                bill = results[0] if not isinstance(results[0], Exception) else None
                usage = results[1] if not isinstance(results[1], Exception) else None
                meter_history = results[2] if not isinstance(results[2], Exception) else []

                if isinstance(results[0], Exception):
                    _LOGGER.error("Eroare la preluarea facturii pentru %s: %s", uan, results[0])
                if isinstance(results[1], Exception):
                    _LOGGER.warning("Eroare la preluarea consumului pentru %s: %s", uan, results[1])
                if isinstance(results[2], Exception):
                    _LOGGER.error("Eroare la preluarea istoricului de contor pentru %s: %s", uan, results[2])

                # Register logic
                registers = {}
                active_meter = {}
                if meter_history and isinstance(meter_history, list):
                    for entry in meter_history:
                        if not isinstance(entry, dict):
                            continue
                        reg_code = entry.get("RegisterCode")
                        if reg_code:
                            # Păstrăm prima intrare (cea mai recentă) pentru fiecare cod
                            if reg_code not in registers:
                                registers[reg_code] = entry
                    
                    # Determinăm registrul principal (de obicei 1.8.0 pentru consum total)
                    active_meter = registers.get("1.8.0") or registers.get("1.8.1") or (meter_history[0] if meter_history else {})

                data[uan] = {
                    "account_info": acc,
                    "bill": bill,
                    "meter": active_meter,
                    "registers": registers,
                    "meter_history": meter_history,
                    "usage": usage,
                }

            _LOGGER.debug("Actualizare finalizată pentru %s puncte de consum", len(data))
            return data

        except Exception as err:
            _LOGGER.exception("Eroare critică la actualizarea datelor iHidro: %s", err)
            raise UpdateFailed(f"Eroare comunicare iHidro (via curl): {err}") from err
