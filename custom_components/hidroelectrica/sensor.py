"""Platforma Sensor pentru Hidroelectrica România."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import HidroelectricaCoordinator
from .helpers import (
    MONTHS_NUM_RO,
    READING_TYPE_MAP,
    format_number_ro,
    format_ron,
    parse_romanian_amount,
    safe_get,
)

_LOGGER = logging.getLogger(__name__)

def _parse_date_dmy(date_str: str) -> datetime | None:
    """Parsează o dată în diverse formate. Returnează None dacă eșuează."""
    if not date_str:
        return None
    # Dacă conține spațiu + timp (ex: "06/15/2021 00:00:00"), trunchiem
    clean = date_str.rstrip("Z").split(" ")[0] if " " in date_str else date_str.rstrip("Z")
    for fmt in ("%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            continue
    return None

def _format_date_display(date_str: str) -> str:
    """Formatează o dată pentru afișare. Returnează string-ul original dacă nu poate parsa."""
    parsed = _parse_date_dmy(date_str)
    if parsed:
        return parsed.strftime("%d/%m/%Y")
    return date_str

def _extract_year_from_dmy(date_str: str) -> int | None:
    """Extrage anul dintr-o dată dd/MM/yyyy sau yyyy-... format."""
    parsed = _parse_date_dmy(date_str)
    if parsed:
        return parsed.year
    if date_str and len(date_str) >= 10:
        try:
            return int(date_str[-4:])
        except (ValueError, TypeError):
            pass
    if date_str and len(date_str) >= 4:
        try:
            return int(date_str[:4])
        except (ValueError, TypeError):
            pass
    return None

def _format_duedate_yyyymmdd(duedate: str) -> str:
    """Formatează duedate din format yyyyMMdd (ex: '20260316') în dd/MM/yyyy."""
    if not duedate or len(duedate) != 8:
        return duedate or "Necunoscut"
    try:
        parsed = datetime.strptime(duedate, "%Y%m%d")
        return parsed.strftime("%d/%m/%Y")
    except ValueError:
        return duedate

def _get_meter_read_list(data: dict | None) -> list:
    """Extrage lista de citiri din GetMeterReadHistory.

    Structură reală: result.Data = LIST direct cu:
    {POD, CounterSeries, RegisterDescription, Registers, ReadingType, Date, Index}
    """
    if not data:
        return []
    mrh = data.get("meter_read_history")
    if not mrh:
        return []
    mrh_data = safe_get(mrh, "result", "Data", default=[])
    if isinstance(mrh_data, list):
        return mrh_data
    if isinstance(mrh_data, dict):
        for key in ("objMeterReadHistoryData", "objMeterReadData", "objHistoryData"):
            lst = mrh_data.get(key, [])
            if lst:
                return lst
    return []

def _get_billing_list(data: dict | None) -> list:
    """Extrage lista de facturi din GetBillingHistory.

    Structură reală: result.objBillingHistoryEntity = LIST cu:
    {amount, invoiceDate, dueDate, invoiceType, exbel, invoiceId, ...}
    """
    if not data:
        return []
    bh = data.get("billing_history")
    if not bh:
        return []
    result = bh.get("result", {})
    if not isinstance(result, dict):
        return []
    bh_list = result.get("objBillingHistoryEntity", [])
    if bh_list:
        return bh_list
    data_inner = result.get("Data", {})
    if isinstance(data_inner, list):
        return data_inner
    if isinstance(data_inner, dict):
        for key in ("objBillingHistoryData", "objBillingData"):
            lst = data_inner.get(key, [])
            if lst:
                return lst
    return []

def _get_payment_list(data: dict | None) -> list:
    """Extrage lista de plăți din GetBillingHistory.

    Structură reală: result.objBillingPaymentHistoryEntity = LIST cu:
    {amount, paymentDate, channel, type, status, ...}
    """
    if not data:
        return []
    bh = data.get("billing_history")
    if not bh:
        return []
    result = bh.get("result", {})
    if not isinstance(result, dict):
        return []
    return result.get("objBillingPaymentHistoryEntity", []) or []

def _get_usage_list(data: dict | None) -> list:
    """Extrage lista de consum din GetUsageGeneration.

    Structură reală: result.Data.objUsageGenerationResultSetTwo = LIST cu:
    {Month, Year, UsageDate, UsageValue, value, BillingDays, FromDate, ToDate, ...}
    """
    if not data:
        return []
    usage = data.get("usage")
    if not usage:
        return []
    usage_data = safe_get(usage, "result", "Data", default={})
    if isinstance(usage_data, dict):
        return usage_data.get("objUsageGenerationResultSetTwo", []) or []
    if isinstance(usage_data, list):
        return usage_data
    return []

def _get_window_data(data: dict | None) -> dict:
    """Extrage datele ferestrei de autocitire.

    Structură reală: result.Data = DICT cu:
    {OpeningDate, ClosingDate, NextMonthOpeningDate, NextMonthClosingDate, Is_Window_Open}
    """
    if not data:
        return {}
    wd = data.get("window_dates") or data.get("window_dates_enc") or {}
    wd_data = safe_get(wd, "result", "Data", default={})
    if isinstance(wd_data, dict):
        return wd_data
    return {}

def _compute_closing_date(wd: dict) -> str:
    """Calculează data corectă de închidere a ferestrei de autocitire.

    Bug Hidroelectrica: NextMonthClosingDate NU se actualizează corect —
    rămâne pe luna curentă în loc de luna viitoare uneori.

    Soluția: calculăm durata ferestrei și adăugăm la NextMonthOpeningDate.
    """
    from datetime import datetime, timedelta

    opening_day = wd.get("OpeningDate", "")
    closing_day = wd.get("ClosingDate", "")
    next_opening = wd.get("NextMonthOpeningDate", "")

    if opening_day and closing_day and next_opening:
        try:
            open_d = int(opening_day)
            close_d = int(closing_day)
            durata = close_d - open_d
            if durata < 0:
                # Fereastra trece peste granița lunii (ex: 28 → 2)
                # Estimăm ~30 zile în lună
                durata = (30 - open_d) + close_d
            dt_opening = datetime.strptime(next_opening, "%d/%m/%Y")
            dt_closing = dt_opening + timedelta(days=durata)
            return dt_closing.strftime("%d/%m/%Y")
        except (ValueError, IndexError):
            pass

    return wd.get("NextMonthClosingDate", "")

def _get_pods_list(data: dict | None) -> list:
    """Extrage lista de PODs din GetPods.

    Structură reală: result.Data = LIST direct cu:
    {accountID, installation, contractAccountID, pod}
    """
    if not data:
        return []
    pods = data.get("pods")
    if not pods:
        return []
    pods_data = safe_get(pods, "result", "Data", default=[])
    if isinstance(pods_data, list):
        return pods_data
    if isinstance(pods_data, dict):
        return pods_data.get("objPodData", []) or []
    return []

def _get_multi_meter_data(data: dict | None) -> dict:
    """Extrage datele contorului din GetMultiMeter.

    Structură reală: result.MeterDetails = LIST cu:
    {MeterType, MeterNumber, IsAMI, Status, Address}
    """
    if not data:
        return {}
    mm = data.get("multi_meter")
    if not mm:
        return {}
    result = mm.get("result", {})
    if not isinstance(result, dict):
        return {}
    meter_details = result.get("MeterDetails", [])
    if meter_details and isinstance(meter_details, list):
        return meter_details[0]
    return {}

def _get_previous_meter_read(data: dict | None) -> dict | None:
    """Extrage datele din GetPreviousMeterRead.

    Structură reală: result.Data = LIST cu un singur element conținând date despre contract.
    """
    if not data:
        return None
    prev = data.get("previous_meter_read")
    if not prev:
        return None
    prev_data = safe_get(prev, "result", "Data", default=[])
    if isinstance(prev_data, list) and prev_data:
        return prev_data[0]
    if isinstance(prev_data, dict):
        for k in ("objPreviousMeterReadData",):
            inner = prev_data.get(k, [])
            if inner and isinstance(inner, list):
                return inner[0]
        return prev_data if prev_data else None
    return None

def _get_active_counter_series(data: dict | None) -> str | None:
    """Determină seria de contor activă (cea mai recentă)."""
    if not data:
        return None
    mcs = data.get("meter_counter_series")
    if not mcs:
        return None
    mcs_data = safe_get(mcs, "result", "Data", default=[])
    if not isinstance(mcs_data, list) or not mcs_data:
        if isinstance(mcs_data, dict):
            inner = mcs_data.get("objMeterCounterSeriesList", [])
            if isinstance(inner, list) and inner:
                mcs_data = inner
            else:
                return None
        else:
            return None

    # Alegem seria cu MrDate cel mai recent
    best_series = None
    best_date = datetime.min
    for entry in mcs_data:
        series = entry.get("CounterSeries", "") or entry.get("MeterCounterSeriesId", "")
        mr_date_str = entry.get("MrDate", "")
        parsed = _parse_date_dmy(mr_date_str)
        if parsed and parsed > best_date:
            best_date = parsed
            best_series = str(series)

    return best_series

def _get_latest_meter_read(
    data: dict | None,
    register_filter: str | None = None,
) -> dict | None:
    """Returnează cea mai recentă citire din GetMeterReadHistory.

    Filtrează pe seria de contor activă (dacă e cunoscută).
    Dacă register_filter e specificat (ex: "1.8.0"), returnează doar citiri cu acel Registers.
    """
    reads = _get_meter_read_list(data)
    if not reads:
        return None

    active_series = _get_active_counter_series(data)
    if active_series:
        filtered = [
            r for r in reads
            if str(r.get("CounterSeries", "")) == str(active_series)
            or str(r.get("MeterCounterSeriesId", "")) == str(active_series)
        ]
        if filtered:
            reads = filtered

    if register_filter:
        reads = [r for r in reads if r.get("Registers") == register_filter]
        if not reads:
            return None

    def parse_key(entry):
        d = _parse_date_dmy(entry.get("Date", ""))
        return d if d else datetime.min

    return max(reads, key=parse_key)

def _get_meter_counter_series_fallback(data: dict | None) -> tuple[int | None, str | None]:
    """Fallback: extrage ultimul index din meter_counter_series (seria activă)."""
    if not data:
        return None, None
    mcs = data.get("meter_counter_series")
    if not mcs:
        return None, None
    mcs_data = safe_get(mcs, "result", "Data", default=[])
    if isinstance(mcs_data, dict):
        inner = mcs_data.get("objMeterCounterSeriesList", [])
        if isinstance(inner, list) and inner:
            mcs_data = inner
    if not isinstance(mcs_data, list) or not mcs_data:
        return None, None

    active_series = _get_active_counter_series(data)
    target = None
    for entry in mcs_data:
        cs = entry.get("CounterSeries") or entry.get("MeterCounterSeriesId")
        if active_series and str(cs) == str(active_series):
            target = entry
            break
    if not target:
        target = mcs_data[0]

    index_str = target.get("Index", "")
    mr_date = target.get("MrDate", "")
    if index_str:
        indices = index_str.split(",")
        if indices:
            try:
                return int(indices[-1].strip()), mr_date
            except (ValueError, TypeError):
                pass
    return None, None

def _get_bill_result(data: dict | None) -> dict:
    """Extrage result din GetBill."""
    if not data:
        return {}
    bill = data.get("bill") or {}
    result = bill.get("result", {})
    return result if isinstance(result, dict) else {}

def _extract_usage_years(data: dict | None) -> dict[int, list]:
    """Grupează datele de consum pe an."""
    entries = _get_usage_list(data)
    if not entries:
        return {}
    yearly: dict[int, list] = defaultdict(list)
    for entry in entries:
        year = entry.get("Year", 0)
        if year:
            yearly[year].append(entry)
    return dict(yearly)

def _extract_meter_read_years(
    data: dict | None,
    register_filter: str | None = None,
) -> dict[int, list]:
    """Grupează citirile de contor pe an (filtrate pe seria activă)."""
    entries = _get_meter_read_list(data)
    if not entries:
        return {}

    active_series = _get_active_counter_series(data)
    if active_series:
        entries = [
            e for e in entries
            if str(e.get("CounterSeries", "")) == str(active_series)
        ]

    if register_filter:
        entries = [e for e in entries if e.get("Registers") == register_filter]

    yearly: dict[int, list] = defaultdict(list)
    for entry in entries:
        year = _extract_year_from_dmy(entry.get("Date", ""))
        if year:
            yearly[year].append(entry)
    return dict(yearly)

_COMP_PREFIXES = ("Comp ANRE", "Comp ", "Compensare")

def _is_compensation(channel: str) -> bool:
    """Determină dacă o plată este compensație ANRE (prosumator)."""
    return any(channel.startswith(p) for p in _COMP_PREFIXES)

def _extract_payment_years(
    data: dict | None,
    channel_filter: str | None = None,
) -> dict[int, list]:
    """Grupează plățile reale pe an."""
    entries = _get_payment_list(data)
    if not entries:
        return {}
    if channel_filter == "normal":
        entries = [e for e in entries if not _is_compensation(e.get("channel", ""))]
    elif channel_filter == "comp":
        entries = [e for e in entries if _is_compensation(e.get("channel", ""))]
    yearly: dict[int, list] = defaultdict(list)
    for entry in entries:
        year = _extract_year_from_dmy(entry.get("paymentDate", ""))
        if year:
            yearly[year].append(entry)
    return dict(yearly)

class HidroelectricaEntity(
    CoordinatorEntity[HidroelectricaCoordinator], SensorEntity
):
    """Clasă de bază pentru entitățile Hidroelectrica România."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: HidroelectricaCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._uan = coordinator.uan
        self._custom_entity_id: str | None = None

    @property
    def entity_id(self) -> str | None:
        return self._custom_entity_id

    @entity_id.setter
    def entity_id(self, value: str) -> None:
        self._custom_entity_id = value

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._uan)},
            name=f"Hidroelectrica România ({self._uan})",
            manufacturer="Hidroelectrica SA",
            model="Hidroelectrica România",
            entry_type=DeviceEntryType.SERVICE,
        )

def _build_sensors_for_coordinator(
    coordinator: HidroelectricaCoordinator,
    config_entry: ConfigEntry,
    hass: HomeAssistant,
) -> list[SensorEntity]:
    """Construiește lista de senzori pentru un coordinator (un cont)."""
    uan = coordinator.uan
    sensors: list[SensorEntity] = []

    sensors.append(DateContractSensor(coordinator, config_entry))
    sensors.append(SoldFacturaSensor(coordinator, config_entry))
    sensors.append(FacturaRestantaSensor(coordinator, config_entry))
    sensors.append(IndexEnergieSensor(coordinator, config_entry))

    # CitirePermisaSensor — doar la non-prosumator
    reads_early = _get_meter_read_list(coordinator.data)
    is_prosumer = any(r.get("Registers") == "1.8.0_P" for r in reads_early)
    if not is_prosumer:
        sensors.append(CitirePermisaSensor(coordinator, config_entry))
    else:
        _LOGGER.info(
            "Prosumator detectat (UAN=%s): CitirePermisaSensor NU se creează "
            "(distribuitorul citește contorul automat).",
            uan,
        )

    # Arhivă consum
    usage_years = _extract_usage_years(coordinator.data)
    if usage_years:
        max_year = max(usage_years.keys())
        sensors.append(ArhivaConsumSensor(coordinator, config_entry, max_year))
    else:
        current_year = datetime.now().year
        sensors.append(ArhivaConsumSensor(coordinator, config_entry, current_year))

    has_production = is_prosumer

    # Arhivă index consum
    consum_filter = "1.8.0" if has_production else None
    mrh_years = _extract_meter_read_years(coordinator.data, register_filter=consum_filter)
    if mrh_years:
        max_year = max(mrh_years.keys())
        sensors.append(ArhivaIndexSensor(coordinator, config_entry, max_year, register_filter=consum_filter))
    else:
        current_year = datetime.now().year
        sensors.append(ArhivaIndexSensor(coordinator, config_entry, current_year, register_filter=consum_filter))

    # Prosumator: Index energie produsă + Arhivă index producție
    if has_production:
        sensors.append(IndexEnergieProdusSensor(coordinator, config_entry))

        prod_years = _extract_meter_read_years(coordinator.data, register_filter="1.8.0_P")
        if prod_years:
            max_year_prod = max(prod_years.keys())
            sensors.append(ArhivaIndexProdusSensor(coordinator, config_entry, max_year_prod))
        else:
            current_year = datetime.now().year
            sensors.append(ArhivaIndexProdusSensor(coordinator, config_entry, current_year))

    # Arhivă plăți normale
    normal_years = _extract_payment_years(coordinator.data, channel_filter="normal")
    if normal_years:
        max_year = max(normal_years.keys())
        sensors.append(ArhivaPlatiSensor(coordinator, config_entry, max_year))
    else:
        current_year = datetime.now().year
        sensors.append(ArhivaPlatiSensor(coordinator, config_entry, current_year))

    # Arhivă plăți prosumator
    if has_production:
        comp_years = _extract_payment_years(coordinator.data, channel_filter="comp")
        if comp_years:
            max_comp_year = max(comp_years.keys())
            sensors.append(ArhivaPlatiProsumatorSensor(coordinator, config_entry, max_comp_year))
        else:
            current_year = datetime.now().year
            sensors.append(ArhivaPlatiProsumatorSensor(coordinator, config_entry, current_year))

    return sensors


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configurează senzorii pentru toate conturile selectate."""
    coordinators: dict[str, HidroelectricaCoordinator] = (
        config_entry.runtime_data.coordinators
    )

    _LOGGER.debug(
        "Inițializare platforma sensor pentru %s (entry_id=%s, conturi=%s).",
        DOMAIN,
        config_entry.entry_id,
        list(coordinators.keys()),
    )

    all_sensors: list[SensorEntity] = []

    for uan, coordinator in coordinators.items():
        sensors = _build_sensors_for_coordinator(coordinator, config_entry, hass)
        all_sensors.extend(sensors)

    _LOGGER.info(
        "Total %s senzori adăugați pentru %s (entry_id=%s).",
        len(all_sensors), DOMAIN, config_entry.entry_id,
    )

    async_add_entities(all_sensors)

class DateContractSensor(HidroelectricaEntity):
    """Senzor pentru afișarea datelor contractului."""

    _attr_icon = "mdi:file-document-edit-outline"
    _attr_translation_key = "date_contract"

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_name = "Date contract"
        self._attr_unique_id = f"{DOMAIN}_date_contract_{self._uan}"
        self._custom_entity_id = f"sensor.{DOMAIN}_{self._uan}_date_contract"

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        if not data:
            return None
        return self._uan

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if not data:
            return {"attribution": ATTRIBUTION}

        attrs: dict[str, Any] = {}

        pods_list = _get_pods_list(data)
        if pods_list:
            pod = pods_list[0]
            if pod.get("pod"):
                attrs["CLC - Cod punct de măsură (POD)"] = pod["pod"]
            if pod.get("installation"):
                attrs["Instalație"] = pod["installation"]
            if pod.get("contractAccountID"):
                attrs["Cod încasare"] = pod["contractAccountID"]
            if pod.get("accountID"):
                attrs["Cod partener (BP)"] = pod["accountID"]

        active_series = _get_active_counter_series(data)
        if active_series:
            attrs["Serie contor"] = active_series

        meter = _get_multi_meter_data(data)
        if meter:
            if meter.get("MeterType"):
                attrs["Tip contor"] = meter["MeterType"]
            if meter.get("IsAMI") is not None:
                attrs["Contor inteligent (AMI)"] = "Da" if meter["IsAMI"] else "Nu"

        prev = _get_previous_meter_read(data)
        if prev:
            attrs["────"] = ""

            if prev.get("distributor"):
                attrs["Operator de Distribuție (OD)"] = prev["distributor"]
            if prev.get("supplier"):
                supplier_map = {"HE": "Hidroelectrica"}
                raw_supplier = prev["supplier"]
                attrs["Furnizor"] = supplier_map.get(raw_supplier, raw_supplier)
            if prev.get("distCustomer"):
                attrs["Client distribuitor"] = prev["distCustomer"]
            if prev.get("distCustomerId"):
                attrs["ID client distribuitor"] = prev["distCustomerId"]
            if prev.get("distContract"):
                attrs["Nr. contract distribuitor"] = prev["distContract"]
            if prev.get("distContractDate"):
                attrs["Data contract distribuitor"] = _format_date_display(
                    prev["distContractDate"]
                )

            attrs["─────"] = ""

            if prev.get("serialNumber"):
                attrs["Serie contor (distribuitor)"] = prev["serialNumber"]
            if prev.get("equipmentNo"):
                attrs["Nr. echipament"] = prev["equipmentNo"]
            if prev.get("registerCat"):
                attrs["Categorie registru"] = prev["registerCat"]
            if prev.get("uom"):
                attrs["Unitate de măsură"] = prev["uom"]
            if prev.get("meterInterval"):
                attrs["Interval citire"] = prev["meterInterval"].capitalize()
        else:
            attrs["────"] = ""
            latest = _get_latest_meter_read(data)
            if latest:
                if latest.get("POD"):
                    attrs["POD (citire)"] = latest["POD"]
                if latest.get("RegisterDescription"):
                    attrs["Registru"] = latest["RegisterDescription"]
                if latest.get("Registers"):
                    attrs["Categorie registru"] = latest["Registers"]

            if meter and meter.get("MeterNumber") and active_series:
                old_meter = meter["MeterNumber"]
                if str(old_meter) != str(active_series):
                    attrs["─────"] = ""
                    attrs["Serie contor veche (multi_meter)"] = old_meter

        attrs["attribution"] = ATTRIBUTION
        return attrs


class SoldFacturaSensor(HidroelectricaEntity):
    """Senzor pentru soldul facturii / balanța curentă."""

    _attr_icon = "mdi:currency-eur"
    _attr_translation_key = "sold_factura"

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_name = "Sold factură"
        self._attr_unique_id = f"{DOMAIN}_sold_factura_{self._uan}"
        self._custom_entity_id = f"sensor.{DOMAIN}_{self._uan}_sold_factura"

    @property
    def native_value(self) -> str | None:
        bill = _get_bill_result(self.coordinator.data)
        if not bill:
            return "Nu"
        rembalance = bill.get("rembalance", "0")
        try:
            val = parse_romanian_amount(str(rembalance))
            if val > 0:
                return "Da"
            if val < 0:
                return "Credit"
            return "Nu"
        except (ValueError, TypeError):
            return "Nu"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        bill = _get_bill_result(self.coordinator.data)
        if not bill:
            return {"attribution": ATTRIBUTION}

        attrs: dict[str, Any] = {}
        rembalance = bill.get("rembalance", "0")
        try:
            rem_val = parse_romanian_amount(str(rembalance))
            if rem_val > 0:
                attrs["Sold"] = f"{format_ron(rem_val)} lei"
                attrs["Status"] = "De plată"
            elif rem_val < 0:
                attrs["Sold"] = f"-{format_ron(abs(rem_val))} lei"
                attrs["Status"] = "Credit (prosumator)"
            else:
                attrs["Sold"] = "0,00 lei"
                attrs["Status"] = "Achitat integral"
        except (ValueError, TypeError):
            attrs["Sold"] = "Necunoscut"
            attrs["Status"] = "Necunoscut"

        billamount = bill.get("billamount", "")
        if billamount:
            try:
                bill_val = parse_romanian_amount(str(billamount))
                attrs["Suma ultimei facturi"] = f"{format_ron(bill_val)} lei"
            except (ValueError, TypeError):
                attrs["Suma ultimei facturi"] = f"{billamount} lei"

        duedate = bill.get("duedate", "")
        if duedate:
            attrs["Data scadenței"] = _format_duedate_yyyymmdd(duedate)

        invoicenumber = bill.get("invoicenumber", "")
        if invoicenumber and not invoicenumber.endswith("=="):
            attrs["Număr factură"] = invoicenumber

        attrs["attribution"] = ATTRIBUTION
        return attrs


class FacturaRestantaSensor(HidroelectricaEntity):
    """Senzor pentru afișarea facturilor restante (neplătite și scadente)."""

    _attr_icon = "mdi:invoice-text-arrow-left"
    _attr_translation_key = "factura_restanta"

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_name = "Factură restantă"
        self._attr_unique_id = f"{DOMAIN}_factura_restanta_{self._uan}"
        self._custom_entity_id = f"sensor.{DOMAIN}_{self._uan}_factura_restanta"

    def _is_overdue(self) -> bool:
        bill = _get_bill_result(self.coordinator.data)
        if not bill:
            return False

        rembalance = bill.get("rembalance", "0")
        try:
            val = parse_romanian_amount(str(rembalance))
            if val <= 0:
                return False
        except (ValueError, TypeError):
            return False

        duedate = bill.get("duedate", "")
        if duedate and len(duedate) == 8:
            try:
                due = datetime.strptime(duedate, "%Y%m%d")
                return datetime.now() > due
            except ValueError:
                pass

        return False

    @property
    def native_value(self) -> str | None:
        return "Da" if self._is_overdue() else "Nu"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if not data:
            return {
                "Total neachitat": "0,00 lei",
                "Detalii": "Nu există facturi restante",
                "attribution": ATTRIBUTION,
            }

        attrs: dict[str, Any] = {}
        bill = _get_bill_result(data)

        if self._is_overdue():
            rembalance = bill.get("rembalance", "0")
            try:
                val = parse_romanian_amount(str(rembalance))
                duedate = _format_duedate_yyyymmdd(bill.get("duedate", ""))
                attrs["Factură restantă"] = (
                    f"Datorie de {format_ron(val)} lei (scadentă {duedate})"
                )
                attrs["Total neachitat"] = f"{format_ron(val)} lei"
            except (ValueError, TypeError):
                attrs["Total neachitat"] = "Necunoscut"
        else:
            attrs["Total neachitat"] = "0,00 lei"

        billing_list = _get_billing_list(data)
        if billing_list:
            def sort_key(e):
                parsed = _parse_date_dmy(e.get("invoiceDate", ""))
                return parsed if parsed else datetime.min

            latest = max(billing_list, key=sort_key)
            attrs["────"] = ""
            attrs["Ultima factură emisă"] = (
                f"{latest.get('amount', 'N/A')} lei din {latest.get('invoiceDate', 'N/A')}"
            )
            if latest.get("invoiceType"):
                attrs["Tip"] = latest["invoiceType"]
            if latest.get("dueDate"):
                attrs["Scadentă"] = latest["dueDate"]

        attrs["attribution"] = ATTRIBUTION
        return attrs


class IndexEnergieSensor(HidroelectricaEntity):
    """Senzor pentru afișarea indexului curent al contorului."""

    _attr_translation_key = "index_energie_electrica"

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_name = "Index energie electrică"
        self._attr_icon = "mdi:lightning-bolt"
        self._attr_unique_id = f"{DOMAIN}_index_curent_{self._uan}"
        self._custom_entity_id = f"sensor.{DOMAIN}_{self._uan}_index_energie_electrica"

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfEnergy.KILO_WATT_HOUR

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data:
            return 0

        latest = _get_latest_meter_read(data, register_filter="1.8.0")
        if not latest:
            latest = _get_latest_meter_read(data)
        if latest:
            idx = latest.get("Index")
            if idx is not None:
                try:
                    return int(idx)
                except (ValueError, TypeError):
                    pass

        prev = _get_previous_meter_read(data)
        if prev:
            prev_val = prev.get("prevMRResult")
            if prev_val is not None:
                try:
                    return int(prev_val)
                except (ValueError, TypeError):
                    pass

        mcs_index, _ = _get_meter_counter_series_fallback(data)
        if mcs_index is not None:
            return mcs_index

        return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if not data:
            return {"attribution": ATTRIBUTION}

        attrs: dict[str, Any] = {}

        active_series = _get_active_counter_series(data)
        if active_series:
            attrs["Serie contor activă"] = active_series

        prev = _get_previous_meter_read(data)
        if prev and prev.get("serialNumber"):
            attrs["Numărul dispozitivului"] = prev["serialNumber"]
        elif active_series:
            attrs["Numărul dispozitivului"] = active_series

        latest = _get_latest_meter_read(data, register_filter="1.8.0")
        if not latest:
            latest = _get_latest_meter_read(data)
        if latest:
            attrs["────"] = ""
            attrs["Ultima citire validată"] = latest.get("Index", "N/A")
            attrs["Data ultimei citiri"] = latest.get("Date", "Necunoscut")
            read_type = latest.get("ReadingType", "")
            if read_type:
                attrs["Tipul citirii curente"] = READING_TYPE_MAP.get(read_type, read_type)
            if latest.get("POD"):
                attrs["POD"] = latest["POD"]
            if latest.get("CounterSeries"):
                attrs["Serie contor (citire)"] = latest["CounterSeries"]
            if latest.get("RegisterDescription"):
                attrs["Registru"] = latest["RegisterDescription"]
            if latest.get("Registers"):
                attrs["Cod registru"] = latest["Registers"]
        else:
            mcs_index, mcs_date = _get_meter_counter_series_fallback(data)
            attrs["────"] = ""
            if mcs_index is not None:
                attrs["Ultima citire (fallback)"] = mcs_index
                if mcs_date:
                    attrs["Data ultimei citiri"] = _format_date_display(mcs_date)
                attrs["Sursă date"] = "meter_counter_series"
            else:
                attrs["Ultima citire"] = "Nu sunt disponibile date"

        prev = _get_previous_meter_read(data)
        if prev:
            attrs["─────"] = ""
            if prev.get("prevMRResult") is not None:
                attrs["Citire anterioară"] = prev["prevMRResult"]
            prev_date = prev.get("prevMRDate", "")
            if prev_date:
                attrs["Data citirii anterioare"] = _format_date_display(prev_date)
            prev_reason = prev.get("prevMRRsn", "")
            if prev_reason:
                reason_map = {
                    "01": "Citire distribuitor",
                    "02": "Autocitire",
                    "03": "Estimare",
                }
                attrs["Motiv citire anterioară"] = reason_map.get(
                    prev_reason, prev_reason
                )

        wd = _get_window_data(data)
        if wd:
            attrs["──────"] = ""
            is_open_raw = wd.get("Is_Window_Open", "0")
            is_open = is_open_raw == "1"
            attrs["Autorizat să citească contorul"] = "Da" if is_open else "Nu"
            open_date = wd.get("NextMonthOpeningDate", "")
            close_date = _compute_closing_date(wd)
            if open_date and close_date:
                attrs["Perioadă transmitere index"] = f"{open_date} — {close_date}"
            if close_date:
                attrs["Indexul poate fi trimis până la"] = close_date

        attrs["attribution"] = ATTRIBUTION
        return attrs


class IndexEnergieProdusSensor(HidroelectricaEntity):
    """Senzor pentru indexul de energie produsă (prosumator)."""

    _attr_translation_key = "index_energie_produsa"

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_name = "Index energie produsă"
        self._attr_icon = "mdi:solar-power-variant"
        self._attr_unique_id = f"{DOMAIN}_index_produs_{self._uan}"
        self._custom_entity_id = f"sensor.{DOMAIN}_{self._uan}_index_energie_produsa"

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfEnergy.KILO_WATT_HOUR

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data:
            return 0

        latest = _get_latest_meter_read(data, register_filter="1.8.0_P")
        if latest:
            idx = latest.get("Index")
            if idx is not None:
                try:
                    return int(idx)
                except (ValueError, TypeError):
                    pass
        return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if not data:
            return {"attribution": ATTRIBUTION}

        attrs: dict[str, Any] = {}

        active_series = _get_active_counter_series(data)
        if active_series:
            attrs["Serie contor activă"] = active_series

        latest = _get_latest_meter_read(data, register_filter="1.8.0_P")
        if latest:
            attrs["Ultima citire producție"] = latest.get("Index", "N/A")
            attrs["Data ultimei citiri"] = latest.get("Date", "Necunoscut")
            read_type = latest.get("ReadingType", "")
            if read_type:
                attrs["Tipul citirii"] = READING_TYPE_MAP.get(read_type, read_type)
            if latest.get("RegisterDescription"):
                attrs["Registru"] = latest["RegisterDescription"]
            attrs["Cod registru"] = "1.8.0_P"
        else:
            attrs["Ultima citire producție"] = "Nu sunt date disponibile"

        reads = _get_meter_read_list(data)
        prod_reads = [r for r in reads if r.get("Registers") == "1.8.0_P"]
        if prod_reads:
            attrs["Total citiri producție"] = len(prod_reads)

        attrs["attribution"] = ATTRIBUTION
        return attrs


class CitirePermisaSensor(HidroelectricaEntity):
    """Senzor pentru verificarea permisiunii de citire a indexului."""

    _attr_translation_key = "citire_permisa"

    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator, config_entry)
        self._attr_name = "Citire permisă"
        self._attr_unique_id = f"{DOMAIN}_citire_permisa_{self._uan}"
        self._custom_entity_id = f"sensor.{DOMAIN}_{self._uan}_citire_permisa"

    def _is_window_open(self) -> bool:
        data = self.coordinator.data
        if not data:
            return False

        wd_plain = data.get("window_dates") or {}
        plain_data = safe_get(wd_plain, "result", "Data", default={})
        if isinstance(plain_data, dict):
            val = plain_data.get("Is_Window_Open", "0")
            if val in ("0", "1"):
                return val == "1"

        prev = data.get("previous_meter_read")
        if prev and isinstance(prev, dict):
            status = prev.get("status_code", 0)
            if status == 200:
                return True

        return False

    @property
    def native_value(self) -> str | None:
        return "Da" if self._is_window_open() else "Nu"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if not data:
            return {"attribution": ATTRIBUTION}

        attrs: dict[str, Any] = {}
        wd = _get_window_data(data)

        if wd:
            open_date = wd.get("NextMonthOpeningDate", "")
            close_date = _compute_closing_date(wd)

            if open_date and close_date:
                attrs["Perioadă transmitere index"] = f"{open_date} — {close_date}"

            if close_date:
                attrs["Indexul poate fi trimis până la"] = close_date

            is_open = self._is_window_open()
            attrs["În perioadă de citire"] = "Da" if is_open else "Nu"

            opening = wd.get("OpeningDate", "")
            closing = wd.get("ClosingDate", "")
            if opening and closing:
                attrs["Zi deschidere fereastră"] = opening
                attrs["Zi închidere fereastră"] = closing
        else:
            attrs["Perioadă transmitere index"] = "Perioada nu a fost stabilită"

        pods_list = _get_pods_list(data)
        if pods_list:
            pod = pods_list[0]
            if pod.get("pod"):
                attrs["POD"] = pod["pod"]
            if pod.get("installation"):
                attrs["Instalație"] = pod["installation"]

        attrs["Cod încasare"] = self._uan
        attrs["attribution"] = ATTRIBUTION
        return attrs

    @property
    def icon(self) -> str:
        value = self.native_value
        if value == "Da":
            return "mdi:clock-check-outline"
        if value == "Nu":
            return "mdi:clock-alert-outline"
        return "mdi:cog-stop-outline"


class ArhivaConsumSensor(HidroelectricaEntity):
    """Senzor pentru afișarea datelor istorice ale consumului."""

    _attr_icon = "mdi:lightning-bolt"
    _attr_translation_key = "arhiva_consum_energie_electrica"

    def __init__(self, coordinator, config_entry, year: int):
        super().__init__(coordinator, config_entry)
        self._year = year
        self._attr_name = f"{year} → Arhivă consum energie electrică"
        self._attr_unique_id = f"{DOMAIN}_arhiva_consum_{self._uan}_{year}"
        self._custom_entity_id = (
            f"sensor.{DOMAIN}_{self._uan}_arhiva_consum_energie_electrica_{year}"
        )

    def _get_entries(self) -> list:
        usage_years = _extract_usage_years(self.coordinator.data)
        return usage_years.get(self._year, [])

    @property
    def native_value(self):
        entries = self._get_entries()
        if not entries:
            return 0
        total = sum(
            float(e.get("value", 0))
            for e in entries
            if e.get("value") is not None
        )
        return round(total, 2)

    @property
    def native_unit_of_measurement(self):
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"attribution": ATTRIBUTION}
        entries = self._get_entries()

        if not entries:
            attrs["Date"] = "Nu sunt disponibile date de consum"
            return attrs

        sorted_entries = sorted(entries, key=lambda e: e.get("Month", 0))

        for entry in sorted_entries:
            month_num = entry.get("Month", 0)
            kwh = entry.get("value", 0)
            lei = entry.get("UsageValue", 0)
            month_name = MONTHS_NUM_RO.get(month_num, str(month_num))
            attrs[f"Consum lunar {month_name}"] = (
                f"{format_number_ro(kwh)} kWh ({format_ron(float(lei))} lei)"
            )

        has_daily = False
        for entry in sorted_entries:
            billing_days = entry.get("BillingDays", "0")
            try:
                days = int(billing_days)
                if days > 0:
                    kwh_val = float(entry.get("value", 0))
                    daily = round(kwh_val / days, 2)
                    month_num = entry.get("Month", 0)
                    month_name = MONTHS_NUM_RO.get(month_num, str(month_num))
                    if not has_daily:
                        attrs["────"] = ""
                        has_daily = True
                    attrs[f"Consum mediu zilnic în {month_name}"] = f"{format_number_ro(daily)} kWh"
            except (ValueError, TypeError, ZeroDivisionError):
                pass

        return attrs


class ArhivaIndexSensor(HidroelectricaEntity):
    """Senzor pentru afișarea istoricului citirilor contorului."""

    _attr_icon = "mdi:clipboard-text-clock-outline"
    _attr_translation_key = "arhiva_index_energie_electrica"

    def __init__(self, coordinator, config_entry, year: int, register_filter: str | None = None):
        super().__init__(coordinator, config_entry)
        self._year = year
        self._register_filter = register_filter
        self._attr_name = f"{year} → Arhivă index energie electrică"
        self._attr_unique_id = f"{DOMAIN}_arhiva_index_{self._uan}_{year}"
        self._custom_entity_id = (
            f"sensor.{DOMAIN}_{self._uan}_arhiva_index_energie_electrica_{year}"
        )

    def _get_entries(self) -> list:
        mrh_years = _extract_meter_read_years(self.coordinator.data, register_filter=self._register_filter)
        return mrh_years.get(self._year, [])

    @property
    def native_value(self):
        return len(self._get_entries())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        entries = self._get_entries()

        if not entries:
            attrs["Date"] = "Nu sunt disponibile date de citire"
            attrs["attribution"] = ATTRIBUTION
            return attrs

        def sort_key(e):
            parsed = _parse_date_dmy(e.get("Date", ""))
            return parsed if parsed else datetime.min

        sorted_entries = sorted(entries, key=sort_key)

        for entry in sorted_entries:
            date_str = entry.get("Date", "Necunoscut")
            index_val = entry.get("Index", "N/A")
            read_type = entry.get("ReadingType", "")
            display_type = READING_TYPE_MAP.get(read_type, read_type) if read_type else "Necunoscut"

            attrs[f"Index ({display_type}) {date_str}"] = f"{index_val} kWh"

        attrs["attribution"] = ATTRIBUTION
        return attrs


class ArhivaIndexProdusSensor(HidroelectricaEntity):
    """Senzor pentru afișarea istoricului citirilor contorului de energie produsă."""

    _attr_icon = "mdi:solar-power-variant"
    _attr_translation_key = "arhiva_index_energie_produsa"

    def __init__(self, coordinator, config_entry, year: int):
        super().__init__(coordinator, config_entry)
        self._year = year
        self._attr_name = f"{year} → Arhivă index energie produsă"
        self._attr_unique_id = f"{DOMAIN}_arhiva_index_produs_{self._uan}_{year}"
        self._custom_entity_id = (
            f"sensor.{DOMAIN}_{self._uan}_arhiva_index_energie_produsa_{year}"
        )

    def _get_entries(self) -> list:
        mrh_years = _extract_meter_read_years(
            self.coordinator.data, register_filter="1.8.0_P"
        )
        return mrh_years.get(self._year, [])

    @property
    def native_value(self):
        return len(self._get_entries())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        entries = self._get_entries()

        if not entries:
            attrs["Date"] = "Nu sunt disponibile date de citire producție"
            attrs["attribution"] = ATTRIBUTION
            return attrs

        def sort_key(e):
            parsed = _parse_date_dmy(e.get("Date", ""))
            return parsed if parsed else datetime.min

        sorted_entries = sorted(entries, key=sort_key)

        for entry in sorted_entries:
            date_str = entry.get("Date", "Necunoscut")
            index_val = entry.get("Index", "N/A")
            read_type = entry.get("ReadingType", "")
            display_type = READING_TYPE_MAP.get(read_type, read_type) if read_type else "Necunoscut"

            attrs[f"Index produs ({display_type}) {date_str}"] = f"{index_val} kWh"

        attrs["attribution"] = ATTRIBUTION
        return attrs


class ArhivaPlatiSensor(HidroelectricaEntity):
    """Senzor pentru afișarea istoricului plăților efectuate de utilizator."""

    _attr_icon = "mdi:cash-register"
    _attr_translation_key = "arhiva_plati"

    def __init__(self, coordinator, config_entry, year: int):
        super().__init__(coordinator, config_entry)
        self._year = year
        self._attr_name = f"{year} → Arhivă plăți"
        self._attr_unique_id = f"{DOMAIN}_arhiva_plati_{self._uan}_{year}"
        self._custom_entity_id = f"sensor.{DOMAIN}_{self._uan}_arhiva_plati_{year}"

    def _get_entries(self) -> list:
        payment_years = _extract_payment_years(
            self.coordinator.data, channel_filter="normal"
        )
        return payment_years.get(self._year, [])

    @property
    def native_value(self):
        return len(self._get_entries())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        entries = self._get_entries()

        if not entries:
            attrs["Date"] = "Nu sunt disponibile date de plată"
            attrs["Plăți efectuate"] = 0
            attrs["Sumă totală"] = "0,00 lei"
            attrs["attribution"] = ATTRIBUTION
            return attrs

        def sort_key(e):
            parsed = _parse_date_dmy(e.get("paymentDate", ""))
            return parsed if parsed else datetime.min

        sorted_entries = sorted(entries, key=sort_key)

        total = 0.0
        for idx, entry in enumerate(sorted_entries, start=1):
            amount_str = entry.get("amount", "0")
            payment_date = entry.get("paymentDate", "Necunoscut")
            channel = entry.get("channel", "")

            try:
                amount_float = parse_romanian_amount(str(amount_str))
            except (ValueError, TypeError):
                amount_float = 0.0

            total += amount_float

            parsed_date = _parse_date_dmy(payment_date)
            if parsed_date:
                month_name = MONTHS_NUM_RO.get(parsed_date.month, "necunoscut")
            else:
                month_name = payment_date

            channel_suffix = f" ({channel})" if channel else ""
            attrs[f"Plată {idx} luna {month_name}{channel_suffix}"] = (
                f"{format_ron(amount_float)} lei"
            )

        attrs["Plăți efectuate"] = len(sorted_entries)
        attrs["Sumă totală"] = f"{format_ron(total)} lei"
        attrs["attribution"] = ATTRIBUTION
        return attrs


class ArhivaPlatiProsumatorSensor(HidroelectricaEntity):
    """Senzor pentru afișarea compensațiilor ANRE primite de prosumator."""

    _attr_icon = "mdi:solar-power-variant"
    _attr_translation_key = "arhiva_plati_prosumator"

    def __init__(self, coordinator, config_entry, year: int):
        super().__init__(coordinator, config_entry)
        self._year = year
        self._attr_name = f"{year} → Arhivă plăți prosumator"
        self._attr_unique_id = (
            f"{DOMAIN}_arhiva_plati_prosumator_{self._uan}_{year}"
        )
        self._custom_entity_id = (
            f"sensor.{DOMAIN}_{self._uan}_arhiva_plati_prosumator_{year}"
        )

    def _get_entries(self) -> list:
        payment_years = _extract_payment_years(
            self.coordinator.data, channel_filter="comp"
        )
        return payment_years.get(self._year, [])

    @property
    def native_value(self):
        return len(self._get_entries())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        entries = self._get_entries()

        if not entries:
            attrs["Date"] = "Nu sunt disponibile compensații ANRE"
            attrs["Compensații ANRE"] = 0
            attrs["Sumă totală"] = "0,00 lei"
            attrs["attribution"] = ATTRIBUTION
            return attrs

        def sort_key(e):
            parsed = _parse_date_dmy(e.get("paymentDate", ""))
            return parsed if parsed else datetime.min

        sorted_entries = sorted(entries, key=sort_key)

        total = 0.0
        for idx, entry in enumerate(sorted_entries, start=1):
            amount_str = entry.get("amount", "0")
            payment_date = entry.get("paymentDate", "Necunoscut")
            channel = entry.get("channel", "")

            try:
                amount_float = parse_romanian_amount(str(amount_str))
            except (ValueError, TypeError):
                amount_float = 0.0

            total += amount_float

            parsed_date = _parse_date_dmy(payment_date)
            if parsed_date:
                month_name = MONTHS_NUM_RO.get(parsed_date.month, "necunoscut")
            else:
                month_name = payment_date

            attrs[f"Compensație {idx} luna {month_name} ({channel})"] = (
                f"{format_ron(amount_float)} lei"
            )

        attrs["Compensații ANRE"] = len(sorted_entries)
        attrs["Sumă totală"] = f"{format_ron(total)} lei"
        attrs["attribution"] = ATTRIBUTION
        return attrs
