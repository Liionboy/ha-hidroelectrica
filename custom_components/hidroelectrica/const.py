"""Constante pentru integrarea Hidroelectrica (iHidro)."""

DOMAIN = "hidroelectrica"

# API Base
API_BASE_URL = "https://hidroelectrica-svc.smartcmobile.com"

# API Paths
API_PATH_GET_ID = "/API/UserLogin/GetId"
API_PATH_VALIDATE_LOGIN = "/API/UserLogin/ValidateUserLogin"
API_PATH_GET_USER_SETTING = "/API/UserLogin/GetUserSetting"
API_PATH_GET_BILL = "/Service/Billing/GetBill"
API_PATH_GET_BILL_HISTORY = "/Service/Billing/GetBillingHistoryList"
API_PATH_GET_USAGE_GENERATION = "/Service/Usage/GetUsageGeneration"
API_PATH_GET_PODS = "/Service/SelfMeterReading/GetPods"
API_PATH_GET_METER_READ_HISTORY = "/Service/IndexHistory/GetMeterReadHistory"

# Headers
HEADERS = {
    "SourceType": "1",
    "Content-Type": "application/json",
    "Host": "hidroelectrica-svc.smartcmobile.com",
    "User-Agent": "okhttp/4.9.1",
}

# Configuration
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# Update Interval
DEFAULT_UPDATE_INTERVAL = 3600  # 1 hour

# Attributes
ATTR_UTILITY_ACCOUNT_NUMBER = "utility_account_number"
ATTR_ACCOUNT_NUMBER = "account_number"
ATTR_ADDRESS = "address"
ATTR_METER_NUMBER = "meter_number"
ATTR_LAST_READING_DATE = "last_reading_date"
ATTR_DUE_DATE = "due_date"
