# =============================================================================
# SIANA — hardware/leds.py
# Signalisation LED d'état (vert/orange/rouge) + éclairage sous-caisse PWM
# =============================================================================

import time
import threading
import logging

logger = logging.getLogger("siana.leds")

try:
    import Jetson.GPIO as GPIO
    _GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    _GPIO_AVAILABLE = False

# ─── États robot → pattern LED ────────────────────────────────────────────────
# Chaque pattern : (vert, orange, rouge, fréquence clignotement Hz, 0=fixe)
LED_PATTERNS = {
    "idle":       (False, False, False, 0),    # éteint
    "ready":      (True,  False, False, 0),    # vert fixe : prêt
    "moving":     (True,  False, False, 2),    # vert clignotant : en déplacement
    "warning":    (False, True,  False, 1),    # orange clignotant : avertissement
    "battery_low":(False, True,  False, 3),    # orange rapide : batterie faible
    "emergency":  (False, False, True,  5),    # rouge rapide : arrêt urgence
    "fault":      (False, False, True,  1),    # rouge lent : défaut
    "paused":     (True,  True,  False, 0.5),  # vert+orange : pause inspection
}


class LedController:
    """
    Gestion des LEDs de signalisation et de l'éclairage sous-caisse.
    Supporte les patterns fixes et clignotants.
    """

    def __init__(self):
        import config as cfg
        self.cfg = cfg

        self._green_pin  = cfg.LED_GREEN_PIN
        self._orange_pin = cfg.LED_ORANGE_PIN
        self._red_pin    = cfg.LED_RED_PIN

        self._current_state = "idle"
        self._blink_thread  = None
        self._blink_running = False
        self._lock = threading.Lock()

        # Éclairage sous-caisse PWM
        self._lighting_duty = cfg.LED_LIGHTING_DEFAULT
        self._lighting_pwm  = None

        if _GPIO_AVAILABLE:
            for pin in (self._green_pin, self._orange_pin, self._red_pin):
                GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

            GPIO.setup(cfg.LED_LIGHTING_PWM_PIN, GPIO.OUT)
            self._lighting_pwm = GPIO.PWM(cfg.LED_LIGHTING_PWM_PIN, cfg.LED_LIGHTING_FREQ)
            self._lighting_pwm.start(self._lighting_duty)

        logger.info("LedController initialisé")

    # ── LEDs état ─────────────────────────────────────────────────────────────

    def set_state(self, state_name: str):
        """
        Applique un pattern d'état prédéfini.
        state_name : voir LED_PATTERNS
        """
        if state_name not in LED_PATTERNS:
            logger.warning("État LED inconnu : %s", state_name)
            return

        logger.debug("LED → %s", state_name)
        with self._lock:
            self._current_state = state_name

        self._stop_blink()
        pattern = LED_PATTERNS[state_name]
        green, orange, red, freq = pattern

        if freq == 0:
            self._apply(green, orange, red)
        else:
            self._blink_running = True
            self._blink_thread = threading.Thread(
                target=self._blink_loop,
                args=(green, orange, red, freq),
                daemon=True
            )
            self._blink_thread.start()

    def _stop_blink(self):
        self._blink_running = False
        if self._blink_thread and self._blink_thread.is_alive():
            self._blink_thread.join(timeout=1.0)

    def _blink_loop(self, green: bool, orange: bool, red: bool, freq: float):
        period = 1.0 / freq
        while self._blink_running:
            self._apply(green, orange, red)
            time.sleep(period / 2)
            self._apply(False, False, False)
            time.sleep(period / 2)

    def _apply(self, green: bool, orange: bool, red: bool):
        if not _GPIO_AVAILABLE:
            return
        GPIO.output(self._green_pin,  GPIO.HIGH if green  else GPIO.LOW)
        GPIO.output(self._orange_pin, GPIO.HIGH if orange else GPIO.LOW)
        GPIO.output(self._red_pin,    GPIO.HIGH if red    else GPIO.LOW)

    def flash(self, color: str, times: int = 3, duration_s: float = 0.1):
        """Flash rapide d'une couleur (feedback immédiat, non bloquant)."""
        pin_map = {
            "green":  self._green_pin,
            "orange": self._orange_pin,
            "red":    self._red_pin,
        }
        pin = pin_map.get(color)
        if pin is None or not _GPIO_AVAILABLE:
            return

        def _do():
            for _ in range(times):
                GPIO.output(pin, GPIO.HIGH)
                time.sleep(duration_s)
                GPIO.output(pin, GPIO.LOW)
                time.sleep(duration_s)

        threading.Thread(target=_do, daemon=True).start()

    @property
    def current_state(self) -> str:
        return self._current_state

    # ── Éclairage sous-caisse ─────────────────────────────────────────────────

    def set_lighting(self, duty_pct: float):
        """Règle l'intensité de l'éclairage : 0 = éteint, 100 = max."""
        duty_pct = max(0.0, min(100.0, duty_pct))
        self._lighting_duty = duty_pct
        if self._lighting_pwm:
            self._lighting_pwm.ChangeDutyCycle(duty_pct)
        logger.debug("Éclairage sous-caisse : %.0f%%", duty_pct)

    def lighting_on(self):
        self.set_lighting(self.cfg.LED_LIGHTING_DEFAULT)

    def lighting_off(self):
        self.set_lighting(0)

    @property
    def lighting_duty(self) -> float:
        return self._lighting_duty

    def get_telemetry(self) -> dict:
        return {
            "led_state":      self._current_state,
            "lighting_pct":   self._lighting_duty,
        }

    def cleanup(self):
        self._stop_blink()
        if _GPIO_AVAILABLE:
            self._apply(False, False, False)
            if self._lighting_pwm:
                self._lighting_pwm.stop()
        logger.info("LedController nettoyé")
