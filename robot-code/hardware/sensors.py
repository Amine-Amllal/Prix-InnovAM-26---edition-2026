# =============================================================================
# SIANA — hardware/sensors.py
# Capteurs : ultrasons HC-SR04 (obstacles) + INA219 (batterie)
# =============================================================================

import time
import asyncio
import threading
import logging

logger = logging.getLogger("siana.sensors")

try:
    import Jetson.GPIO as GPIO
    _GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    _GPIO_AVAILABLE = False
    logger.warning("Jetson.GPIO non disponible — capteurs simulés")

try:
    from ina219 import INA219
    _INA_AVAILABLE = True
except ImportError:
    _INA_AVAILABLE = False
    logger.warning("ina219 non disponible — batterie simulée")


# ─── Ultrasons HC-SR04 ────────────────────────────────────────────────────────

class UltrasonicSensor:
    """
    Capteur ultrason HC-SR04.
    Mesure : pulse TRIG 10µs → mesure durée ECHO → distance = vitesse_son × t / 2
    """
    SOUND_SPEED_CM_S = 34300  # cm/s à 20°C

    def __init__(self, name: str, trig_pin: int, echo_pin: int, timeout_s: float = 0.03):
        self.name = name
        self._trig = trig_pin
        self._echo = echo_pin
        self._timeout = timeout_s
        self._lock = threading.Lock()
        self._last_cm = 999.0   # valeur par défaut = voie libre

        if _GPIO_AVAILABLE:
            GPIO.setup(trig_pin, GPIO.OUT, initial=GPIO.LOW)
            GPIO.setup(echo_pin, GPIO.IN)

    def measure_cm(self) -> float:
        """
        Déclenche une mesure et retourne la distance en cm.
        Thread-safe. En cas d'erreur retourne 999.0 (voie libre).
        """
        if not _GPIO_AVAILABLE:
            # Simulation : retourne une distance aléatoire plausible
            import random
            return round(60 + random.gauss(0, 10), 1)

        with self._lock:
            # Impulsion TRIG
            GPIO.output(self._trig, GPIO.HIGH)
            time.sleep(0.00001)  # 10 µs
            GPIO.output(self._trig, GPIO.LOW)

            # Attente front montant ECHO
            t_start = time.time()
            while GPIO.input(self._echo) == 0:
                if time.time() - t_start > self._timeout:
                    return 999.0

            pulse_start = time.time()

            # Attente front descendant ECHO
            while GPIO.input(self._echo) == 1:
                if time.time() - pulse_start > self._timeout:
                    return 999.0

            pulse_end = time.time()

            duration = pulse_end - pulse_start
            distance_cm = round((duration * self.SOUND_SPEED_CM_S) / 2.0, 1)
            self._last_cm = distance_cm
            return distance_cm

    @property
    def last_cm(self) -> float:
        return self._last_cm


class ObstacleManager:
    """
    Gestion de l'ensemble des capteurs ultrason.
    Scrute en continu dans un thread dédié.
    Déclenche des callbacks d'alerte.
    """

    def __init__(self):
        import config as cfg
        self.cfg = cfg
        self._sensors = {
            "front": UltrasonicSensor("front", cfg.US_FRONT_TRIG, cfg.US_FRONT_ECHO),
            "rear":  UltrasonicSensor("rear",  cfg.US_REAR_TRIG,  cfg.US_REAR_ECHO),
            "left":  UltrasonicSensor("left",  cfg.US_LEFT_TRIG,  cfg.US_LEFT_ECHO),
        }
        self._readings = {k: 999.0 for k in self._sensors}
        self._callbacks_warning  = []   # callable(sensor_name, dist_cm)
        self._callbacks_critical = []   # callable(sensor_name, dist_cm)
        self._running = False
        self._thread  = None

    def on_warning(self, cb):
        """Enregistre un callback déclenché à distance d'avertissement."""
        self._callbacks_warning.append(cb)

    def on_critical(self, cb):
        """Enregistre un callback déclenché à distance critique → arrêt requis."""
        self._callbacks_critical.append(cb)

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._thread.start()
        logger.info("ObstacleManager démarré")

    def stop(self):
        self._running = False

    def _scan_loop(self):
        cfg = self.cfg
        while self._running:
            for name, sensor in self._sensors.items():
                d = sensor.measure_cm()
                self._readings[name] = d
                if d < cfg.US_MIN_DISTANCE_CM:
                    for cb in self._callbacks_critical:
                        try:
                            cb(name, d)
                        except Exception:
                            pass
                elif d < cfg.US_WARNING_DISTANCE_CM:
                    for cb in self._callbacks_warning:
                        try:
                            cb(name, d)
                        except Exception:
                            pass
            time.sleep(0.05)   # 20 Hz

    def get_readings(self) -> dict:
        return dict(self._readings)

    def is_path_clear(self, direction: str = "front") -> bool:
        """True si la voie est libre (distance > seuil critique)."""
        return self._readings.get(direction, 999.0) > self.cfg.US_MIN_DISTANCE_CM


# ─── Batterie INA219 ──────────────────────────────────────────────────────────

class BatteryMonitor:
    """
    Surveillance batterie via INA219 (I2C).
    Mesure : tension bus (V), courant (A), puissance (W).
    Calcul : SOC (State of Charge) en %.
    """

    def __init__(self):
        import config as cfg
        self.cfg = cfg
        self._ina = None
        self._soc = 100.0
        self._voltage = cfg.BATTERY_NOMINAL_V
        self._current_a = 0.0
        self._power_w   = 0.0
        self._lock = threading.Lock()
        self._running = False
        self._thread  = None
        self._callbacks_low = []  # callable(soc_pct)

        if _INA_AVAILABLE:
            try:
                self._ina = INA219(
                    shunt_ohms=cfg.BATTERY_SHUNT_OHM,
                    max_expected_amps=cfg.BATTERY_MAX_EXPECTED_A,
                    address=cfg.BATTERY_I2C_ADDR,
                )
                self._ina.configure(
                    voltage_range=INA219.RANGE_32V,
                    gain=INA219.GAIN_AUTO,
                    bus_adc=INA219.ADC_128SAMP,
                    shunt_adc=INA219.ADC_128SAMP,
                )
                logger.info("INA219 initialisé sur 0x%02X", cfg.BATTERY_I2C_ADDR)
            except Exception as e:
                logger.error("Erreur INA219 : %s", e)
                self._ina = None

    def on_low_battery(self, cb):
        self._callbacks_low.append(cb)

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("BatteryMonitor démarré")

    def stop(self):
        self._running = False

    def _monitor_loop(self):
        cfg = self.cfg
        alerted = False
        while self._running:
            try:
                if self._ina:
                    v = self._ina.voltage()
                    i = self._ina.current() / 1000.0    # mA → A
                    p = self._ina.power()   / 1000.0    # mW → W
                else:
                    # Simulation : décharge linéaire lente
                    import random
                    v = self._voltage - random.uniform(0, 0.001)
                    i = round(random.uniform(1.5, 3.5), 2)
                    p = round(v * i, 1)

                # SOC = interpolation linéaire Vmin…Vmax → 0…100%
                soc = ((v - cfg.BATTERY_MIN_V) /
                       (cfg.BATTERY_MAX_V - cfg.BATTERY_MIN_V)) * 100.0
                soc = max(0.0, min(100.0, round(soc, 1)))

                with self._lock:
                    self._voltage   = v
                    self._current_a = i
                    self._power_w   = p
                    self._soc       = soc

                if soc < cfg.BATTERY_LOW_THRESHOLD and not alerted:
                    alerted = True
                    logger.warning("BATTERIE FAIBLE : %.1f%%", soc)
                    for cb in self._callbacks_low:
                        try:
                            cb(soc)
                        except Exception:
                            pass
                elif soc >= cfg.BATTERY_LOW_THRESHOLD:
                    alerted = False

            except Exception as e:
                logger.error("Erreur lecture batterie : %s", e)

            time.sleep(2.0)   # lecture toutes les 2 s (INA219 lent en mode haute précision)

    @property
    def soc(self) -> float:
        return self._soc

    @property
    def voltage(self) -> float:
        return self._voltage

    @property
    def current_a(self) -> float:
        return self._current_a

    def get_telemetry(self) -> dict:
        with self._lock:
            return {
                "soc_pct":    self._soc,
                "voltage_v":  round(self._voltage,   2),
                "current_a":  round(self._current_a, 3),
                "power_w":    round(self._power_w,   1),
            }
