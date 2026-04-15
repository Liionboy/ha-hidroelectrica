"""Senzori pentru Hidroelectrica."""

import logging
from typing import Any, Dict, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
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

CURRENCY_RON = "RON"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator: HidroelectricaDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for uan in coordinator.data:
        # Sold Curent
        entities.append(HidroelectricaBalanceSensor(coordinator, uan))
        # Ultima Factură
        entities.append(HidroelectricaBillSensor(coordinator, uan))
        # Index Consum
        entities.append(HidroelectricaMeterSensor(coordinator, uan, "consumption"))
        # Index Injecție
        entities.append(HidroelectricaMeterSensor(coordinator, uan, "injection"))
        # Consum lunar/recent
        entities.append(HidroelectricaUsageSensor(coordinator, uan))

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
        self._address = acc_info.get("ServiceAddress", "") or acc_info.get("Address", "")

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
        self._attr_translation_key = "balance"
        self._attr_native_unit_of_measurement = CURRENCY_RON
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:cash-multiple"

    @property
    def native_value(self) -> Optional[float]:
        """Valoarea soldului."""
        bill = self.pod_data.get("bill")
        if not bill:
            return None
        try:
            # În iHidro SVC, soldul total poate fi în TotalBalance sau similar
            val = bill.get("TotalBalance") or bill.get("Balance")
            if val is None:
                return None
            return float(val)
        except (ValueError, TypeError):
            return None


class HidroelectricaBillSensor(HidroelectricaBaseSensor):
    """Senzor pentru valoarea ultimei facturi."""

    def __init__(self, coordinator: HidroelectricaDataUpdateCoordinator, uan: str) -> None:
        """Inițializare."""
        super().__init__(coordinator, uan, "last_bill")
        self._attr_translation_key = "last_bill"
        self._attr_native_unit_of_measurement = CURRENCY_RON
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:file-document-outline"

    @property
    def native_value(self) -> Optional[float]:
        """Valoarea facturii."""
        bill = self.pod_data.get("bill")
        if not bill:
            return None
        try:
            val = bill.get("AmountToPay") or bill.get("TotalAmount") or 0
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
            ATTR_DUE_DATE: bill.get("DueDate") or bill.get("LastBillDueDate"),
            "data_factura": bill.get("InvoiceDate") or bill.get("LastBillDate"),
            "numar_factura": bill.get("InvoiceNumber") or bill.get("LastBillNumber"),
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
        self._attr_translation_key = f"{meter_type}_index"
        if meter_type == "consumption":
            self._attr_icon = "mdi:gauge"
        else:
            self._attr_icon = "mdi:gauge-empty"

        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def native_value(self) -> Optional[float]:
        """Valoarea indexului."""
        registers = self.pod_data.get("registers", {})
        
        # Identificăm codul de registru
        if self._type == "consumption":
            reg_codes = ["1.8.0", "1.8.1", "1.8.2"]
        else:
            reg_codes = ["2.8.0", "1.8.0_P", "2.8.1"]

        for code in reg_codes:
            if code in registers:
                try:
                    # Cheia corectă în iHidro SVC pentru valoare index este ReadingValue
                    val = registers[code].get("ReadingValue") or registers[code].get("Reading")
                    if val is not None:
                        return float(val)
                except (ValueError, TypeError):
                    continue
        
        # Fallback 
        meter = self.pod_data.get("meter")
        if meter:
            try:
                val = meter.get("ReadingValue") or meter.get("Reading")
                if val is not None:
                    return float(val)
            except (ValueError, TypeError):
                pass

        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Atribute suplimentare."""
        meter = self.pod_data.get("meter", {})
        return {
            ATTR_METER_NUMBER: meter.get("MeterSerialNumber") or meter.get("meterSerialNumber") or self._meter_number,
            ATTR_LAST_READING_DATE: meter.get("ReadingDate") or meter.get("readingDate"),
            "tip_index": meter.get("ReadingType") or meter.get("readingType"),
        }


class HidroelectricaUsageSensor(HidroelectricaBaseSensor):
    """Senzor pentru consumul recent/lunar."""

    def __init__(self, coordinator: HidroelectricaDataUpdateCoordinator, uan: str) -> None:
        """Inițializare."""
        super().__init__(coordinator, uan, "usage")
        self._attr_translation_key = "monthly_usage"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:chart-line"

    @property
    def native_value(self) -> Optional[float]:
        """Valoarea consumului."""
        usage = self.pod_data.get("usage") or {}
        try:
            # În noul API, consumul poate fi structurat altfel, extragem prima valoare relevantă
            if isinstance(usage, list) and usage:
                val = usage[0].get("ReadingValue") or usage[0].get("Usage")
            else:
                val = usage.get("TotalUsage") or usage.get("Usage")
            return float(val) if val else None
        except (ValueError, TypeError):
            return None
