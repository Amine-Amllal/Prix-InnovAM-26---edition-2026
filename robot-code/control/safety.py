# =============================================================================
# SIANA — control/safety.py
# Gestionnaire de sécurité : arrêt d'urgence physique, obstacles,
# batterie faible, watchdog de connexion, limites de fosse
# =============================================================================

import asyncio
import threading
import time
import logging

logger = logging.getLogger("siana.safety")

try:
    import Jetson.GPIO as GPIO
    _GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    _GPIO_AVAILABLE = False


class SafetyManager:
    """
    Surveillance et actions de sécurité.

    Surveillance en parallèle :
      1. Bouton arrêt d'urgence PHYSIQUE (GPIO interrupt, réponse < 1 ms)
      2. Obstacles ultrason (via ObstacleManager callbacks)
      3. Batterie faible (via BatteryMonitor callbacks)
      4. Watchdog connexion WiFi (arrêt si perte > N secondes)
      5. Limites de fosse (distance max inspection)

    Toutes les actions de sécurité sont centralisées ici pour
    garantir qu'aucun composant ne peut contourner l'arrêt d'urgence.
    """

    WATCHDOG_TIMEOUT_S  = 15    # secondes sans commande → arrêt sécurité
    FOSSE_LENGTH_M      = 200   # longueur max fosse (m)

    def __init__(self, motors, leds, sensors, navigation=None):
        """
        :param motors:     hardware.motors.MotorController
        :param leds:       hardware.leds.LedController
        :param sensors:    (ObstacleManager, BatteryMonitor) tuple
        :param navigation: control.navigation.NavigationController (optionnel)
        """
        self._motors  = motors
        self._leds    = leds
        self._obstacle_mgr, self._battery_mon = sensors
        self._nav     = navigation

        self._estop_active   = False
        self._last_command_t = time.time()
        self._watchdog_active = True

        # Enregistrement des callbacks capteurs
        self._obstacle_mgr.on_critical(self._on_obstacle_critical)
        self._obstacle_mgr.on_warning(self._on_obstacle_warning)
        self._battery_mon.on_low_battery(self._on_low_battery)

        # Bouton physique E-STOP
        self._setup_estop_gpio()

        # Watchdog connexion
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True
        )
        self._watchdog_thread.start()

        logger.info("SafetyManager initialisé")

    # ── E-STOP GPIO physique ──────────────────────────────────────────────────

    def _setup_estop_gpio(self):
        import config as cfg
        if not _GPIO_AVAILABLE:
            logger.warning("GPIO non disponible — bouton E-STOP matériel désactivé")
            return
        GPIO.setup(cfg.ESTOP_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(
            cfg.ESTOP_PIN,
            GPIO.FALLING,           # bouton NO → front descendant
            callback=self._on_estop_gpio,
            bouncetime=200          # anti-rebond 200 ms
        )
        logger.info("Bouton E-STOP configuré sur GPIO%d", cfg.ESTOP_PIN)

    def _on_estop_gpio(self, _channel):
        """Interrupt GPIO — exécuté immédiatement lors du pressage bouton."""
        logger.critical("BOUTON E-STOP PHYSIQUE PRESSÉ")
        self.trigger_emergency("Bouton E-STOP physique")

    # ── Callbacks obstacles ───────────────────────────────────────────────────

    def _on_obstacle_critical(self, sensor_name: str, dist_cm: float):
        logger.critical("Obstacle critique [%s] : %.1f cm", sensor_name, dist_cm)
        # Arrêt uniquement si le robot se déplace dans la direction concernée
        from control.navigation import RobotState
        if self._nav:
            state = self._nav._state
            moving_forward  = state == RobotState.MOVING_FORWARD  and sensor_name == "front"
            moving_backward = state == RobotState.MOVING_BACKWARD and sensor_name == "rear"
            if moving_forward or moving_backward:
                self.trigger_emergency(f"Obstacle critique [{sensor_name}] : {dist_cm:.0f} cm")
        else:
            self._motors.brake()

    def _on_obstacle_warning(self, sensor_name: str, dist_cm: float):
        logger.warning("Obstacle proche [%s] : %.1f cm — ralentissement", sensor_name, dist_cm)
        self._leds.set_state("warning")
        # Réduction vitesse automatique
        from control.navigation import RobotState
        if self._nav and self._nav._state in (
            RobotState.MOVING_FORWARD, RobotState.MOVING_BACKWARD
        ):
            new_speed = max(20.0, self._nav._speed_pct * 0.5)
            self._motors.set_speed_pct(new_speed)

    # ── Callback batterie ─────────────────────────────────────────────────────

    def _on_low_battery(self, soc_pct: float):
        logger.warning("Batterie faible : %.1f%%", soc_pct)
        self._leds.set_state("battery_low")
        if soc_pct < 5.0:
            logger.critical("Batterie critique < 5%% — arrêt de sécurité")
            self.trigger_emergency(f"Batterie critique : {soc_pct:.1f}%")

    # ── Watchdog connexion ────────────────────────────────────────────────────

    def _watchdog_loop(self):
        """
        Si aucune commande reçue depuis WATCHDOG_TIMEOUT_S secondes,
        le robot s'arrête automatiquement (sécurité perte signal WiFi).
        """
        while self._watchdog_active:
            time.sleep(2.0)
            if not self._estop_active:
                elapsed = time.time() - self._last_command_t
                if elapsed > self.WATCHDOG_TIMEOUT_S:
                    logger.warning(
                        "Watchdog : aucune commande depuis %.0fs — arrêt sécurité",
                        elapsed
                    )
                    self._motors.stop()
                    if self._nav:
                        from control.navigation import RobotState
                        self._nav._state = RobotState.IDLE
                    self._leds.set_state("warning")

    def heartbeat(self):
        """Appelé à chaque réception de commande ou heartbeat WebSocket."""
        self._last_command_t = time.time()

    # ── Limite de fosse ───────────────────────────────────────────────────────

    def check_fosse_limits(self, distance_m: float):
        """
        Vérifie que le robot ne dépasse pas la longueur de la fosse.
        À appeler périodiquement depuis la boucle principale.
        """
        if distance_m >= self.FOSSE_LENGTH_M - 2.0:
            logger.warning("Limite fosse proche : %.1f m / %d m", distance_m, self.FOSSE_LENGTH_M)
            self._motors.stop()
            self._leds.flash("orange", times=5)
        if distance_m >= self.FOSSE_LENGTH_M:
            logger.critical("Limite fosse atteinte — arrêt sécurité")
            self.trigger_emergency("Limite fosse 200 m atteinte")

    # ── Arrêt d'urgence centralisé ────────────────────────────────────────────

    def trigger_emergency(self, reason: str = ""):
        """
        Déclenche l'arrêt d'urgence depuis n'importe quelle source.
        Idempotent : sans effet si déjà actif.
        """
        if self._estop_active:
            return
        self._estop_active = True
        logger.critical("ARRÊT D'URGENCE : %s", reason)

        # 1. Couper les moteurs immédiatement
        self._motors.emergency_stop()

        # 2. Signalisation rouge
        self._leds.set_state("emergency")

        # 3. Mettre à jour l'état navigation
        if self._nav:
            from control.navigation import RobotState
            self._nav._state = RobotState.EMERGENCY_STOP

    def release_emergency(self, reason: str = ""):
        """
        Libère le verrouillage E-STOP.
        Ne peut être fait que par l'opérateur (commande explicite).
        """
        if not self._estop_active:
            return
        logger.warning("E-STOP relâché : %s", reason)
        self._estop_active = False
        self._motors.release_emergency()
        self._leds.set_state("ready")
        if self._nav:
            from control.navigation import RobotState
            self._nav._state = RobotState.IDLE
        self._last_command_t = time.time()   # reset watchdog

    @property
    def is_emergency(self) -> bool:
        return self._estop_active

    def is_path_clear(self, direction: str = "front") -> bool:
        """Délègue à ObstacleManager."""
        return self._obstacle_mgr.is_path_clear(direction)

    def set_navigation(self, nav):
        """Liaison tardive NavigationController (évite dépendance circulaire)."""
        self._nav = nav

    def get_telemetry(self) -> dict:
        return {
            "estop":           self._estop_active,
            "watchdog_ok":     (time.time() - self._last_command_t) < self.WATCHDOG_TIMEOUT_S,
            "last_cmd_ago_s":  round(time.time() - self._last_command_t, 1),
            "obstacles":       self._obstacle_mgr.get_readings(),
        }

    def shutdown(self):
        self._watchdog_active = False
