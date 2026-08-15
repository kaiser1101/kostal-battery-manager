#!/usr/bin/env python3
"""
Kostal Modbus TCP Client
Portiert von batcharge.py

Zwei grundverschiedene Steuerwege (siehe Kostal Modbus-Doku Kap. 3.4):

1. SETPOINT (Register 1034) - erzwingt einen Leistungsfluss.
   Negativ = Laden, Positiv = Entladen.
   ACHTUNG: Ein Ladesetpoint bei Nacht zieht die Energie aus dem NETZ.
   Nur fuer die Legacy-Preisstrategie gedacht.

2. LIMITS (Register 1038/1040/1042/1044) - begrenzen, was der
   Wechselrichter mit seiner EIGENEN Logik tun darf:
     1038  Max. Ladeleistung (W)
     1040  Max. Entladeleistung (W)
     1042  Minimum SOC (%)
     1044  Maximum SOC (%)
   Die interne Eigenverbrauchs-Optimierung laeuft weiter, nur eben
   innerhalb dieser Grenzen. Es entsteht KEINE Netzladung.
   Das ist der Weg fuer die prognosebasierte Strategie.
"""

import logging
from pymodbus.client.tcp import ModbusTcpClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadBuilder

logger = logging.getLogger(__name__)


class ModbusClient:
    """
    Modbus TCP Client for Kostal Plenticore Plus
    
    Schreibt Batterie-Ladeleistung auf Register 1034 (Float32)
    Negativ = Laden, Positiv = Entladen, 0 = Automatik
    """
    
    def __init__(self, inverter_ip, port=1502, slave_id=71, dry_run=False):
        """
        Initialize Modbus Client

        Args:
            inverter_ip: IP-Adresse des Wechselrichters
            port: Modbus TCP Port (Standard: 1502)
            slave_id: Modbus Slave ID (Standard: 71)
            dry_run: Wenn True, werden Schreibzugriffe NUR geloggt, nicht
                     ausgefuehrt. Lesezugriffe laufen normal weiter, damit
                     die Diagnose echte Werte sieht (Shadow-Modus).
        """
        self.inverter_ip = inverter_ip
        self.port = port
        self.slave_id = slave_id
        self.dry_run = dry_run
        self.client = None
        self.connected = False
        # Letzte geschriebene Limits - vermeidet redundante Writes und
        # dient dem Dashboard als Anzeige des aktuellen Plans.
        self.last_limits = {}
        # Zustand beim Start - Ziel fuer das Aufraeumen beim Beenden
        self.initial_limits = {}
        self._last_limit_refresh = None
        # Wortreihenfolge fuer Float32. Default des Wechselrichters ist
        # Little-endian (CDAB) = byteorder BIG + wordorder LITTLE.
        # Kann am Geraet auf Big-endian (ABCD) umgestellt sein, siehe
        # verify_byte_order().
        self._wordorder = Endian.LITTLE

        mode = " [DRY-RUN: keine Schreibzugriffe]" if dry_run else ""
        logger.info(f"Modbus Client initialized for {inverter_ip}:{port}, Slave ID {slave_id}{mode}")

    def _ensure_connection(self):
        """Stellt sicher, dass eine offene Verbindung existiert."""
        if not self.connected:
            if not self.connect():
                return False
        if not self.client.is_socket_open():
            logger.warning("Connection lost, reconnecting...")
            return self.connect()
        return True

    def _write_float32(self, address, value, label):
        """
        Schreibt einen Float32-Wert (Big Endian, Little Word Order).

        Zentraler Choke-Point fuer ALLE Schreibzugriffe - hier greift
        der Dry-Run.

        Returns:
            bool: True bei Erfolg (im Dry-Run immer True)
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Wuerde schreiben: {label} = {value} (Register {address})")
            return True

        try:
            if not self._ensure_connection():
                logger.error(f"Cannot write {label} - not connected")
                return False

            builder = BinaryPayloadBuilder(
                byteorder=Endian.BIG,
                wordorder=self._wordorder
            )
            builder.add_32bit_float(float(value))
            payload = builder.build()

            result = self.client.write_registers(
                address=address,
                values=payload,
                slave=self.slave_id,
                skip_encode=True
            )

            if result.isError():
                logger.error(f"Modbus write error for {label} (Register {address}): {result}")
                return False

            logger.info(f"{label} = {value} (Register {address})")
            return True

        except Exception as e:
            logger.error(f"Error writing {label} (Register {address}): {e}")
            return False
    
    def connect(self):
        """
        Establish Modbus TCP connection
        
        Returns:
            bool: True if successful
        """
        try:
            if self.client and self.client.is_socket_open():
                logger.debug("Modbus connection already established")
                return True
            
            self.client = ModbusTcpClient(
                self.inverter_ip,
                port=self.port,
                timeout=5
            )
            
            result = self.client.connect()
            self.connected = result
            
            if result:
                logger.info(f"Modbus connection established to {self.inverter_ip}:{self.port}")
            else:
                logger.error(f"Failed to connect to Modbus at {self.inverter_ip}:{self.port}")
            
            return result
            
        except Exception as e:
            logger.error(f"Modbus connection error: {e}")
            self.connected = False
            return False
    
    def disconnect(self):
        """Close Modbus connection"""
        try:
            if self.client:
                self.client.close()
                self.connected = False
                logger.info("Modbus connection closed")
        except Exception as e:
            logger.warning(f"Error closing Modbus connection: {e}")
    
    def write_battery_power(self, power_watts):
        """
        Write battery charge/discharge power to Register 1034
        
        Args:
            power_watts: Power in Watts
                        Negative = Charging (e.g., -3900 = charge with 3900W)
                        Positive = Discharging (e.g., 2000 = discharge with 2000W)
                        0 = Automatic mode (back to internal control)
        
        WARNUNG: Ein negativer Setpoint erzwingt Laden - nachts also aus
        dem Netz. Fuer die prognosebasierte Strategie stattdessen die
        Limit-Register verwenden (set_battery_limits).

        Returns:
            bool: True if successful
        """
        action = "Charging" if power_watts < 0 else "Discharging" if power_watts > 0 else "Automatic"
        return self._write_float32(1034, power_watts, f"Battery power setpoint {power_watts}W ({action})")

    # ------------------------------------------------------------------
    # Limit-basierte Steuerung (Kostal Modbus-Doku Kap. 3.4)
    # Begrenzt die interne Logik, statt Leistung zu erzwingen.
    # ------------------------------------------------------------------

    def set_max_charge_power(self, watts):
        """Register 1038: Max. Ladeleistung in W. 0 = Laden unterbinden."""
        return self._write_float32(1038, max(0.0, float(watts)), f"Max charge power {watts}W")

    def set_max_discharge_power(self, watts):
        """Register 1040: Max. Entladeleistung in W. 0 = Entladen unterbinden."""
        return self._write_float32(1040, max(0.0, float(watts)), f"Max discharge power {watts}W")

    def set_min_soc(self, percent):
        """Register 1042: Minimum SOC in %. Untergrenze fuer das Entladen."""
        value = min(100.0, max(0.0, float(percent)))
        return self._write_float32(1042, value, f"Min SOC {value}%")

    def set_max_soc(self, percent):
        """Register 1044: Maximum SOC in %. Obergrenze fuer das Laden."""
        value = min(100.0, max(0.0, float(percent)))
        return self._write_float32(1044, value, f"Max SOC {value}%")

    def set_battery_limits(self, max_charge_power=None, max_discharge_power=None,
                           min_soc=None, max_soc=None, force=False,
                           refresh_interval_s=600):
        """
        Schreibt mehrere Limits auf einmal.

        Schreibt nur Werte, die sich seit dem letzten Aufruf geaendert
        haben (ausser force=True), um den Wechselrichter nicht unnoetig
        mit identischen Writes zu belasten.

        Returns:
            dict: {'written': [...], 'failed': [...], 'skipped': [...]}
        """
        targets = [
            ('max_charge_power', max_charge_power, self.set_max_charge_power),
            ('max_discharge_power', max_discharge_power, self.set_max_discharge_power),
            ('min_soc', min_soc, self.set_min_soc),
            ('max_soc', max_soc, self.set_max_soc),
        ]

        # Die Kostal-Doku sagt fuer Kap. 3.3 ausdruecklich, dass Setpoints
        # einen Reset NICHT ueberleben; fuer die Limits in Kap. 3.4 schweigt
        # sie. Falls sie ebenfalls fluechtig sind, wuerde der Aenderungs-Cache
        # nach einem Reset des Wechselrichters nie neu schreiben. Deshalb
        # periodisch erzwungen neu schreiben.
        import time as _time
        nowts = _time.monotonic()
        if (self._last_limit_refresh is None or
                nowts - self._last_limit_refresh > refresh_interval_s):
            force = True
            self._last_limit_refresh = nowts

        report = {'written': [], 'failed': [], 'skipped': []}
        for name, value, setter in targets:
            if value is None:
                continue
            value = round(float(value), 1)
            if not force and self.last_limits.get(name) == value:
                report['skipped'].append(name)
                continue
            if setter(value):
                self.last_limits[name] = value
                report['written'].append(f"{name}={value}")
            else:
                report['failed'].append(name)

        return report

    def verify_byte_order(self):
        """
        Register 5: eingestellte MODBUS Byte Order des Wechselrichters.
            0x00 = Little-endian (CDAB)  -> Default
            0x01 = Big-endian (ABCD)     -> SunSpec-Einstellung

        Float-Register wuerden bei falscher Annahme voellig falsche Werte
        liefern - und beim SCHREIBEN eines SOC-Limits waere das gefaehrlich.
        Deshalb einmalig pruefen und die Wortreihenfolge anpassen.

        Returns:
            bool: True wenn die Reihenfolge sicher bestimmt werden konnte
        """
        raw = self.read_register(5, count=1, data_type='uint16')
        if raw is None:
            logger.warning("Byte Order (Register 5) nicht lesbar - bleibe beim "
                           "Default Little-endian (CDAB)")
            return False

        if raw == 0:
            self._wordorder = Endian.LITTLE
            logger.info("Byte Order: Little-endian (CDAB) - Default, passt zur Implementierung")
        elif raw == 1:
            self._wordorder = Endian.BIG
            logger.warning("Byte Order: Big-endian (ABCD/SunSpec) am Wechselrichter "
                           "eingestellt - Wortreihenfolge entsprechend umgestellt")
        else:
            logger.error(f"Unerwarteter Wert in Register 5: {raw} - bleibe beim Default")
            return False
        return True

    def release_limits(self, max_power=None):
        """
        Setzt die Grenzen auf unkritische Werte zurueck.

        Wichtig beim Beenden: Ein geschriebener Grenzwert PERSISTIERT im
        Wechselrichter. Stoppt das Add-on, waehrend z.B. ein niedriges
        Ladelimit gesetzt ist, bliebe die Batterie dauerhaft gedrosselt -
        ohne dass irgendwo ersichtlich waere, warum.

        Deshalb: SOC-Korridor auf den vollen Bereich, Leistungsgrenzen auf
        das Geraetemaximum. Damit verhaelt sich die Anlage wie ohne Add-on.
        """
        # Auf die beim Start vorgefundenen Werte zurueck, nicht auf 0/100:
        # min_soc=0 wuerde eine tiefere Entladung erlauben als die eigene
        # Einstellung des Nutzers im Kostal-Webinterface.
        power = max_power or self.initial_limits.get('max_charge_power') or 10000.0
        report = self.set_battery_limits(
            max_charge_power=power,
            max_discharge_power=self.initial_limits.get('max_discharge_power') or power,
            min_soc=self.initial_limits.get('min_soc', 10.0),
            max_soc=self.initial_limits.get('max_soc', 100.0),
            force=True,
        )
        logger.info(f"Grenzwerte freigegeben (Add-on beendet sich): {report['written']}")
        return report

    def read_battery_limits(self):
        """
        Liest die vier Limit-Register zurueck.

        Dient der Verifikation: akzeptiert der Wechselrichter unsere
        Writes ueberhaupt? Im Dry-Run zeigt das die echten Ist-Werte.

        Returns:
            dict: gelesene Werte (fehlende Register fehlen im dict)
        """
        registers = {
            'max_charge_power': 1038,
            'max_discharge_power': 1040,
            'min_soc': 1042,
            'max_soc': 1044,
        }
        values = {}
        for name, address in registers.items():
            value = self.read_register(address, count=2, data_type='float32')
            if value is not None:
                values[name] = round(value, 1)
        return values

    def read_battery_management_mode(self):
        """
        Register 1080 (U8, read-only): aktueller Batterie-Management-Modus.

        Returns:
            tuple: (raw_value, description) oder (None, 'unknown')
        """
        modes = {
            0: 'Kein externes Batteriemanagement',
            1: 'Extern via digital I/O',
            2: 'Extern via MODBUS',
        }
        raw = self.read_register(1080, count=1, data_type='uint16')
        if raw is None:
            return None, 'unknown'
        return raw, modes.get(raw, f'unbekannt ({raw})')

    def read_work_capacity(self):
        """Register 1068 (RO): nutzbare Batteriekapazitaet in Wh."""
        return self.read_register(1068, count=2, data_type='float32')
    
    def start_charging(self, power_watts):
        """
        Start charging battery
        
        Args:
            power_watts: Charging power in Watts (positive number, will be negated)
        
        Returns:
            bool: True if successful
        """
        # Ensure power is negative for charging
        charge_power = -abs(power_watts)
        return self.write_battery_power(charge_power)
    
    def stop_charging(self):
        """
        Stop charging - return to automatic mode
        
        Returns:
            bool: True if successful
        """
        return self.write_battery_power(0)
    
    def start_discharging(self, power_watts):
        """
        Start discharging battery
        
        Args:
            power_watts: Discharging power in Watts (positive number)
        
        Returns:
            bool: True if successful
        """
        # Ensure power is positive for discharging
        discharge_power = abs(power_watts)
        return self.write_battery_power(discharge_power)
    
    def read_register(self, address, count=2, data_type='float32'):
        """
        Read Modbus register(s)
        
        Args:
            address: Register address
            count: Number of registers to read
            data_type: Data type ('float32', 'int32', 'uint32', etc.)
        
        Returns:
            Value or None if failed
        """
        try:
            if not self.connected:
                if not self.connect():
                    return None
            
            result = self.client.read_holding_registers(
                address=address,
                count=count,
                slave=self.slave_id
            )
            
            if result.isError():
                logger.error(f"Modbus read error: {result}")
                return None

            # U8/U16 stehen in einem einzelnen Register - kein Decoder noetig
            if data_type in ('uint8', 'uint16'):
                return result.registers[0]

            # Parse based on data type
            from pymodbus.payload import BinaryPayloadDecoder
            decoder = BinaryPayloadDecoder.fromRegisters(
                result.registers,
                byteorder=Endian.BIG,
                wordorder=self._wordorder
            )
            
            if data_type == 'float32':
                return decoder.decode_32bit_float()
            elif data_type == 'int32':
                return decoder.decode_32bit_int()
            elif data_type == 'uint32':
                return decoder.decode_32bit_uint()
            else:
                logger.warning(f"Unknown data type: {data_type}")
                return None
                
        except Exception as e:
            logger.error(f"Error reading register {address}: {e}")
            return None
    
    def test_connection(self):
        """Test Modbus connection"""
        try:
            if self.connect():
                # Register 1068 = Battery work capacity in Wh (NICHT SOC -
                # das war in frueheren Versionen falsch beschriftet).
                capacity_wh = self.read_work_capacity()
                if capacity_wh is not None:
                    logger.info(f"Modbus test successful, Battery work capacity: {capacity_wh} Wh")
                    raw, mode = self.read_battery_management_mode()
                    logger.info(f"Battery management mode: {mode} (Register 1080 = {raw})")
                    return True
            return False
        except Exception as e:
            logger.error(f"Modbus test failed: {e}")
            return False
    
    def __del__(self):
        """Cleanup on destruction"""
        self.disconnect()
