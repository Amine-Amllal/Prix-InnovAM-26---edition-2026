# =============================================================================
# SIANA — hardware/motors.py
# Contrôle moteurs DC — Traction différentielle (differential drive)
# Matériel : H-Bridge L298N ou IBT-2 (haute puissance, recommandé)
# =============================================================================

import threading
import time
import logging
import math

logger = logging.getLogger("siana.motors")

# ── Tentative import RPi.GPIO ──────────────────────────────────────────────
try:
    import Jetson.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    _GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    logger.warning("Jetson.GPIO non disponible — mode simulation activé")
    _GPIO_AVAILABLE = False


class PWMChannel:
    """Abstraction d'un canal PWM matériel ou simulé."""

    def __init__(self, pin: int, frequency: int = 20000):
        self.pin = pin
        self._duty = 0.0
        if _GPIO_AVAILABLE:
            GPIO.setup(pin, GPIO.OUT)
            self._pwm = GPIO.PWM(pin, frequency)
            self._pwm.start(0)
        else:
            self._pwm = None

    def set_duty(self, duty: float):
        """duty : 0.0 – 100.0 (%)"""
        duty = max(0.0, min(100.0, duty))
        self._duty = duty
        if self._pwm:
            self._pwm.ChangeDutyCycle(duty)

    @property
    def duty(self) -> float:
        return self._duty

    def stop(self):
        self.set_duty(0)
        if self._pwm:
            self._pwm.stop()


class MotorChannel:
    """
    Contrôle d'un moteur DC via pont-H.
    Brochage :
        IN1 HIGH + IN2 LOW  → marche avant
        IN1 LOW  + IN2 HIGH → marche arrière
        IN1 LOW  + IN2 LOW  → roue libre
        IN1 HIGH + IN2 HIGH → freinage actif
    """

    def __init__(self, name: str, pwm_pin: int, in1_pin: int, in2_pin: int,
                 pwm_freq: int = 20000, inverted: bool = False):
        self.name = name
        self.inverted = inverted
        self._speed = 0.0          # -100 … +100 %
        self._pwm = PWMChannel(pwm_pin, pwm_freq)

        if _GPIO_AVAILABLE:
            GPIO.setup(in1_pin, GPIO.OUT)
            GPIO.setup(in2_pin, GPIO.OUT)
        self._in1 = in1_pin
        self._in2 = in2_pin

    def _set_direction(self, forward: bool):
        if not _GPIO_AVAILABLE:
            return
        if forward ^ self.inverted:
            GPIO.output(self._in1, GPIO.HIGH)
            GPIO.output(self._in2, GPIO.LOW)
        else:
            GPIO.output(self._in1, GPIO.LOW)
            GPIO.output(self._in2, GPIO.HIGH)

    def set_speed(self, speed: float):
        """
        speed : -100.0 (plein arrière) … +100.0 (plein avant)
        0.0 = frein actif
        """
        speed = max(-100.0, min(100.0, speed))
        self._speed = speed
        if speed == 0:
            self.brake()
            return
        self._set_direction(speed > 0)
        self._pwm.set_duty(abs(speed))

    def brake(self):
        """Freinage actif (court-circuit bobine moteur)."""
        self._speed = 0
        self._pwm.stop()
        if _GPIO_AVAILABLE:
            GPIO.output(self._in1, GPIO.HIGH)
            GPIO.output(self._in2, GPIO.HIGH)

    def coast(self):
        """Roue libre (coupure alimentation)."""
        self._speed = 0
        self._pwm.stop()
        if _GPIO_AVAILABLE:
            GPIO.output(self._in1, GPIO.LOW)
            GPIO.output(self._in2, GPIO.LOW)

    @property
    def speed(self) -> float:
        return self._speed

    def cleanup(self):
        self.coast()
        self._pwm.stop()


class MotorController:
    """
    Contrôleur de traction différentielle pour SIANA.
    Expose les méthodes de haut niveau : forward, backward, turn, stop.
    Intègre la rampe d'accélération douce et les encodeurs odométriques.
    """

    from config import (
        MOTOR_LEFT_PWM,  MOTOR_LEFT_IN1,  MOTOR_LEFT_IN2,
        MOTOR_RIGHT_PWM, MOTOR_RIGHT_IN1, MOTOR_RIGHT_IN2,
        ENCODER_LEFT_A,  ENCODER_LEFT_B,
        ENCODER_RIGHT_A, ENCODER_RIGHT_B,
        ENCODER_TICKS_PER_REV, WHEEL_DIAMETER_MM, WHEEL_BASE_MM,
        SPEED_MIN_PERCENT, SPEED_MAX_PERCENT, SPEED_DEFAULT,
        TURN_SPEED_FACTOR, RAMP_STEP, RAMP_INTERVAL_MS,
    ) if False else None  # évite l'exécution au niveau module

    def __init__(self):
        import config as cfg
        self.cfg = cfg

        self._left  = MotorChannel("L", cfg.MOTOR_LEFT_PWM,  cfg.MOTOR_LEFT_IN1,  cfg.MOTOR_LEFT_IN2)
        self._right = MotorChannel("R", cfg.MOTOR_RIGHT_PWM, cfg.MOTOR_RIGHT_IN1, cfg.MOTOR_RIGHT_IN2,
                                   inverted=True)  # moteur droit souvent câblé en sens inverse

        # Cibles de vitesse actuelles (avant rampe)
        self._target_left  = 0.0
        self._target_right = 0.0
        # Vitesses courantes (après rampe)
        self._current_left  = 0.0
        self._current_right = 0.0

        # Odométrie
        self._ticks_left  = 0
        self._ticks_right = 0
        self._odometry_lock = threading.Lock()
        self._dist_m   = 0.0   # distance totale parcourue (m)
        self._heading  = 0.0   # cap en degrés (0 = avant)

        # Rampe d'accélération
        self._ramp_active = True
        self._ramp_thread = threading.Thread(target=self._ramp_loop, daemon=True)
        self._ramp_thread.start()

        self._emergency = False

        # Attacher les interruptions encodeurs
        self._setup_encoders()

        logger.info("MotorController initialisé")

    # ── Encodeurs ─────────────────────────────────────────────────────────────

    def _setup_encoders(self):
        cfg = self.cfg
        if not _GPIO_AVAILABLE:
            return
        for pin in (cfg.ENCODER_LEFT_A, cfg.ENCODER_LEFT_B,
                    cfg.ENCODER_RIGHT_A, cfg.ENCODER_RIGHT_B):
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(cfg.ENCODER_LEFT_A,  GPIO.RISING, callback=self._tick_left)
        GPIO.add_event_detect(cfg.ENCODER_RIGHT_A, GPIO.RISING, callback=self._tick_right)

    def _tick_left(self, _channel):
        direction = 1 if self._current_left >= 0 else -1
        with self._odometry_lock:
            self._ticks_left += direction

    def _tick_right(self, _channel):
        direction = 1 if self._current_right >= 0 else -1
        with self._odometry_lock:
            self._ticks_right += direction

    def update_odometry(self):
        """
        Calcul odométrique différentiel.
        Appelé périodiquement par la boucle principale.
        """
        cfg = self.cfg
        with self._odometry_lock:
            tl = self._ticks_left
            tr = self._ticks_right
            self._ticks_left  = 0
            self._ticks_right = 0

        wheel_circ = math.pi * (cfg.WHEEL_DIAMETER_MM / 1000.0)   # m
        dist_l = (tl / cfg.ENCODER_TICKS_PER_REV) * wheel_circ
        dist_r = (tr / cfg.ENCODER_TICKS_PER_REV) * wheel_circ

        dist_center = (dist_l + dist_r) / 2.0
        delta_theta  = math.degrees((dist_r - dist_l) / (cfg.WHEEL_BASE_MM / 1000.0))

        self._dist_m   += abs(dist_center)
        self._heading   = (self._heading + delta_theta) % 360

        return {
            "distance_m": round(self._dist_m, 3),
            "heading_deg": round(self._heading, 1),
        }

    def reset_odometry(self):
        with self._odometry_lock:
            self._ticks_left = 0
            self._ticks_right = 0
            self._dist_m  = 0.0
            self._heading = 0.0

    # ── Rampe d'accélération ──────────────────────────────────────────────────

    def _ramp_loop(self):
        cfg = self.cfg
        interval = cfg.RAMP_INTERVAL_MS / 1000.0
        step     = cfg.RAMP_STEP

        while self._ramp_active:
            if not self._emergency:
                for side in ('left', 'right'):
                    target  = self._target_left  if side == 'left' else self._target_right
                    current = self._current_left if side == 'left' else self._current_right

                    if abs(current - target) < step:
                        next_val = target
                    elif current < target:
                        next_val = current + step
                    else:
                        next_val = current - step

                    if side == 'left':
                        self._current_left = next_val
                        self._left.set_speed(next_val)
                    else:
                        self._current_right = next_val
                        self._right.set_speed(next_val)

            time.sleep(interval)

    def _set_targets(self, left: float, right: float):
        if self._emergency:
            return
        self._target_left  = max(-self.cfg.SPEED_MAX_PERCENT,
                                  min(self.cfg.SPEED_MAX_PERCENT, left))
        self._target_right = max(-self.cfg.SPEED_MAX_PERCENT,
                                  min(self.cfg.SPEED_MAX_PERCENT, right))

    # ── API mouvement de haut niveau ──────────────────────────────────────────

    def forward(self, speed: float = None):
        """Avance tout droit."""
        s = speed if speed is not None else self.cfg.SPEED_DEFAULT
        logger.debug("forward @ %.0f%%", s)
        self._set_targets(s, s)

    def backward(self, speed: float = None):
        """Recule tout droit."""
        s = speed if speed is not None else self.cfg.SPEED_DEFAULT
        logger.debug("backward @ %.0f%%", s)
        self._set_targets(-s, -s)

    def turn_left(self, speed: float = None):
        """Virage à gauche (roue droite avance, gauche ralentit)."""
        s = speed if speed is not None else self.cfg.SPEED_DEFAULT
        tf = self.cfg.TURN_SPEED_FACTOR
        logger.debug("turn_left @ %.0f%%", s)
        self._set_targets(s * tf, s)

    def turn_right(self, speed: float = None):
        """Virage à droite."""
        s = speed if speed is not None else self.cfg.SPEED_DEFAULT
        tf = self.cfg.TURN_SPEED_FACTOR
        logger.debug("turn_right @ %.0f%%", s)
        self._set_targets(s, s * tf)

    def pivot_left(self, speed: float = None):
        """Rotation en place vers la gauche (pivotement différentiel)."""
        s = speed if speed is not None else self.cfg.SPEED_DEFAULT * 0.5
        self._set_targets(-s, s)

    def pivot_right(self, speed: float = None):
        """Rotation en place vers la droite."""
        s = speed if speed is not None else self.cfg.SPEED_DEFAULT * 0.5
        self._set_targets(s, -s)

    def set_speed_pct(self, speed_pct: float):
        """Règle la vitesse des deux moteurs (directionnalité maintenue)."""
        # Rééchelonne sans changer le signe actuel
        l_sign = 1 if self._target_left  >= 0 else -1
        r_sign = 1 if self._target_right >= 0 else -1
        s = max(self.cfg.SPEED_MIN_PERCENT, abs(speed_pct))
        self._set_targets(l_sign * s, r_sign * s)

    def stop(self):
        """Arrêt progressif (rampe vers 0)."""
        logger.info("Arrêt progressif")
        self._set_targets(0, 0)

    def brake(self):
        """Freinage immédiat (sans attendre la rampe)."""
        logger.info("Frein immédiat")
        self._target_left  = 0
        self._target_right = 0
        self._current_left  = 0
        self._current_right = 0
        self._left.brake()
        self._right.brake()

    def emergency_stop(self):
        """ARRÊT D'URGENCE — coupe alimentation moteurs immédiatement."""
        logger.critical("ARRÊT D'URGENCE MOTEURS")
        self._emergency = True
        self._target_left   = 0
        self._target_right  = 0
        self._current_left  = 0
        self._current_right = 0
        self._left.coast()
        self._right.coast()

    def release_emergency(self):
        """Libère le verrouillage arrêt d'urgence (après résolution de la cause)."""
        logger.warning("Arrêt d'urgence relâché — vérifier l'environnement !")
        self._emergency = False

    @property
    def is_emergency(self) -> bool:
        return self._emergency

    @property
    def distance_m(self) -> float:
        return self._dist_m

    @property
    def heading_deg(self) -> float:
        return self._heading

    def get_telemetry(self) -> dict:
        return {
            "speed_left":  round(self._current_left,  1),
            "speed_right": round(self._current_right, 1),
            "distance_m":  round(self._dist_m,         3),
            "heading_deg": round(self._heading,         1),
            "emergency":   self._emergency,
        }

    def cleanup(self):
        self._ramp_active = False
        self._left.cleanup()
        self._right.cleanup()
        if _GPIO_AVAILABLE:
            GPIO.cleanup()
        logger.info("MotorController nettoyé")
