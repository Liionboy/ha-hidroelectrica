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
        self._attr_translation_key = "balance"
        self._attr_native_unit_of_measurement = CURRENCY_RON
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:cash-multiple"

    @property
    def native_value(self) -> Optional[float]:
        """Valoarea soldului."""
        bill = self.pod_data.get("bill")
        if not bill:
            _LOGGER.debug("Sold '%s': lipsește 'bill' în pod_data", self._uan)
            return None
        try:
            val = bill.get("TotalBalance")
            if val is None:
                 _LOGGER.debug("Sold '%s': cheia 'TotalBalance' lipsește în %s", self._uan, bill)
                 return None
            return float(val)
        except (ValueError, TypeError) as err:
            _LOGGER.error("Sold '%s': eroare conversie %s: %s", self._uan, val, err)
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
                    val = registers[code].get("Reading")
                    if val is not None:
                        return float(val)
                except (ValueError, TypeError):
                    continue
        
        # Fallback la primul index găsit în 'meter' dacă nu am găsit codurile standard
        meter = self.pod_data.get("meter")
        if meter:
            try:
                val = meter.get("Reading")
                if val is not None:
                    _LOGGER.debug("Index '%s' (%s): fallback la valoarea din 'meter'", self._uan, self._type)
                    return float(val)
            except (ValueError, TypeError):
                pass

        _LOGGER.debug("Index '%s' (%s): nu am găsit nicio valoare în registers (%s) sau meter (%s)", 
                     self._uan, self._type, list(registers.keys()), meter)
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Atribute suplimentare."""
        meter = self.pod_data.get("meter", {})
        return {
            ATTR_METER_NUMBER: meter.get("meterSerialNumber") or self._meter_number,
            ATTR_LAST_READING_DATE: meter.get("readingDate"),
            "tip_index": meter.get("readingType"),
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
        # API-ul iHidro returnează o listă de valori în usage[result][Data]
        # Totuși, structura depinde de perioada cerută.
        # Pentru moment, extragem totalul dacă există.
        try:
            val = usage.get("TotalUsage", 0)
            return float(val) if val else None
        except (ValueError, TypeError):
            return None
