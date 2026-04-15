"""Constante pentru Hidroelectrica integration."""

DOMAIN = "hidroelectrica"

# API Backend (Switching to the working SVC endpoint)
API_BASE_URL = "https://hidroelectrica-svc.smartcmobile.com"

# Endpoint paths
API_PATH_GET_ID = "/API/UserLogin/GetId"
API_PATH_VALIDATE_LOGIN = "/API/UserLogin/ValidateUserLogin"
API_PATH_GET_USER_SETTING = "/API/UserLogin/GetUserSetting"

API_PATH_GET_BILL = "/Service/Billing/GetBill"
API_PATH_GET_BILL_HISTORY = "/Service/Billing/GetBillingHistoryList"

API_PATH_GET_USAGE_GENERATION = "/Service/Usage/GetUsageGeneration"
API_PATH_GET_MULTI_METER = "/Service/Usage/GetMultiMeter"

API_PATH_GET_METER_READ_HISTORY = "/Service/IndexHistory/GetMeterReadHistory"

# Headers logic
HEADERS_PRE_AUTH = {
    "SourceType": "0",
    "Content-Type": "application/json",
    "Host": "hidroelectrica-svc.smartcmobile.com",
    "User-Agent": "okhttp/4.9.1",
}

HEADERS_POST_AUTH_BASE = {
    "SourceType": "1",
    "Content-Type": "application/json",
    "Host": "hidroelectrica-svc.smartcmobile.com",
    "User-Agent": "okhttp/4.9.1",
}

# Config keys
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# Defaults
DEFAULT_SCAN_INTERVAL = 3600  # 1 oră
