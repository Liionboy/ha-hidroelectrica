"""Constante pentru integrarea Hidroelectrica România."""

from typing import Final

from homeassistant.const import Platform

DOMAIN = "hidroelectrica"
DOMAIN_TOKEN_STORE = f"{DOMAIN}_token_store"  # Cheie în hass.data pentru token-uri SEW

# ──────────────────────────────────────────────
DEFAULT_UPDATE_INTERVAL = 3600  # Interval de actualizare în secunde (1 oră)
MIN_UPDATE_INTERVAL = 300       # 5 minute
MAX_UPDATE_INTERVAL = 86400     # 24 ore

# ──────────────────────────────────────────────
API_TIMEOUT = 15

# ──────────────────────────────────────────────
DEFAULT_LANGUAGE = "RO"

# ──────────────────────────────────────────────
# Pre-auth headers (GetId, ValidateUserLogin, GetUserSetting)
PRE_AUTH_HEADERS = {
    "SourceType": "0",
    "Content-Type": "application/json",
    "Host": "hidroelectrica-svc.smartcmobile.com",
    "User-Agent": "okhttp/4.9.0",
}

# ──────────────────────────────────────────────
# Post-auth headers (Service calls)
POST_AUTH_HEADERS = {
    "SourceType": "1",
    "Content-Type": "application/json",
    "Host": "hidroelectrica-svc.smartcmobile.com",
    "User-Agent": "okhttp/4.9.0",
}

# ──────────────────────────────────────────────
API_BASE = "https://ihidro.ro"

# ──────────────────────────────────────────────
ENDPOINT_GET_ID = "/API/UserLogin/GetId"
ENDPOINT_VALIDATE_LOGIN = "/API/UserLogin/ValidateUserLogin"
ENDPOINT_GET_USER_SETTING = "/API/UserLogin/GetUserSetting"
ENDPOINT_GET_MASTER_DATA_STATUS = "/API/UserLogin/GetMasterDataStatus"

# ──────────────────────────────────────────────
ENDPOINT_GET_MULTI_METER = "/Service/Usage/GetMultiMeter"
ENDPOINT_GET_USAGE = "/Service/Usage/GetUsageGeneration"

# ──────────────────────────────────────────────
ENDPOINT_GET_WINDOW_DATES_ENC = "/Service/SelfMeterReading/GetWindowDatesENC"
ENDPOINT_GET_WINDOW_DATES = "/Service/SelfMeterReading/GetWindowDates"
ENDPOINT_GET_PODS = "/Service/SelfMeterReading/GetPods"
ENDPOINT_GET_METER_VALUE = "/Service/SelfMeterReading/GetMeterValue"
ENDPOINT_GET_PREVIOUS_METER_READ = "/Service/SelfMeterReading/GetPreviousMeterRead"
ENDPOINT_SUBMIT_SELF_METER_READ = "/Service/SelfMeterReading/SubmitSelfMeterRead"

# ──────────────────────────────────────────────
ENDPOINT_GET_BILL = "/Service/Billing/GetBill"
ENDPOINT_GET_BILLING_HISTORY = "/Service/Billing/GetBillingHistoryList"

# ──────────────────────────────────────────────
ENDPOINT_GET_METER_COUNTER_SERIES = "/Service/IndexHistory/GetMeterCounterSeries"
ENDPOINT_GET_METER_READ_HISTORY = "/Service/IndexHistory/GetMeterReadHistory"

# ──────────────────────────────────────────────
PLATFORMS: list[Platform] = [Platform.SENSOR]

# ──────────────────────────────────────────────
ATTRIBUTION = "Date furnizate de Hidroelectrica România"

# ──────────────────────────────────────────────
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_SELECTED_ACCOUNTS = "selected_accounts"
CONF_ACCOUNT_METADATA = "account_metadata"
