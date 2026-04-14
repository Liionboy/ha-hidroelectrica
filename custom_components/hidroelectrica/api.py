"""Client API async pentru comunicarea cu Hidroelectrica România (platforma SEW).

Autentificare în 3 pași:
  1. GetId           → key + tokenId
  2. ValidateUserLogin → UserID + SessionToken  (Basic auth = key:tokenId)
  3. Apeluri post-auth → (Basic auth = UserID:SessionToken, SourceType=1)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from datetime import datetime
from typing import Any

from .const import (
    API_BASE,
    DEFAULT_LANGUAGE,
    ENDPOINT_GET_BILL,
    ENDPOINT_GET_BILLING_HISTORY,
    ENDPOINT_GET_ID,
    ENDPOINT_GET_MASTER_DATA_STATUS,
    ENDPOINT_GET_METER_COUNTER_SERIES,
    ENDPOINT_GET_METER_READ_HISTORY,
    ENDPOINT_GET_METER_VALUE,
    ENDPOINT_GET_MULTI_METER,
    ENDPOINT_GET_PODS,
    ENDPOINT_GET_PREVIOUS_METER_READ,
    ENDPOINT_GET_USAGE,
    ENDPOINT_GET_USER_SETTING,
    ENDPOINT_GET_WINDOW_DATES,
    ENDPOINT_GET_WINDOW_DATES_ENC,
    ENDPOINT_SUBMIT_SELF_METER_READ,
    ENDPOINT_VALIDATE_LOGIN,
    POST_AUTH_HEADERS,
    PRE_AUTH_HEADERS,
)

_LOGGER = logging.getLogger(__name__)


class HidroelectricaApiError(Exception):
    """Eroare generică aruncată de API client."""


class HidroelectricaAuthError(HidroelectricaApiError):
    """Eroare de autentificare (credențiale invalide)."""


class HidroelectricaApiClient:
    """Client async pentru API-ul Hidroelectrica România (SEW platform)."""

    def __init__(
        self,
        username: str,
        password: str,
    ) -> None:
        self._username = username
        self._password = password

        # Stare autentificare
        self._key: str | None = None
        self._token_id: str | None = None
        self._user_id: str | None = None
        self._session_token: str | None = None
        self._token_obtained_at: float = 0.0

        # Lock pentru a preveni login-uri concurente
        self._auth_lock = asyncio.Lock()
        self._token_generation: int = 0

    @property
    def has_token(self) -> bool:
        """Verifică dacă există un session token setat."""
        return self._session_token is not None

    @property
    def token_generation(self) -> int:
        """Generația curentă a token-ului."""
        return self._token_generation

    @property
    def user_id(self) -> str | None:
        """Returnează UserID-ul obținut la autentificare."""
        return self._user_id

    def export_token_data(self) -> dict | None:
        """Exportă datele de autentificare pentru persistență."""
        if self._session_token is None:
            return None
        return {
            "key": self._key,
            "token_id": self._token_id,
            "user_id": self._user_id,
            "session_token": self._session_token,
        }

    def inject_token(self, token_data: dict) -> None:
        """Injectează un token existent."""
        self._key = token_data.get("key")
        self._token_id = token_data.get("token_id")
        self._user_id = token_data.get("user_id")
        self._session_token = token_data.get("session_token")
        self._token_obtained_at = time.monotonic()
        self._token_generation += 1
        _LOGGER.debug("Token injectat (user_id=%s, gen=%s).", self._user_id, self._token_generation)

    def invalidate_session(self) -> None:
        """Invalidează sesiunea curentă."""
        self._session_token = None
        self._token_obtained_at = 0.0

    async def _run_curl(self, method: str, url: str, headers: dict, data: dict | None = None) -> dict:
        """Run curl command and return JSON response. Using curl to bypass JA3/TLS fingerprinting blocks."""
        header_args = []
        for k, v in headers.items():
            header_args.extend(["-H", f"{k}: {v}"])

        cmd = ["curl", "-v", "-X", method, url, "-k", "--silent"]
        cmd.extend(header_args)

        if data is not None:
            cmd.extend(["-d", json.dumps(data)])

        _LOGGER.debug("Running curl command: %s", " ".join(cmd[:10]) + "...")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            err = stderr.decode().strip()
            _LOGGER.error("Curl failed with return code %s: %s", process.returncode, err)
            raise HidroelectricaApiError(f"Curl failed: {err}")

        output = stdout.decode().strip()
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            _LOGGER.error("Failed to decode JSON from curl output: %s", output[:500])
            raise HidroelectricaApiError(f"JSON decode error: {exc}")

    async def async_login(self) -> bool:
        """Autentificare completă în 3 pași."""
        _LOGGER.debug("[LOGIN] Pornire autentificare pentru '%s'.", self._username)

        # ── Pas 1: GetId ──
        resp_id = await self._run_curl(
            method="POST",
            url=f"{API_BASE}{ENDPOINT_GET_ID}",
            headers=PRE_AUTH_HEADERS,
            data={}
        )

        data_id = self._extract_data(resp_id, "GetId")
        self._key = data_id.get("key")
        self._token_id = data_id.get("tokenId")

        if not self._key or not self._token_id:
            raise HidroelectricaApiError("GetId nu a returnat key/tokenId.")

        _LOGGER.debug("[LOGIN] Pas 1 OK: key/tokenId obținuți.")

        # ── Pas 2: ValidateUserLogin ──
        basic_pre = base64.b64encode(f"{self._key}:{self._token_id}".encode()).decode()
        login_headers = {**PRE_AUTH_HEADERS, "Authorization": f"Basic {basic_pre}"}

        login_payload = {
            "deviceType": "MobileApp",
            "OperatingSystem": "Android",
            "UpdatedDate": datetime.now().strftime("%m/%d/%Y %H:%M:%S"),
            "Deviceid": "",
            "SessionCode": "",
            "LanguageCode": DEFAULT_LANGUAGE,
            "password": self._password,
            "UserId": self._username,
            "TFADeviceid": "",
            "OSVersion": 14,
            "TimeOffSet": "120",
            "LUpdHideShow": datetime.now().strftime("%m/%d/%Y %H:%M:%S"),
            "Browser": "NA",
        }

        resp_login = await self._run_curl(
            method="POST",
            url=f"{API_BASE}{ENDPOINT_VALIDATE_LOGIN}",
            headers=login_headers,
            data=login_payload
        )

        data_login = self._extract_data(resp_login, "ValidateUserLogin")
        table = data_login.get("Table", [])
        if not table:
            raise HidroelectricaAuthError("Autentificare eșuată — credențiale invalide sau cont blocat.")

        first_row = table[0]
        self._user_id = first_row.get("UserID", "")
        self._session_token = first_row.get("SessionToken", "")

        if not self._user_id or not self._session_token:
            raise HidroelectricaAuthError("Autentificare eșuată — UserID sau SessionToken lipsă.")

        self._token_obtained_at = time.monotonic()
        self._token_generation += 1

        _LOGGER.debug("[LOGIN] Pas 2 OK: UserID=%s.", self._user_id)
        return True

    async def async_ensure_authenticated(self) -> bool:
        """Asigură că avem o sesiune validă."""
        if self._session_token:
            return True

        async with self._auth_lock:
            if self._session_token:
                return True
            return await self.async_login()

    def _build_auth_headers(self) -> dict[str, str]:
        """Construiește headerele post-autentificare."""
        basic = base64.b64encode(f"{self._user_id}:{self._session_token}".encode()).decode()
        return {**POST_AUTH_HEADERS, "Authorization": f"Basic {basic}"}

    async def _post_auth(self, endpoint: str, payload: dict, label: str = "request") -> dict | None:
        """POST autentificat cu retry automat la 401."""
        await self.async_ensure_authenticated()

        gen_before = self._token_generation
        url = f"{API_BASE}{endpoint}"

        try:
            resp = await self._run_curl(
                method="POST",
                url=url,
                headers=self._build_auth_headers(),
                data=payload
            )

            # Check for error in response if standard format
            if isinstance(resp, dict) and resp.get("status") == 401:
                raise HidroelectricaApiError("401 Unauthorized")

            return resp

        except Exception as exc:
            _LOGGER.warning("[%s] Request failed: %s. Attempting re-login.", label, exc)
            if self._token_generation == gen_before:
                self.invalidate_session()
                try:
                    await self.async_ensure_authenticated()
                    return await self._run_curl(
                        method="POST",
                        url=url,
                        headers=self._build_auth_headers(),
                        data=payload
                    )
                except Exception as retry_exc:
                    _LOGGER.error("[%s] Retry failed: %s", label, retry_exc)
                    return None
            return None

    @staticmethod
    def _extract_data(response: dict, label: str) -> dict:
        """Extrage 'result.Data' din răspunsul SEW standard."""
        try:
            return response["result"]["Data"]
        except (KeyError, TypeError) as exc:
            raise HidroelectricaApiError(f"{label}: Structură răspuns invalidă.") from exc

    async def async_fetch_user_setting(self) -> dict:
        """GetUserSetting — returnează tot JSON-ul brut."""
        payload = {"UserID": self._user_id}
        resp = await self._post_auth(endpoint=ENDPOINT_GET_USER_SETTING, payload=payload, label="GetUserSetting")
        return resp if resp else {}

    async def async_fetch_utility_accounts(self) -> list[dict]:
        """Extrage lista conturilor din GetUserSetting."""
        resp = await self.async_fetch_user_setting()
        data = resp.get("result", {}).get("Data", {})

        accounts: list[dict] = []
        seen: set[str] = set()

        for table_key in ("Table1", "Table2"):
            for entry in data.get(table_key, []) or []:
                uan = entry.get("UtilityAccountNumber", "").strip()
                if uan and uan not in seen:
                    seen.add(uan)
                    accounts.append({
                        "contractAccountID": uan,
                        "accountNumber": entry.get("AccountNumber", ""),
                        "address": entry.get("Address", ""),
                        "pod": entry.get("Pod", ""),
                        "equipmentNo": entry.get("EquipmentNo", ""),
                        "isDefault": entry.get("IsDefaultAccount", False),
                    })
        return accounts

    async def async_fetch_multi_meter(self, utility_account_number: str, account_number: str) -> dict | None:
        """GetMultiMeter — detalii contor(uri) pentru un cont."""
        payload = {
            "MeterType": "E",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_auth(ENDPOINT_GET_MULTI_METER, payload, f"GetMultiMeter({utility_account_number})")

    async def async_fetch_window_dates_enc(self, utility_account_number: str, account_number: str) -> dict | None:
        """GetWindowDatesENC — ferestre autocitire enc."""
        payload = {
            "LanguageCode": DEFAULT_LANGUAGE,
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_auth(ENDPOINT_GET_WINDOW_DATES_ENC, payload, f"GetWindowDatesENC({utility_account_number})")

    async def async_fetch_window_dates(self, utility_account_number: str, account_number: str) -> dict | None:
        """GetWindowDates — ferestre autocitire."""
        payload = {
            "LanguageCode": DEFAULT_LANGUAGE,
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_auth(ENDPOINT_GET_WINDOW_DATES, payload, f"GetWindowDates({utility_account_number})")

    async def async_fetch_meter_counter_series(self, utility_account_number: str, installation_number: str, pod_value: str) -> dict | None:
        """GetMeterCounterSeries — serii contor pentru istoric."""
        payload = {
            "utilityAccountNumber": utility_account_number,
            "InstallationNumber": installation_number,
            "podValue": pod_value,
            "LanguageCode": DEFAULT_LANGUAGE,
        }
        return await self._post_auth(ENDPOINT_GET_METER_COUNTER_SERIES, payload, f"GetMeterCounterSeries({utility_account_number})")

    async def async_fetch_meter_read_history(self, utility_account_number: str, installation_number: str, pod_value: str, serial_numbers: list | None = None) -> dict | None:
        """GetMeterReadHistory — istoric citiri contor."""
        payload = {
            "utilityAccountNumber": utility_account_number,
            "podValue": pod_value,
            "LanguageCode": DEFAULT_LANGUAGE,
            "InstallationNumber": installation_number,
            "SerialNumber": serial_numbers or [],
        }
        return await self._post_auth(ENDPOINT_GET_METER_READ_HISTORY, payload, f"GetMeterReadHistory({utility_account_number})")

    async def async_fetch_pods(self, utility_account_number: str, account_number: str) -> dict | None:
        """GetPods — puncte de livrare pentru autocitire."""
        payload = {
            "MeterType": "E",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_auth(ENDPOINT_GET_PODS, payload, f"GetPods({utility_account_number})")

    async def async_fetch_previous_meter_read(self, utility_account_number: str, installation_number: str = "", pod_value: str = "", customer_number: str = "") -> dict | None:
        """GetPreviousMeterRead — citirea anterioară a contorului."""
        payload = {
            "UtilityAccountNumber": utility_account_number,
            "InstallationNumber": installation_number,
            "podValue": pod_value,
            "LanguageCode": DEFAULT_LANGUAGE,
            "UserID": self._user_id,
            "BasicValue": "",
            "CustomerNumber": customer_number,
            "Distributor": "",
        }
        return await self._post_auth(ENDPOINT_GET_PREVIOUS_METER_READ, payload, f"GetPreviousMeterRead({utility_account_number})")

    async def async_fetch_bill(self, utility_account_number: str, account_number: str) -> dict | None:
        """GetBill — factura curentă."""
        payload = {
            "LanguageCode": DEFAULT_LANGUAGE,
            "UserID": self._user_id,
            "IsBillPDF": "0",
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_auth(ENDPOINT_GET_BILL, payload, f"GetBill({utility_account_number})")

    async def async_fetch_billing_history(self, utility_account_number: str, account_number: str, from_date: str = "", to_date: str = "") -> dict | None:
        """GetBillingHistoryList — istoricul facturilor."""
        payload = {
            "LanguageCode": DEFAULT_LANGUAGE,
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
            "FromDate": from_date,
            "ToDate": to_date,
        }
        return await self._post_auth(ENDPOINT_GET_BILLING_HISTORY, payload, f"GetBillingHistory({utility_account_number})")

    async def async_fetch_usage(self, utility_account_number: str, account_number: str) -> dict | None:
        """GetUsageGeneration — istoric consum/generare."""
        payload = {
            "date": "", "IsCSR": False, "IsUSD": False, "Mode": "M", "HourlyType": "H",
            "UsageType": "e", "UsageOrGeneration": False, "GroupId": 0,
            "LanguageCode": DEFAULT_LANGUAGE, "Type": "D", "MeterNumber": "",
            "IsEnterpriseUser": False, "SeasonType": 0, "DateFromDaily": "",
            "IsNetUsage": False, "TimeOffset": "120", "UserType": "Residential",
            "DateToDaily": "", "UtilityId": 0, "IsLastTendays": False,
            "UserID": self._user_id, "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_auth(ENDPOINT_GET_USAGE, payload, f"GetUsageGeneration({utility_account_number})")
