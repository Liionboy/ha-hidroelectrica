import asyncio
import logging
import json
import base64
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from .const import (
    API_BASE_URL,
    API_PATH_GET_ID,
    API_PATH_VALIDATE_LOGIN,
    API_PATH_GET_USER_SETTING,
    API_PATH_GET_BILL,
    API_PATH_GET_BILL_HISTORY,
    API_PATH_GET_USAGE_GENERATION,
    API_PATH_GET_METER_READ_HISTORY,
)

_LOGGER = logging.getLogger(__name__)

class HidroelectricaAPI:
    """Client API pentru iHidro folosind curl.exe ca workaround pentru JA3 bypass."""

    def __init__(self, session, username, password) -> None:
        # Păstrăm session pentru compatibilitate, deși folosim curl
        self._session = session
        self._username = username
        self._password = password
        self._user_id: Optional[str] = None
        self._session_token: Optional[str] = None
        self._auth_lock = asyncio.Lock()
        self._headers: Dict[str, str] = {}

    async def login(self) -> bool:
        """Autentificare la API iHidro folosind curl wrapper."""
        async with self._auth_lock:
            try:
                _LOGGER.debug("Începem procesul de login (curl wrapper) pentru %s", self._username)
                
                # Pasul 1: GetId
                headers_pre = {
                    "SourceType": "0",
                    "User-Agent": "okhttp/4.9.1",
                    "Accept": "*/*"
                }
                resp_id = await self._run_curl(API_PATH_GET_ID, {}, headers_pre)
                
                if not resp_id or "result" not in resp_id:
                    _LOGGER.error("Răspuns GetId invalid: %s", resp_id)
                    return False
                    
                data = resp_id["result"].get("Data", {})
                key = data.get("key")
                token_id = data.get("tokenId")
                
                if not key or not token_id:
                    _LOGGER.error("Nu am primit key sau tokenId de la GetId")
                    return False

                # Pasul 2: ValidateUserLogin
                auth_val = base64.b64encode(f"{key}:{token_id}".encode()).decode()
                headers_login = {
                    **headers_pre,
                    "Authorization": f"Basic {auth_val}"
                }
                
                login_payload = {
                    "deviceType": "HomeAssistant",
                    "OperatingSystem": "Linux",
                    "UpdatedDate": datetime.now().strftime("%m/%d/%Y %H:%M:%S"),
                    "Deviceid": "",
                    "SessionCode": "",
                    "LanguageCode": "RO",
                    "password": self._password,
                    "UserId": self._username,
                    "TFADeviceid": "",
                    "OSVersion": 14,
                    "TimeOffSet": "120",
                    "LUpdHideShow": datetime.now().strftime("%m/%d/%Y %H:%M:%S"),
                    "Browser": "HomeAssistant",
                }
                
                resp_login = await self._run_curl(API_PATH_VALIDATE_LOGIN, login_payload, headers_login)
                
                if not resp_login or resp_login.get("result", {}).get("Status") != 1:
                    msg = resp_login.get("result", {}).get("Message", "Eroare necunoscută la login")
                    _LOGGER.error("Login eșuat: %s", msg)
                    return False
                
                login_data = resp_login["result"]["Data"]["Table"][0]
                self._user_id = login_data.get("UserID")
                self._session_token = login_data.get("SessionToken")
                
                if not self._user_id or not self._session_token:
                    _LOGGER.error("UserID sau SessionToken lipsă din răspuns")
                    return False

                _LOGGER.debug("Login reușit. UserID: %s", self._user_id)
                
                # Header pentru cererile viitoare
                auth_token = base64.b64encode(f"{self._user_id}:{self._session_token}".encode()).decode()
                self._headers = {
                    "SourceType": "1",
                    "User-Agent": "okhttp/4.9.1",
                    "Authorization": f"Basic {auth_token}",
                    "Accept": "*/*"
                }
                
                return True
            except Exception as err:
                _LOGGER.exception("Excepție în timpul procesului de login: %s", err)
                return False

    async def get_accounts(self) -> List[Dict[str, Any]]:
        """Obține lista de conturi."""
        if not self._user_id:
            return []
            
        resp = await self._run_curl(API_PATH_GET_USER_SETTING, {"UserID": self._user_id}, self._headers)
        data = resp.get("result", {}).get("Data", {})
        
        accounts = []
        if "Table1" in data and data["Table1"]:
            accounts.extend(data["Table1"])
        if "Table2" in data and data["Table2"]:
            for item in data["Table2"]:
                if not any(a.get("UtilityAccountNumber") == item.get("UtilityAccountNumber") for a in accounts):
                    accounts.append(item)
                    
        return accounts

    async def get_current_bill(self, uan: str, acc_num: str) -> Optional[Dict[str, Any]]:
        """Ultima factură."""
        payload = {
            "LanguageCode": "RO",
            "UserID": self._user_id,
            "IsBillPDF": "0",
            "UtilityAccountNumber": uan,
            "AccountNumber": acc_num,
        }
        resp = await self._run_curl(API_PATH_GET_BILL, payload, self._headers)
        table = resp.get("result", {}).get("Data", {}).get("Table", [])
        return table[0] if table else None

    async def get_meter_history(self, uan: str) -> List[Dict[str, Any]]:
        """Istoric citiri."""
        payload = {"utilityAccountNumber": uan, "LanguageCode": "RO"}
        resp = await self._run_curl(API_PATH_GET_METER_READ_HISTORY, payload, self._headers)
        return resp.get("result", {}).get("Data", {}).get("Table", [])

    async def get_usage(self, uan: str, acc_num: str) -> List[Dict[str, Any]]:
        """Consum istoric."""
        payload = {
            "Mode": "M",
            "LanguageCode": "RO",
            "UserID": self._user_id,
            "UtilityAccountNumber": uan,
            "AccountNumber": acc_num,
            "UsageOrGeneration": False,
        }
        resp = await self._run_curl(API_PATH_GET_USAGE_GENERATION, payload, self._headers)
        return resp.get("result", {}).get("Data", {}).get("Table", [])

    async def _run_curl(self, path: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        """Wrapper pentru curl.exe care ocolește protecția TLS a Python."""
        url = f"{API_BASE_URL}{path}"
        
        args = ["curl.exe", "-s", "-X", "POST", url, "-H", "Content-Type: application/json"]
        for k, v in headers.items():
            args.extend(["-H", f"{k}: {v}"])
        
        args.extend(["-d", json.dumps(payload)])
        
        _LOGGER.debug("Executăm curl la %s", path)
        
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            err_msg = stderr.decode().strip()
            _LOGGER.error("Curl failed for %s: %s", path, err_msg)
            return {}
            
        output = stdout.decode().strip()
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            _LOGGER.error("Răspuns non-JSON de la %s: %s", path, output)
            return {}
