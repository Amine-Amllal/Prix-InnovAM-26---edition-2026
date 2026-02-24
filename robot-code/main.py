# =============================================================================
# SIANA — main.py
# Point d'entrée principal du robot d'inspection TGV
# Exécuter sur NVIDIA Jetson Nano :  sudo python main.py
# (sudo requis pour GPIO + accès /dev/video*)
# =============================================================================

import asyncio
import logging
import signal
import sys
import os

# ── Ajouter le répertoire courant au PYTHONPATH ────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

import config as cfg

# ── Configuration journalisation ───────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        # Décommentez pour journalisation fichier :
        # logging.FileHandler(cfg.LOG_FILE),
    ]
)
logger = logging.getLogger("siana.main")

# ── Imports matériel / contrôle ───────────────────────────────────────────
from hardware.motors  import MotorController
from hardware.sensors import ObstacleManager, BatteryMonitor
from hardware.leds    import LedController
from hardware.camera  import CameraStream
from control.navigation import NavigationController
from control.safety    import SafetyManager
from server.api        import RobotServer


# ─── Initialisation ────────────────────────────────────────────────────────

def build_robot():
    """
    Instancie et connecte tous les composants du robot.
    Retourne un dict avec tous les handles pour le shutdown.
    """
    logger.info("════════════════════════════════════════")
    logger.info("   SIANA — Robot Inspection TGV 2026   ")
    logger.info("════════════════════════════════════════")

    # ── Matériel ─────────────────────────────────────────────────────────────
    logger.info("Initialisation moteurs...")
    motors = MotorController()

    logger.info("Initialisation capteurs...")
    obstacle_mgr  = ObstacleManager()
    battery_mon   = BatteryMonitor()

    logger.info("Initialisation LEDs...")
    leds = LedController()

    logger.info("Initialisation caméra...")
    camera = CameraStream()
    camera.start()

    # ── Couche contrôle ───────────────────────────────────────────────────────
    logger.info("Initialisation sécurité...")
    safety = SafetyManager(
        motors=motors,
        leds=leds,
        sensors=(obstacle_mgr, battery_mon),
    )

    logger.info("Initialisation navigation...")
    navigation = NavigationController(
        motors=motors,
        leds=leds,
        camera=camera,
        safety=safety,
    )

    # Liaison tardive (évite import circulaire)
    safety.set_navigation(navigation)

    # ── Démarrage capteurs en arrière-plan ────────────────────────────────────
    obstacle_mgr.start()
    battery_mon.start()

    # ── Serveur réseau ────────────────────────────────────────────────────────
    logger.info("Initialisation serveur réseau...")
    server = RobotServer(
        navigation=navigation,
        safety=safety,
        motors=motors,
        battery=battery_mon,
        leds=leds,
        camera=camera,
    )

    logger.info("Tous les composants initialisés ✓")
    leds.set_state("ready")

    return {
        "motors":       motors,
        "obstacle_mgr": obstacle_mgr,
        "battery_mon":  battery_mon,
        "leds":         leds,
        "camera":       camera,
        "safety":       safety,
        "navigation":   navigation,
        "server":       server,
    }


# ─── Boucle odométrie ──────────────────────────────────────────────────────

async def odometry_loop(motors):
    """
    Met à jour l'odométrie toutes les 100 ms.
    La boucle encodeur est gérée par interruptions GPIO,
    cette tâche agrège les ticks accumulés.
    """
    while True:
        motors.update_odometry()
        await asyncio.sleep(0.1)


# ─── Shutdown propre ───────────────────────────────────────────────────────

def create_shutdown_handler(components):
    def _shutdown(signum, frame):
        logger.warning("Signal %d reçu — arrêt propre en cours...", signum)

        # 1. Arrêt immédiat des moteurs
        try:
            components["motors"].emergency_stop()
        except Exception:
            pass

        # 2. Arrêt composants
        for name, comp in components.items():
            for method in ("stop", "shutdown", "cleanup"):
                fn = getattr(comp, method, None)
                if callable(fn):
                    try:
                        fn()
                        break
                    except Exception:
                        pass

        logger.info("Arrêt propre terminé")
        sys.exit(0)

    return _shutdown


# ─── MAIN ──────────────────────────────────────────────────────────────────

async def main():
    # Construction du robot
    components = build_robot()

    # Handlers signaux POSIX (Ctrl+C, SIGTERM)
    handler = create_shutdown_handler(components)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, handler)

    logger.info("────────────────────────────────────────")
    logger.info("WebSocket  : ws://0.0.0.0:%d", cfg.SERVER_PORT)
    logger.info("HTTP REST  : http://0.0.0.0:%d/api/status", cfg.HTTP_PORT)
    logger.info("Caméra     : http://0.0.0.0:%d/stream", cfg.HTTP_PORT)
    logger.info("────────────────────────────────────────")
    logger.info("Robot prêt — en attente de connexion opérateur")

    # Tâches parallèles
    await asyncio.gather(
        odometry_loop(components["motors"]),
        components["server"].start(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interruption clavier — arrêt.")
