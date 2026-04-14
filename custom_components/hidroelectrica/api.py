"""Client API pentru Hidroelectrica (iHidro)."""

import base64
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp

from .const import (
    API_BASE_URL,
    API_PATH_GET_BILL,
    API_PATH_GET_BILL_HISTORY,
    API_PATH_GET_ID,
    API_PATH_GET_METER_READ_HISTORY,
    API_PATH_GET_PODS,
    API_PATH_GET_USAGE_GENERATION,
    API_PATH_GET_USER_SETTING,
    API_PATH_VALIDATE_LOGIN,
    HEADERS,
)

_LOGGER = logging.getLogger(__name__)


class HidroelectricaAPI:
    """Clasă pentru interacțiunea cu API-ul iHidro."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
    ) -> None:
        """Inițializare."""
        self._session = session
        self._username = username
        self._password = password
        self._user_id: Optional[str] = None
        self._session_token: Optional[str] = None
        self._auth_header: Optional[Dict[str, str]] = None

    def _safe_get(self, data: Any, path: List[str], default: Any = None) -> Any:
        """Extragere sigură de date dintr-o structură ierarhică JSON."""
        if not isinstance(data, dict):
            # iHidro uneori returnează liste sau erori direct
            if isinstance(data, list) and not path:
                return data
            return default
        
        current = data
        for key in path:
            if isinstance(current, dict):
                current = current.get(key, {})
            else:
                return default
        
        # Dacă am ajuns la final și valoarea este {} (de la .get), returnăm default
        if current == {} and (isinstance(default, list) or default is None):
             return default
        return current

    async def login(self) -> bool:
        """Autentificare la iHidro."""
        try:
            # Pasul 1: GetId pentru a genera key și tokenId
            async with self._session.post(
                f"{API_BASE_URL}{API_PATH_GET_ID}",
                json={},
                headers=HEADERS,
            ) as resp:
                if resp.status != 200:
                    _LOGGER.error("Eroare GetId: %s", resp.status)
                    return False
                res = await resp.json()
                data = self._safe_get(res, ["result", "Data"], {})
                key = data.get("key")
                token_id = data.get("tokenId")

            if not key or not token_id:
                _LOGGER.error("Nu am putut obține key sau tokenId")
                return False

            # Pasul 2: ValidateUserLogin
            auth_str = f"{key}:{token_id}"
            encoded_auth = base64.b64encode(auth_str.encode()).decode()
            
            login_headers = {
                **HEADERS,
                "Authorization": f"Basic {encoded_auth}",
            }
            
            login_payload = {
                "deviceType": "HomeAssistant",
                "LanguageCode": "RO",
                "password": self._password,
                "UserId": self._username,
            }

            async with self._session.post(
                f"{API_BASE_URL}{API_PATH_VALIDATE_LOGIN}",
                json=login_payload,
                headers=login_headers,
            ) as resp:
                if resp.status != 200:
                    _LOGGER.error("Eroare login: %s", resp.status)
                    return False
                res = await resp.json()
                table = self._safe_get(res, ["result", "Data", "Table"], [])
                if not table or not isinstance(table, list):
                    _LOGGER.error("Login eșuat: date invalide sau sesiune expirată")
                    return False
                
                self._user_id = table[0].get("UserID")
                self._session_token = table[0].get("SessionToken")

            if not self._user_id or not self._session_token:
                return False

            # Setăm header-ul final de autentificare
            final_auth = f"{self._user_id}:{self._session_token}"
            encoded_final = base64.b64encode(final_auth.encode()).decode()
            self._auth_header = {
                **HEADERS,
                "Authorization": f"Basic {encoded_final}",
            }
            
            _LOGGER.info("Autentificare reușită pentru %s", self._username)
            return True

        except Exception as err:
            _LOGGER.error("Excepție în timpul login-ului: %s", err)
            return False

    async def get_accounts(self) -> List[Dict[str, Any]]:
        """Obține lista de conturi (POD-uri)."""
        if not self._auth_header:
            return []
        
        payload = {"UserID": self._user_id}
        async with self._session.post(
            f"{API_BASE_URL}{API_PATH_GET_USER_SETTING}",
            json=payload,
            headers=self._auth_header,
        ) as resp:
            if resp.status != 200:
                return []
            res = await resp.json()
            data = self._safe_get(res, ["result", "Data"], {})
            # Combinăm Table1 și Table2 (uneori POD-urile sunt splituite)
            table1 = data.get("Table1", []) if isinstance(data, dict) else []
            table2 = data.get("Table2", []) if isinstance(data, dict) else []
            accounts = (table1 or []) + (table2 or [])
            # Eliminăm duplicatele după UtilityAccountNumber
            seen = set()
            unique_accounts = []
            for acc in accounts:
                if not isinstance(acc, dict):
                    continue
                uan = acc.get("UtilityAccountNumber")
                if uan and uan not in seen:
                    seen.add(uan)
                    unique_accounts.append(acc)
            return unique_accounts

    async def get_current_bill(self, uan: str, account_number: str) -> Optional[Dict[str, Any]]:
        """Obține datele facturii curente."""
        if not self._auth_header:
            return None
        
        payload = {
            "LanguageCode": "RO",
            "UserID": self._user_id,
            "IsBillPDF": "0",
            "UtilityAccountNumber": uan,
            "AccountNumber": account_number,
        }
        async with self._session.post(
            f"{API_BASE_URL}{API_PATH_GET_BILL}",
            json=payload,
            headers=self._auth_header,
        ) as resp:
            if resp.status != 200:
                return None
            res = await resp.json()
            table = self._safe_get(res, ["result", "Data", "Table"], [])
            return table[0] if table and isinstance(table, list) else None

    async def get_bill_history(self, uan: str, account_number: str) -> List[Dict[str, Any]]:
        """Obține istoricul facturilor."""
        if not self._auth_header:
            return []
        
        # Luăm istoricul pe ultimul an
        to_date = datetime.now().strftime("%m/%d/%Y")
        from_date = datetime.now().replace(year=datetime.now().year - 1).strftime("%m/%d/%Y")
        
        payload = {
            "LanguageCode": "RO",
            "UserID": self._user_id,
            "UtilityAccountNumber": uan,
            "AccountNumber": account_number,
            "FromDate": from_date,
            "ToDate": to_date,
        }
        async with self._session.post(
            f"{API_BASE_URL}{API_PATH_GET_BILL_HISTORY}",
            json=payload,
            headers=self._auth_header,
        ) as resp:
            if resp.status != 200:
                return []
            res = await resp.json()
            table = self._safe_get(res, ["result", "Data", "Table"], [])
            return table if isinstance(table, list) else []

    async def get_usage(self, uan: str, account_number: str) -> Optional[Dict[str, Any]]:
        """Obține consumul."""
        if not self._auth_header:
            return None
        
        payload = {
            "Mode": "M",
            "UsageOrGeneration": False,
            "LanguageCode": "RO",
            "UserID": self._user_id,
            "UtilityAccountNumber": uan,
            "AccountNumber": account_number,
        }
        async with self._session.post(
            f"{API_BASE_URL}{API_PATH_GET_USAGE_GENERATION}",
            json=payload,
            headers=self._auth_header,
        ) as resp:
            if resp.status != 200:
                return None
            res = await resp.json()
            data = self._safe_get(res, ["result", "Data"], {})
            return data if isinstance(data, dict) else None

    async def get_meter_history(self, uan: str) -> List[Dict[str, Any]]:
        """Obține istoricul indicilor contorului."""
        if not self._auth_header:
            return []
        
        # Mai întâi avem nevoie de InstallationNumber și podValue din GetPods
        pods_payload = {
            "MeterType": "E",
            "UserID": self._user_id,
            "UtilityAccountNumber": uan,
            "AccountNumber": "", # Se poate lăsa gol
        }
        
        async with self._session.post(
            f"{API_BASE_URL}{API_PATH_GET_PODS}",
            json=pods_payload,
            headers=self._auth_header,
        ) as resp:
            if resp.status != 200:
                return []
            res = await resp.json()
            pods = self._safe_get(res, ["result", "Data", "Table"], [])
            if not pods or not isinstance(pods, list):
                return []
            
            inst_id = pods[0].get("installation")
            pod_val = pods[0].get("pod")

        history_payload = {
            "utilityAccountNumber": uan,
            "podValue": pod_val,
            "LanguageCode": "RO",
            "InstallationNumber": inst_id,
            "SerialNumber": [],
        }

        async with self._session.post(
            f"{API_BASE_URL}{API_PATH_GET_METER_READ_HISTORY}",
            json=history_payload,
            headers=self._auth_header,
        ) as resp:
            if resp.status != 200:
                return []
            res = await resp.json()
            table = self._safe_get(res, ["result", "Data", "Table"], [])
            return table if isinstance(table, list) else []
