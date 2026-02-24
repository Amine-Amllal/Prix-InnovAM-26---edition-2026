# =============================================================================
# SIANA — Robot d'Inspection Sous Caisse TGV
# config.py — Configuration matérielle et réseau
# Cible : NVIDIA Jetson Nano (Linux SBC, Jetson.GPIO)
# =============================================================================

# ──────────────────────────────────────────────────────────────────────────────
# GPIO — Moteur GAUCHE  (L298N / IBT-2 ou équivalent H-Bridge)
# ──────────────────────────────────────────────────────────────────────────────
MOTOR_LEFT_PWM   = 12   # GPIO BCM — signal PWM vitesse (freq 20 kHz recommandée)
MOTOR_LEFT_IN1   = 23   # GPIO BCM — direction A
MOTOR_LEFT_IN2   = 24   # GPIO BCM — direction B

# ──────────────────────────────────────────────────────────────────────────────
# GPIO — Moteur DROIT
# ──────────────────────────────────────────────────────────────────────────────
MOTOR_RIGHT_PWM  = 13   # GPIO BCM — signal PWM vitesse
MOTOR_RIGHT_IN1  = 27   # GPIO BCM — direction A
MOTOR_RIGHT_IN2  = 22   # GPIO BCM — direction B

# ──────────────────────────────────────────────────────────────────────────────
# Encodeurs roues (hall effect ou optique)
# ──────────────────────────────────────────────────────────────────────────────
ENCODER_LEFT_A   = 5    # GPIO BCM — canal A encodeur gauche
ENCODER_LEFT_B   = 6    # GPIO BCM — canal B encodeur gauche
ENCODER_RIGHT_A  = 16   # GPIO BCM — canal A encodeur droit
ENCODER_RIGHT_B  = 20   # GPIO BCM — canal B encodeur droit

ENCODER_TICKS_PER_REV  = 360   # impulsions par tour de roue
WHEEL_DIAMETER_MM      = 120   # diamètre roue (mm)
WHEEL_BASE_MM          = 450   # écartement entre roues (mm)

# ──────────────────────────────────────────────────────────────────────────────
# Capteurs ultrasons (HC-SR04 ou similaire)
# ──────────────────────────────────────────────────────────────────────────────
US_FRONT_TRIG    = 17   # GPIO BCM
US_FRONT_ECHO    = 4    # GPIO BCM
US_REAR_TRIG     = 18   # GPIO BCM
US_REAR_ECHO     = 25   # GPIO BCM
US_LEFT_TRIG     = 19   # GPIO BCM
US_LEFT_ECHO     = 26   # GPIO BCM

US_MIN_DISTANCE_CM      = 15   # distance obstacle → arrêt automatique
US_WARNING_DISTANCE_CM  = 40   # distance → ralentissement automatique

# ──────────────────────────────────────────────────────────────────────────────
# Bouton arrêt d'urgence PHYSIQUE (NO — normalement ouvert)
# ──────────────────────────────────────────────────────────────────────────────
ESTOP_PIN        = 21   # GPIO BCM — actif bas (pull-up interne)

# ──────────────────────────────────────────────────────────────────────────────
# Batterie — INA219 sur bus I2C (courant, tension, puissance)
# ──────────────────────────────────────────────────────────────────────────────
BATTERY_I2C_ADDR        = 0x40  # adresse INA219 par défaut
BATTERY_SHUNT_OHM       = 0.1   # valeur shunt (ohm)
BATTERY_MAX_EXPECTED_A  = 5.0   # courant max attendu (A)
BATTERY_NOMINAL_V       = 24.0  # tension nominale pack batterie (V)
BATTERY_MIN_V           = 20.0  # tension coupure basse (V)
BATTERY_MAX_V           = 29.4  # tension pleine charge (7S LiFePO4 ~3.6V×7)
BATTERY_LOW_THRESHOLD   = 15    # % → alerte niveau bas

# ──────────────────────────────────────────────────────────────────────────────
# LEDs de signalisation
# ──────────────────────────────────────────────────────────────────────────────
LED_GREEN_PIN    = 7    # GPIO BCM — vert : opérationnel
LED_ORANGE_PIN   = 8    # GPIO BCM — orange : batterie faible / avertissement
LED_RED_PIN      = 11   # GPIO BCM — rouge : arrêt urgence / défaut

# ──────────────────────────────────────────────────────────────────────────────
# Caméra
# ──────────────────────────────────────────────────────────────────────────────
CAMERA_RESOLUTION       = (1920, 1080)  # Full HD (4K optionnel : (3840,2160))
CAMERA_FRAMERATE        = 30            # fps (50 fps à 5 km/h recommandé)
CAMERA_ROTATION         = 180           # rotation si montage inversé (0/90/180/270)
CAMERA_INDEX            = 0             # index si USB camera (OpenCV)
USE_PICAMERA2           = False         # Jetson Nano : False (OpenCV + GStreamer CSI)

# Éclairage LED sous-caisse  (PWM sur transistor MOSFET)
LED_LIGHTING_PWM_PIN    = 9    # GPIO BCM
LED_LIGHTING_FREQ       = 1000 # Hz
LED_LIGHTING_DEFAULT    = 80   # % duty cycle par défaut

# ──────────────────────────────────────────────────────────────────────────────
# Mouvement et vitesse
# ──────────────────────────────────────────────────────────────────────────────
SPEED_MIN_PERCENT   = 20    # % PWM minimum (seuil anti-blocage moteur)
SPEED_MAX_PERCENT   = 100   # % PWM maximum
SPEED_DEFAULT       = 60    # % PWM — correspond à ~4 km/h
# Correspondance approximative : 60% ≈ 4 km/h sur ce type de robot
# À calibrer selon réduction mécanique et diamètre roue réels

TURN_SPEED_FACTOR   = 0.7   # facteur réduction vitesse en virage
RAMP_STEP           = 5     # increment % par tick de rampe (accél douce)
RAMP_INTERVAL_MS    = 30    # ms entre chaque step de rampe

INSPECTION_LENGTH_M = 200   # longueur fosse inspection (m)

# ──────────────────────────────────────────────────────────────────────────────
# Réseau
# ──────────────────────────────────────────────────────────────────────────────
SERVER_HOST         = "0.0.0.0"     # écoute toutes interfaces
SERVER_PORT         = 8765          # port WebSocket
HTTP_PORT           = 8080          # port HTTP REST + MJPEG stream
STREAM_PATH         = "/stream"     # endpoint MJPEG
API_BASE_PATH       = "/api"        # base URL REST

MAX_WS_CLIENTS      = 5             # connexions simultanées max
WS_PING_INTERVAL    = 10            # secondes — keepalive WebSocket
TELEMETRY_INTERVAL  = 0.2           # secondes — fréquence envoi télémétrie (5 Hz)

# ──────────────────────────────────────────────────────────────────────────────
# Journalisation et données
# ──────────────────────────────────────────────────────────────────────────────
LOG_LEVEL           = "INFO"        # DEBUG / INFO / WARNING / ERROR
LOG_FILE            = "/var/log/siana_robot.log"
EVIDENCE_DIR        = "/home/siana/siana_inspections"  # stockage images anomalies
MAX_EVIDENCE_SIZE   = 500           # nb max d'images par session
