# =============================================================================
# SIANA — control/navigation.py
# Couche navigation : interprète les commandes opérateur
# et traduit en ordres moteurs avec contrôles de sécurité
# =============================================================================

import asyncio
import logging
import time
from enum import Enum, auto

logger = logging.getLogger("siana.navigation")


class RobotState(Enum):
    IDLE           = auto()   # robot arrêté, en attente
    MOVING_FORWARD = auto()   # avance
    MOVING_BACKWARD= auto()   # recule
    TURNING_LEFT   = auto()   # vire gauche
    TURNING_RIGHT  = auto()   # vire droite
    PIVOT_LEFT     = auto()   # pivote gauche sur place
    PIVOT_RIGHT    = auto()   # pivote droite sur place
    PAUSED         = auto()   # pause inspection (bras arrêté)
    EMERGENCY_STOP = auto()   # arrêt urgence verrouillé
    FAULT          = auto()   # défaut système


# Commandes textuelles acceptées via WebSocket / REST
VALID_COMMANDS = {
    # Mouvement
    "forward",
    "backward",
    "turn_left",
    "turn_right",
    "pivot_left",
    "pivot_right",
    "stop",
    "brake",
    # Vitesse
    "speed_up",
    "speed_down",
    "set_speed",       # requiert paramètre "value" (0-100)
    # Inspection
    "inspect_start",
    "inspect_stop",
    "inspect_pause",
    "inspect_resume",
    # Arrêt urgence
    "estop",
    "estop_release",
    # Caméra / éclairage
    "light_on",
    "light_off",
    "light_set",       # requiert paramètre "value" (0-100)
    "snapshot",
    # Système
    "ping",
    "reset_odometry",
}

SPEED_STEP = 10   # % de change par commande speed_up / speed_down


class NavigationController:
    """
    Orchestre la navigation du robot.
    Reçoit des commandes sérialisées (dict) et appelle les
    méthodes de MotorController, LedController et CameraStream.
    Thread-safe. Compatible avec asyncio.
    """

    def __init__(self, motors, leds, camera, safety):
        """
        :param motors:  hardware.motors.MotorController
        :param leds:    hardware.leds.LedController
        :param camera:  hardware.camera.CameraStream
        :param safety:  control.safety.SafetyManager
        """
        self._motors  = motors
        self._leds    = leds
        self._camera  = camera
        self._safety  = safety

        self._state     = RobotState.IDLE
        self._speed_pct = 60.0   # vitesse courante (%)
        self._inspecting = False
        self._start_time = None

        self._leds.set_state("ready")
        logger.info("NavigationController prêt")

    # ── Dispatch commandes ────────────────────────────────────────────────────

    async def handle_command(self, cmd: dict) -> dict:
        """
        Traitement principal d'une commande.
        :param cmd: {"action": str, "value": optional}
        :return:    {"ok": bool, "state": str, "msg": str}
        """
        action = cmd.get("action", "").lower().strip()

        if action not in VALID_COMMANDS:
            return self._resp(False, f"Commande inconnue : '{action}'")

        # L'arrêt d'urgence bloque tout sauf estop_release et ping
        if self._state == RobotState.EMERGENCY_STOP and action not in ("estop_release", "ping"):
            return self._resp(False, "ARRÊT D'URGENCE actif — seule la commande estop_release est acceptée")

        handler = getattr(self, f"_cmd_{action}", None)
        if callable(handler):
            return await handler(cmd)

        return self._resp(False, f"Commande non implémentée : {action}")

    # ── Commandes mouvement ───────────────────────────────────────────────────

    async def _cmd_forward(self, cmd):
        if not self._safety.is_path_clear("front"):
            return self._resp(False, "Obstacle détecté à l'avant — déplacement bloqué")
        self._motors.forward(self._speed_pct)
        self._set_state(RobotState.MOVING_FORWARD)
        self._leds.set_state("moving")
        return self._resp(True, "Avance")

    async def _cmd_backward(self, cmd):
        if not self._safety.is_path_clear("rear"):
            return self._resp(False, "Obstacle détecté à l'arrière — déplacement bloqué")
        self._motors.backward(self._speed_pct)
        self._set_state(RobotState.MOVING_BACKWARD)
        self._leds.set_state("moving")
        return self._resp(True, "Recule")

    async def _cmd_turn_left(self, cmd):
        self._motors.turn_left(self._speed_pct)
        self._set_state(RobotState.TURNING_LEFT)
        self._leds.set_state("moving")
        return self._resp(True, "Virage gauche")

    async def _cmd_turn_right(self, cmd):
        self._motors.turn_right(self._speed_pct)
        self._set_state(RobotState.TURNING_RIGHT)
        self._leds.set_state("moving")
        return self._resp(True, "Virage droite")

    async def _cmd_pivot_left(self, cmd):
        self._motors.pivot_left(self._speed_pct * 0.6)
        self._set_state(RobotState.PIVOT_LEFT)
        self._leds.set_state("moving")
        return self._resp(True, "Pivotement gauche")

    async def _cmd_pivot_right(self, cmd):
        self._motors.pivot_right(self._speed_pct * 0.6)
        self._set_state(RobotState.PIVOT_RIGHT)
        self._leds.set_state("moving")
        return self._resp(True, "Pivotement droite")

    async def _cmd_stop(self, cmd):
        self._motors.stop()
        self._set_state(RobotState.IDLE)
        self._leds.set_state("ready")
        return self._resp(True, "Arrêt progressif")

    async def _cmd_brake(self, cmd):
        self._motors.brake()
        self._set_state(RobotState.IDLE)
        self._leds.set_state("ready")
        return self._resp(True, "Frein immédiat")

    # ── Vitesse ───────────────────────────────────────────────────────────────

    async def _cmd_speed_up(self, cmd):
        self._speed_pct = min(100.0, self._speed_pct + SPEED_STEP)
        self._motors.set_speed_pct(self._speed_pct)
        return self._resp(True, f"Vitesse : {self._speed_pct:.0f}%")

    async def _cmd_speed_down(self, cmd):
        self._speed_pct = max(20.0, self._speed_pct - SPEED_STEP)
        self._motors.set_speed_pct(self._speed_pct)
        return self._resp(True, f"Vitesse : {self._speed_pct:.0f}%")

    async def _cmd_set_speed(self, cmd):
        v = float(cmd.get("value", self._speed_pct))
        self._speed_pct = max(20.0, min(100.0, v))
        self._motors.set_speed_pct(self._speed_pct)
        return self._resp(True, f"Vitesse réglée : {self._speed_pct:.0f}%")

    # ── Inspection ────────────────────────────────────────────────────────────

    async def _cmd_inspect_start(self, cmd):
        self._inspecting = True
        self._start_time = time.time()
        self._motors.reset_odometry()
        self._leds.lighting_on()
        self._camera.update_overlay(0.0, "INSPECTION EN COURS")
        self._leds.set_state("ready")
        logger.info("Inspection démarrée")
        return self._resp(True, "Inspection démarrée")

    async def _cmd_inspect_stop(self, cmd):
        self._inspecting = False
        self._motors.stop()
        self._leds.lighting_off()
        self._camera.update_overlay(self._motors.distance_m, "INSPECTION TERMINÉE")
        self._leds.set_state("ready")
        logger.info("Inspection terminée — %.1f m parcourus", self._motors.distance_m)
        return self._resp(True, f"Inspection terminée — {self._motors.distance_m:.1f} m")

    async def _cmd_inspect_pause(self, cmd):
        self._motors.stop()
        self._set_state(RobotState.PAUSED)
        self._leds.set_state("paused")
        return self._resp(True, "Inspection pausée")

    async def _cmd_inspect_resume(self, cmd):
        self._set_state(RobotState.IDLE)
        self._leds.set_state("ready")
        return self._resp(True, "Inspection reprise")

    # ── Arrêt urgence ─────────────────────────────────────────────────────────

    async def _cmd_estop(self, cmd):
        self._motors.emergency_stop()
        self._set_state(RobotState.EMERGENCY_STOP)
        self._leds.set_state("emergency")
        logger.critical("ARRÊT D'URGENCE déclenché via commande")
        return self._resp(True, "ARRÊT D'URGENCE activé")

    async def _cmd_estop_release(self, cmd):
        self._motors.release_emergency()
        self._set_state(RobotState.IDLE)
        self._leds.set_state("ready")
        logger.warning("Arrêt d'urgence relâché via commande")
        return self._resp(True, "Arrêt d'urgence relâché")

    # ── Caméra / éclairage ────────────────────────────────────────────────────

    async def _cmd_light_on(self, cmd):
        self._leds.lighting_on()
        return self._resp(True, f"Éclairage ON ({self._leds.lighting_duty:.0f}%)")

    async def _cmd_light_off(self, cmd):
        self._leds.lighting_off()
        return self._resp(True, "Éclairage OFF")

    async def _cmd_light_set(self, cmd):
        v = float(cmd.get("value", 80))
        self._leds.set_lighting(v)
        return self._resp(True, f"Éclairage : {v:.0f}%")

    async def _cmd_snapshot(self, cmd):
        import os
        import config as cfg
        os.makedirs(cfg.EVIDENCE_DIR, exist_ok=True)
        ts  = time.strftime("%Y%m%d_%H%M%S")
        pos = f"{self._motors.distance_m:.2f}m".replace(".", "p")
        fp  = os.path.join(cfg.EVIDENCE_DIR, f"evidence_{ts}_{pos}.jpg")
        ok  = self._camera.save_snapshot(fp)
        if ok:
            return self._resp(True, f"Snapshot sauvegardé : {fp}", {"filepath": fp})
        return self._resp(False, "Snapshot échoué — caméra non disponible")

    # ── Utilitaires ───────────────────────────────────────────────────────────

    async def _cmd_ping(self, cmd):
        return self._resp(True, "pong", {"timestamp": time.time()})

    async def _cmd_reset_odometry(self, cmd):
        self._motors.reset_odometry()
        return self._resp(True, "Odométrie réinitialisée")

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _set_state(self, state: RobotState):
        if self._state != state:
            logger.info("État robot : %s → %s", self._state.name, state.name)
        self._state = state

    def _resp(self, ok: bool, msg: str, extra: dict = None) -> dict:
        r = {
            "ok":    ok,
            "msg":   msg,
            "state": self._state.name,
            "speed": self._speed_pct,
        }
        if extra:
            r.update(extra)
        return r

    def get_status(self) -> dict:
        return {
            "state":       self._state.name,
            "speed_pct":   self._speed_pct,
            "inspecting":  self._inspecting,
            "distance_m":  self._motors.distance_m,
            "heading_deg": self._motors.heading_deg,
        }
