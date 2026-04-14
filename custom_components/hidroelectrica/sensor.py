"""Senzori pentru Hidroelectrica."""

import logging
from typing import Any, Dict, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_EURO, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ACCOUNT_NUMBER,
    ATTR_ADDRESS,
    ATTR_DUE_DATE,
    ATTR_LAST_READING_DATE,
    ATTR_METER_NUMBER,
    ATTR_UTILITY_ACCOUNT_NUMBER,
    DOMAIN,
)
from .coordinator import HidroelectricaDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Hidroelectrica folosește RON, dar HA are CURRENCY_EURO. 
# Vom folosi "RON" ca string direct pentru unit_of_measurement.
CURRENCY_RON = "RON"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator: HidroelectricaDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for uan, data in coordinator.data.items():
        # Sold Curent
        entities.append(HidroelectricaBalanceSensor(coordinator, uan))
        # Ultima Factură
        entities.append(HidroelectricaBillSensor(coordinator, uan))
        # Index Consum
        entities.append(HidroelectricaMeterSensor(coordinator, uan, "consumption"))
        # Index Injecție (2.8.0 / 1.8.0_P)
        entities.append(HidroelectricaMeterSensor(coordinator, uan, "injection"))

    async_add_entities(entities)


class HidroelectricaBaseSensor(CoordinatorEntity, SensorEntity):
    """Bază pentru toți senzorii Hidroelectrica."""

    def __init__(
        self,
        coordinator: HidroelectricaDataUpdateCoordinator,
        uan: str,
        sensor_type: str,
    ) -> None:
        """Inițializare."""
        super().__init__(coordinator)
        self._uan = uan
        self._type = sensor_type
        
        acc_info = coordinator.data.get(uan, {}).get("account_info", {})
        self._acc_number = acc_info.get("AccountNumber", "")
        self._meter_number = acc_info.get("MeterNumber", "")
        self._address = acc_info.get("ServiceAddress", "")

        self._attr_unique_id = f"{uan}_{sensor_type}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, uan)},
            "name": f"iHidro POD {uan}",
            "manufacturer": "Hidroelectrica",
            "model": "iHidro Account",
            "configuration_url": "https://ihidro.ro",
        }

    @property
    def pod_data(self) -> Dict[str, Any]:
        """Datele specifice pentru acest POD."""
        return self.coordinator.data.get(self._uan, {})


class HidroelectricaBalanceSensor(HidroelectricaBaseSensor):
    """Senzor pentru soldul curent."""

    def __init__(self, coordinator: HidroelectricaDataUpdateCoordinator, uan: str) -> None:
        """Inițializare."""
        super().__init__(coordinator, uan, "balance")
        self._attr_name = "Sold Curent"
        self._attr_native_unit_of_measurement = CURRENCY_RON
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:cash-multiple"

    @property
    def native_value(self) -> Optional[float]:
        """Valoarea soldului."""
        bill = self.pod_data.get("bill") or {}
        if not bill:
            return None
        # Soldul poate fi negativ dacă există plăți în avans
        try:
            val = bill.get("TotalBalance", 0)
            return float(val)
        except (ValueError, TypeError):
            return None


class HidroelectricaBillSensor(HidroelectricaBaseSensor):
    """Senzor pentru valoarea ultimei facturi."""

    def __init__(self, coordinator: HidroelectricaDataUpdateCoordinator, uan: str) -> None:
        """Inițializare."""
        super().__init__(coordinator, uan, "last_bill")
        self._attr_name = "Ultima Factură"
        self._attr_native_unit_of_measurement = CURRENCY_RON
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:file-document-outline"

    @property
    def native_value(self) -> Optional[float]:
        """Valoarea facturii."""
        bill = self.pod_data.get("bill") or {}
        if not bill:
            return None
        try:
            val = bill.get("LastBillingAmount", 0)
            return float(val)
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Atribute suplimentare."""
        bill = self.pod_data.get("bill") or {}
        return {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._acc_number,
            ATTR_ADDRESS: self._address,
            ATTR_DUE_DATE: bill.get("LastBillDueDate"),
            "data_factura": bill.get("LastBillDate"),
            "numar_factura": bill.get("LastBillNumber"),
        }


class HidroelectricaMeterSensor(HidroelectricaBaseSensor):
    """Senzor pentru indexul contorului (Consum sau Injecție)."""

    def __init__(
        self,
        coordinator: HidroelectricaDataUpdateCoordinator,
        uan: str,
        meter_type: str,
    ) -> None:
        """Inițializare."""
        super().__init__(coordinator, uan, meter_type)
        if meter_type == "consumption":
            self._attr_name = "Index Consum (1.8.0)"
            self._attr_icon = "mdi:gauge"
        else:
            self._attr_name = "Index Injecție (2.8.0)"
            self._attr_icon = "mdi:gauge-empty"

        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def native_value(self) -> Optional[float]:
        """Valoarea indexului."""
        meter = self.pod_data.get("meter", {})
        if not meter:
            return None
        
        # În API-ul iHidro, indexul vine de obicei sub formă de listă sau câmpuri dedicate.
        # Încercăm să găsim RegisterCode corespunzător.
        # registerCode "1.8.0" pentru consum, "2.8.0" sau "1.8.0_P" pentru injecție.
        # Deoarece coordinatorul returnează meter history [0], verificăm dacă acesta are datele.
        
        # NOTĂ: Structura exactă a obiectului meter depinde de răspunsul API-ului.
        # Dacă meter_history[0] conține direct valoarea:
        reg_code = "1.8.0" if self._type == "consumption" else "2.8.0"
        
        # iHidro uneori trimite RegisterCode și Reading în obiectul Table.
        # Dacă meter este un rând din Table:
        if meter.get("RegisterCode") == reg_code:
            try:
                return float(meter.get("Reading", 0))
            except (ValueError, TypeError):
                pass
        
        # Dacă prosumatorul are câmpuri diferite:
        if self._type == "injection" and meter.get("RegisterCode") == "1.8.0_P":
            try:
                return float(meter.get("Reading", 0))
            except (ValueError, TypeError):
                pass

        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Atribute suplimentare."""
        meter = self.pod_data.get("meter", {})
        return {
            ATTR_METER_NUMBER: meter.get("meterSerialNumber"),
            ATTR_LAST_READING_DATE: meter.get("readingDate"),
            "tip_index": meter.get("readingType"),
        }
