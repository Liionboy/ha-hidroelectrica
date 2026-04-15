"""DataUpdateCoordinator pentru integrarea Hidroelectrica România.

Strategia de actualizare:
- Refresh ușor (light):  endpoint-uri esențiale — bill, multi_meter, window_dates
- Refresh greu (heavy, la fiecare al 4-lea): + usage, billing_history, meter_read_history
- Datele grele se reutilizează între refresh-urile ușoare
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import HidroelectricaApiClient, HidroelectricaApiError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

HEAVY_REFRESH_EVERY = 4


class HidroelectricaCoordinator(DataUpdateCoordinator):
    """Coordinator pentru datele Hidroelectrica — per cont (UAN)."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: HidroelectricaApiClient,
        uan: str,
        account_number: str,
        update_interval: int,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"HidroelectricaCoordinator_{uan}",
            update_interval=timedelta(seconds=update_interval),
        )

        self.api_client = api_client
        self.uan = uan
        self.account_number = account_number
        self._config_entry = config_entry
        self._refresh_counter: int = 0
        # Salvăm generația token-ului la creare
        self._startup_gen: int = api_client.token_generation

    @property
    def _is_heavy_refresh(self) -> bool:
        """Determină dacă refresh-ul curent este „greu"."""
        return self._refresh_counter % HEAVY_REFRESH_EVERY == 0

    async def _async_update_data(self) -> dict:
        """Obține date de la API cu strategie light/heavy."""
        uan = self.uan
        acc = self.account_number
        is_heavy = self._is_heavy_refresh

        _LOGGER.debug(
            "Actualizare Hidroelectrica (UAN=%s, AccountNumber='%s', refresh=#%s, tip=%s).",
            uan, acc, self._refresh_counter, "HEAVY" if is_heavy else "light",
        )

        if not acc:
            _LOGGER.warning("AccountNumber GOL pentru UAN=%s! Se încearcă obținerea din API...", uan)
            try:
                await self.api_client.async_ensure_authenticated()
                fresh_accounts = await self.api_client.async_fetch_utility_accounts()
                for fa in fresh_accounts:
                    if fa.get("contractAccountID", "").strip() == uan:
                        acc = fa.get("accountNumber", "").strip()
                        if acc:
                            self.account_number = acc
                            _LOGGER.info("AccountNumber obținut din API: '%s' (UAN=%s).", acc, uan)
                        break
            except Exception as err:
                _LOGGER.error("Eroare la obținerea AccountNumber din API (UAN=%s): %s", uan, err)

        try:
            # Re-autentificare preventivă la startup
            if self._refresh_counter == 0 and self._startup_gen == self.api_client.token_generation:
                _LOGGER.debug("Primul refresh — forțez login proaspăt (UAN=%s).", uan)
                self.api_client.invalidate_session()
                await self.api_client.async_ensure_authenticated()
            elif not self.api_client.has_token:
                await self.api_client.async_ensure_authenticated()

            # Faza 1: Request-uri paralele esențiale
            essential_phase1 = [
                self.api_client.async_fetch_multi_meter(uan, acc),
                self.api_client.async_fetch_bill(uan, acc),
                self.api_client.async_fetch_window_dates_enc(uan, acc),
                self.api_client.async_fetch_window_dates(uan, acc),
                self.api_client.async_fetch_pods(uan, acc),
            ]

            (
                multi_meter,
                bill,
                window_dates_enc,
                window_dates,
                pods,
            ) = await asyncio.gather(*essential_phase1)

            # Extragere InstallationNumber / podValue din GetPods
            installation_number = ""
            pod_value = ""
            customer_number = ""

            if pods and isinstance(pods, dict):
                pods_data = pods.get("result", {}).get("Data", [])
                if isinstance(pods_data, list) and pods_data:
                    first_pod = pods_data[0]
                    installation_number = str(first_pod.get("installation", first_pod.get("InstallationNumber", "")))
                    pod_value = str(first_pod.get("pod", first_pod.get("podValue", "")))
                    customer_number = str(first_pod.get("accountID", ""))

            # Faza 2: GetPreviousMeterRead (depinde de Pods)
            previous_meter_read = await self.api_client.async_fetch_previous_meter_read(
                uan,
                installation_number=installation_number,
                pod_value=pod_value,
                customer_number=customer_number,
            )

            # Endpoint-uri GRELE (doar la heavy refresh)
            prev = self.data or {}
            if is_heavy:
                end_date = datetime.now()
                start_date = end_date - timedelta(days=2 * 365)
                from_date = start_date.strftime("%Y-%m-%d")
                to_date = end_date.strftime("%Y-%m-%d")

                heavy_tasks = [
                    self.api_client.async_fetch_usage(uan, acc),
                    self.api_client.async_fetch_billing_history(uan, acc, from_date, to_date),
                    self.api_client.async_fetch_meter_counter_series(uan, installation_number, pod_value),
                    self.api_client.async_fetch_meter_read_history(uan, installation_number, pod_value),
                ]

                (usage, billing_history, meter_counter_series, meter_read_history) = await asyncio.gather(*heavy_tasks)
            else:
                usage = prev.get("usage")
                billing_history = prev.get("billing_history")
                meter_counter_series = prev.get("meter_counter_series")
                meter_read_history = prev.get("meter_read_history")

        except HidroelectricaApiError as err:
            _LOGGER.error("Eroare API la actualizarea datelor (UAN=%s): %s", uan, err)
            raise UpdateFailed(f"Eroare API Hidroelectrica: {err}") from err
        except Exception as err:
            _LOGGER.exception("Eroare neașteptată la actualizarea datelor (UAN=%s): %s", uan, err)
            raise UpdateFailed("Eroare neașteptată la actualizarea datelor Hidroelectrica.") from err

        # Persistăm token-ul
        self._persist_token()

        result = {
            "multi_meter": multi_meter,
            "bill": bill,
            "window_dates_enc": window_dates_enc,
            "window_dates": window_dates,
            "pods": pods,
            "previous_meter_read": previous_meter_read,
            "usage": usage,
            "billing_history": billing_history,
            "meter_counter_series": meter_counter_series,
            "meter_read_history": meter_read_history,
        }

        # Validare minimală: bill este esențial
        if bill is None:
            _LOGGER.error(
                "Datele esențiale lipsesc după refresh (UAN=%s): bill=%s. "
                "Se va reîncerca la următorul interval.",
                uan, bill,
            )
            raise UpdateFailed(
                f"Datele esențiale lipsesc după refresh (UAN={uan})"
            )

        # Incrementăm contorul doar la succes
        self._refresh_counter += 1

        _LOGGER.debug(
            "Actualizare completă (UAN=%s, refresh=#%s): bill=%s, pods=%s, usage=%s.",
            uan, self._refresh_counter,
            "OK" if bill else "LIPSĂ",
            "OK" if pods else "LIPSĂ",
            "OK" if usage else "LIPSĂ/refolosit",
        )

        return result

    def _persist_token(self) -> None:
        """Persistă token-ul curent în config_entry.data (pentru restart HA)."""
        if self._config_entry is None:
            return
        token_data = self.api_client.export_token_data()
        if token_data is None:
            return

        current_data = dict(self._config_entry.data)
        current_data["token_data"] = token_data
        self.hass.config_entries.async_update_entry(self._config_entry, data=current_data)
        _LOGGER.debug("Token persistat în config_entry (UAN=%s).", self.uan)
