# =============================================================================
# SIANA — hardware/camera.py
# Capture vidéo et streaming MJPEG temps réel
# Supports : OpenCV + GStreamer (caméra CSI Jetson Nano) ou OpenCV USB
# =============================================================================

import io
import time
import threading
import logging
import datetime

logger = logging.getLogger("siana.camera")

# picamera2 n'est pas disponible sur Jetson Nano
# La caméra CSI est accédée via GStreamer + OpenCV
_PICAM_AVAILABLE = False

try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False
    logger.warning("OpenCV (cv2) non disponible")


class CameraStream:
    """
    Capture continue de la caméra et fourniture du dernier JPEG encodé.
    Pattern thread-safe : un thread producteur, N consommateurs.

    Mode GStreamer : caméra CSI native Jetson Nano (v4l2src / nvarguscamerasrc)
    Mode OpenCV    : toute caméra USB compatible V4L2
    Mode simulation: image synthétique si aucun matériel disponible
    """

    # Délimiteurs MJPEG
    MJPEG_BOUNDARY = b"--frame"
    MJPEG_HEADER   = (
        b"--frame\r\n"
        b"Content-Type: image/jpeg\r\n"
        b"Content-Length: %d\r\n\r\n"
    )

    def __init__(self):
        import config as cfg
        self.cfg = cfg
        self._width, self._height = cfg.CAMERA_RESOLUTION
        self._fps     = cfg.CAMERA_FRAMERATE
        self._rotation = cfg.CAMERA_ROTATION

        self._frame_lock   = threading.Lock()
        self._latest_jpeg  = None
        self._frame_count  = 0
        self._running      = False
        self._thread       = None
        self._capture      = None  # handle caméra

        # Overlay : affichage horodatage + position sur l'image
        self._overlay_pos_m  = 0.0
        self._overlay_status = "INSPECTION"

    # ── Démarrage ─────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True

        if _CV2_AVAILABLE and self.cfg.USE_PICAMERA2 is False:
            # Vérifier si caméra CSI Jetson disponible (nvarguscamerasrc)
            self._thread = threading.Thread(target=self._capture_opencv, daemon=True)
        elif _CV2_AVAILABLE:
            self._thread = threading.Thread(target=self._capture_opencv, daemon=True)
        else:
            logger.warning("Aucune caméra disponible — flux synthétique activé")
            self._thread = threading.Thread(target=self._capture_synthetic, daemon=True)

        self._thread.start()
        logger.info("CameraStream démarré (%dx%d @ %dfps)", self._width, self._height, self._fps)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        if self._capture and _CV2_AVAILABLE:
            self._capture.release()
            self._capture = None
        logger.info("CameraStream arrêté")

    # ── Pipeline GStreamer Jetson Nano (caméra CSI) ────────────────────────────
    # Utilisé automatiquement si la caméra /dev/video0 est une cam CSI IMX219.
    # Le pipeline nvarguscamerasrc exploite le hardware ISP du Jetson pour
    # une meilleure qualité d'image dans les conditions de la fosse (faible éclairage).
    GSTREAMER_PIPELINE = (
        "nvarguscamerasrc sensor-id=0 ! "
        "video/x-raw(memory:NVMM), width={w}, height={h}, framerate={fps}/1 ! "
        "nvvidconv flip-method=0 ! "
        "video/x-raw, width={w}, height={h}, format=BGRx ! "
        "videoconvert ! video/x-raw, format=BGR ! appsink max-buffers=1 drop=true"
    )

    # ── Capture OpenCV (USB ou CSI via GStreamer) ──────────────────────────────

    def _capture_opencv(self):
        # Essayer d'abord le pipeline GStreamer CSI (Jetson Nano + caméra IMX219)
        gst_pipeline = self.GSTREAMER_PIPELINE.format(
            w=self._width, h=self._height, fps=self._fps
        )
        cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
        if not cap.isOpened():
            logger.warning("GStreamer CSI indisponible — fallback caméra USB index %d",
                           self.cfg.CAMERA_INDEX)
            cap = cv2.VideoCapture(self.cfg.CAMERA_INDEX)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self._width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
            cap.set(cv2.CAP_PROP_FPS,          self._fps)
        self._capture = cap

        interval = 1.0 / self._fps

        while self._running:
            t0 = time.time()
            ok, frame = cap.read()
            if ok:
                if self._rotation == 180:
                    frame = cv2.rotate(frame, cv2.ROTATE_180)
                elif self._rotation == 90:
                    frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                frame = self._add_overlay(frame)
                ok2, buf = cv2.imencode(".jpg", frame,
                                        [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ok2:
                    self._set_frame(bytes(buf))
            elapsed = time.time() - t0
            time.sleep(max(0, interval - elapsed))

    # ── Flux synthétique (simulation bureau, sans matériel) ───────────────────

    def _capture_synthetic(self):
        """
        Génère des images synthétiques simulant la vue sous-caisse
        d'un TGV pour les tests sans matériel réel.
        """
        if not _CV2_AVAILABLE:
            # Flux JPEG mono-couleur si cv2 absent
            import struct
            # JPEG 2x2 px noir minimal – placeholder
            tiny_jpeg = (
                b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
                b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t'
                b'\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a'
                b'\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\x1e==',
            )
            interval = 1.0 / self._fps
            while self._running:
                self._set_frame(tiny_jpeg)
                time.sleep(interval)
            return

        W, H = self._width, self._height
        interval = 1.0 / self._fps
        t_start = time.time()

        while self._running:
            t0 = time.time()
            elapsed = t0 - t_start

            # Fond sombre (sous-caisse)
            frame = np.zeros((H, W, 3), dtype=np.uint8)
            frame[:] = (18, 20, 30)

            # Rails / poutres horizontales
            for i, ry in enumerate([int(H * r) for r in (0.15, 0.35, 0.55, 0.75, 0.90)]):
                cv2.rectangle(frame, (0, ry), (W, ry + 18),
                              ((28, 42, 55), (38, 55, 70))[i % 2], -1)

            # Défilement vertical (simulation mouvement)
            scroll = int(elapsed * 60) % H
            for i in range(8):
                bx = (i * int(W / 7) + 30) % W
                by = (int(H * 0.2 + i * 80) + scroll) % H
                # boulon hexagonal
                cx, cy, r = bx, by, 8
                for j in range(6):
                    import math
                    a1 = math.radians(j * 60)
                    a2 = math.radians((j + 1) * 60)
                    p1 = (int(cx + r * math.cos(a1)), int(cy + r * math.sin(a1)))
                    p2 = (int(cx + r * math.cos(a2)), int(cy + r * math.sin(a2)))
                    cv2.line(frame, p1, p2, (90, 110, 140), 2)
                cv2.circle(frame, (cx, cy), 4, (70, 90, 120), -1)

            # Câbles
            for ci, cy_frac in enumerate((0.3, 0.5, 0.65)):
                pts = np.array([
                    [x, int(H * cy_frac + 8 * np.sin((x + int(elapsed * 40)) * 0.03))]
                    for x in range(0, W, 5)
                ], dtype=np.int32)
                cv2.polylines(frame, [pts], False,
                              [(40, 120, 90), (60, 80, 110), (70, 55, 105)][ci], 3)

            # Ligne de scan IA
            scan_y = int((elapsed * 80) % H)
            frame[max(0, scan_y - 2):scan_y + 2, :] = (0, 60, 120)

            # HUD basique
            frame = self._add_overlay(frame)

            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                self._set_frame(bytes(buf))

            elapsed_loop = time.time() - t0
            time.sleep(max(0, interval - elapsed_loop))

    # ── Overlay (horodatage + position) ───────────────────────────────────────

    def _add_overlay(self, frame):
        if not _CV2_AVAILABLE:
            return frame
        now    = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pos    = f"POS: {self._overlay_pos_m:.2f} m"
        status = self._overlay_status

        # Bande supérieure semi-transparente
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (frame.shape[1], 36), (0, 0, 0), -1)
        frame = cv2.addWeighted(overlay, 0.55, frame, 0.45, 0)

        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(frame, f"SIANA | {status}", (8, 24),  font, 0.55, (255, 255, 255), 1)
        cv2.putText(frame, now,                  (frame.shape[1] - 200, 24), font, 0.45, (180, 180, 180), 1)
        cv2.putText(frame, pos,                  (frame.shape[1] // 2 - 50, 24), font, 0.50, (80, 200, 255), 1)
        return frame

    def update_overlay(self, pos_m: float, status: str = "INSPECTION"):
        self._overlay_pos_m  = pos_m
        self._overlay_status = status

    # ── Accès interne ─────────────────────────────────────────────────────────

    def _set_frame(self, jpeg_bytes: bytes):
        with self._frame_lock:
            self._latest_jpeg = jpeg_bytes
            self._frame_count += 1

    def get_latest_jpeg(self) -> bytes | None:
        with self._frame_lock:
            return self._latest_jpeg

    def capture_snapshot(self) -> bytes | None:
        """Capture et retourne le JPEG courant (pour sauvegarde preuve)."""
        return self.get_latest_jpeg()

    def save_snapshot(self, filepath: str) -> bool:
        """Sauvegarde le JPEG courant dans un fichier."""
        jpeg = self.capture_snapshot()
        if jpeg is None:
            return False
        try:
            with open(filepath, "wb") as f:
                f.write(jpeg)
            return True
        except OSError as e:
            logger.error("Impossible de sauvegarder snapshot : %s", e)
            return False

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def mjpeg_generator(self):
        """
        Générateur Python pour streamer le flux MJPEG vers un client HTTP.
        Usage :
            for chunk in camera.mjpeg_generator():
                response.write(chunk)
        """
        while self._running:
            jpeg = self.get_latest_jpeg()
            if jpeg:
                header = self.MJPEG_HEADER % len(jpeg)
                yield header + jpeg + b"\r\n"
            time.sleep(1.0 / self._fps)
