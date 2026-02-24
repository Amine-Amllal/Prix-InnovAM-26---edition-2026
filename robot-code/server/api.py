# =============================================================================
# SIANA — server/api.py
# Serveur embarqué sur le robot : WebSocket (commandes + télémétrie)
#                                + HTTP REST (status, snapshot)
#                                + MJPEG stream (caméra)
#
# Stack : asyncio + websockets + aiohttp (léger, pas de Django)
# Protocoles requis par CdC : TCP/IP, HTTP/HTTPS, WebSocket
# =============================================================================

import asyncio
import json
import time
import logging
import traceback
from typing import Set

logger = logging.getLogger("siana.server")

try:
    import websockets
    from websockets.server import WebSocketServerProtocol
    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False
    logger.error("websockets non installé — pip install websockets")

try:
    from aiohttp import web
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False
    logger.error("aiohttp non installé — pip install aiohttp")


class RobotServer:
    """
    Serveur réseau embarqué sur le Jetson Nano.

    Architecture (conforme CdC section 3.3) :
    ┌─────────────────────────────────────────────────────────────┐
    │  Opérateur (tablette / PC web-poc)                          │
    │       │ WebSocket ws://IP:8765                               │
    │       │ ← télémétrie JSON 5Hz                                │
    │       │ → commandes JSON                                     │
    │       │                                                      │
    │       │ HTTP GET /stream              ← MJPEG caméra         │
    │       │ HTTP GET /api/status          ← état complet JSON    │
    │       │ HTTP POST /api/command        ← commande REST        │
    │       │ HTTP GET /api/snapshot        ← JPEG dernière image  │
    │       │ HTTP POST /api/estop          ← arrêt urgence        │
    │       │ HTTP POST /api/estop/release  ← relâcher E-STOP      │
    └─────────────────────────────────────────────────────────────┘

    Mesure de latence WebSocket :
    - Le serveur répond à {"action":"ping"} avec {"type":"pong","ts":...}
    - Le client calcule RTT = now - ts
    """

    def __init__(self, navigation, safety, motors, battery, leds, camera):
        self._nav     = navigation
        self._safety  = safety
        self._motors  = motors
        self._battery = battery
        self._leds    = leds
        self._camera  = camera

        self._ws_clients: Set[WebSocketServerProtocol] = set()
        self._ws_lock = asyncio.Lock()

        import config as cfg
        self._cfg = cfg

    # ═══════════════════════════════════════════════════════════════════════════
    # WebSocket Server
    # ═══════════════════════════════════════════════════════════════════════════

    async def _ws_handler(self, ws: "WebSocketServerProtocol"):
        """Gère une connexion WebSocket entrante."""
        import config as cfg
        addr = ws.remote_address
        logger.info("WS connexion : %s", addr)

        async with self._ws_lock:
            if len(self._ws_clients) >= cfg.MAX_WS_CLIENTS:
                await ws.close(1013, "Trop de connexions simultanées")
                logger.warning("Connexion refusée (max %d clients)", cfg.MAX_WS_CLIENTS)
                return
            self._ws_clients.add(ws)

        # Envoi état initial à la connexion
        await self._send_json(ws, {
            "type":    "hello",
            "version": "SIANA-2026",
            "state":   self._build_telemetry(),
        })

        try:
            async for raw in ws:
                self._safety.heartbeat()
                try:
                    cmd = json.loads(raw)
                    result = await self._nav.handle_command(cmd)
                    # Réponse directe au client qui a envoyé la commande
                    await self._send_json(ws, {"type": "cmd_ack", **result})
                    # Diffuser le nouvel état à tous
                    await self._broadcast({"type": "state", "state": self._nav.get_status()})
                except json.JSONDecodeError:
                    await self._send_json(ws, {"type": "error", "msg": "JSON invalide"})
                except Exception as e:
                    logger.error("Erreur traitement commande : %s", e)
                    await self._send_json(ws, {"type": "error", "msg": str(e)})
        except Exception:
            pass
        finally:
            async with self._ws_lock:
                self._ws_clients.discard(ws)
            logger.info("WS déconnexion : %s", addr)

    async def _send_json(self, ws, data: dict):
        try:
            await ws.send(json.dumps(data, default=str))
        except Exception:
            pass

    async def _broadcast(self, data: dict):
        """Diffuse un message JSON à tous les clients WebSocket connectés."""
        if not self._ws_clients:
            return
        msg = json.dumps(data, default=str)
        dead = set()
        async with self._ws_lock:
            clients = set(self._ws_clients)
        for ws in clients:
            try:
                await ws.send(msg)
            except Exception:
                dead.add(ws)
        if dead:
            async with self._ws_lock:
                self._ws_clients -= dead

    # ─── Boucle télémétrie 5 Hz ────────────────────────────────────────────────

    async def _telemetry_loop(self):
        import config as cfg
        interval = cfg.TELEMETRY_INTERVAL
        while True:
            try:
                telemetry = self._build_telemetry()
                await self._broadcast({
                    "type":      "telemetry",
                    "timestamp": time.time(),
                    "data":      telemetry,
                })
                # Mise à jour overlay caméra
                self._camera.update_overlay(
                    telemetry["motors"]["distance_m"],
                    "INSP" if self._nav._inspecting else "IDLE"
                )
                # Surveillance limites fosse
                self._safety.check_fosse_limits(telemetry["motors"]["distance_m"])
            except Exception as e:
                logger.debug("Erreur télémétrie : %s", e)
            await asyncio.sleep(interval)

    def _build_telemetry(self) -> dict:
        return {
            "robot":   self._nav.get_status(),
            "motors":  self._motors.get_telemetry(),
            "battery": self._battery.get_telemetry(),
            "safety":  self._safety.get_telemetry(),
            "leds":    self._leds.get_telemetry(),
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # HTTP REST + MJPEG (aiohttp)
    # ═══════════════════════════════════════════════════════════════════════════

    async def _http_status(self, request):
        return web.json_response(self._build_telemetry())

    async def _http_command(self, request):
        try:
            cmd = await request.json()
        except Exception:
            return web.json_response({"ok": False, "msg": "Corps JSON invalide"}, status=400)
        self._safety.heartbeat()
        result = await self._nav.handle_command(cmd)
        return web.json_response(result)

    async def _http_estop(self, request):
        await self._nav.handle_command({"action": "estop"})
        return web.json_response({"ok": True, "msg": "ARRÊT D'URGENCE activé"})

    async def _http_estop_release(self, request):
        await self._nav.handle_command({"action": "estop_release"})
        return web.json_response({"ok": True, "msg": "E-STOP relâché"})

    async def _http_snapshot(self, request):
        jpeg = self._camera.capture_snapshot()
        if jpeg is None:
            return web.Response(status=503, text="Caméra non disponible")
        return web.Response(body=jpeg, content_type="image/jpeg")

    async def _http_stream(self, request):
        """Endpoint MJPEG — compatible navigateurs et VLC."""
        response = web.StreamResponse(headers={
            "Content-Type":  "multipart/x-mixed-replace; boundary=frame",
            "Cache-Control": "no-cache",
            "Pragma":        "no-cache",
        })
        await response.prepare(request)
        try:
            import config as cfg
            while True:
                jpeg = self._camera.get_latest_jpeg()
                if jpeg:
                    header = (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                    )
                    await response.write(header + jpeg + b"\r\n")
                await asyncio.sleep(1.0 / cfg.CAMERA_FRAMERATE)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        return response

    async def _http_ping(self, request):
        return web.json_response({"ok": True, "msg": "pong", "ts": time.time()})

    # ═══════════════════════════════════════════════════════════════════════════
    # Démarrage du serveur
    # ═══════════════════════════════════════════════════════════════════════════

    async def start(self):
        import config as cfg

        # ── WebSocket ──────────────────────────────────────────────────────────
        if _WS_AVAILABLE:
            ws_server = await websockets.serve(
                self._ws_handler,
                cfg.SERVER_HOST,
                cfg.SERVER_PORT,
                ping_interval=cfg.WS_PING_INTERVAL,
                ping_timeout=cfg.WS_PING_INTERVAL * 2,
            )
            logger.info(
                "WebSocket démarré : ws://%s:%d",
                cfg.SERVER_HOST, cfg.SERVER_PORT
            )
        else:
            ws_server = None
            logger.error("WebSocket NON démarré — websockets manquant")

        # ── HTTP REST + MJPEG ──────────────────────────────────────────────────
        if _AIOHTTP_AVAILABLE:
            app = web.Application()
            app.router.add_get( "/ping",                self._http_ping)
            app.router.add_get( "/api/status",          self._http_status)
            app.router.add_post("/api/command",         self._http_command)
            app.router.add_post("/api/estop",           self._http_estop)
            app.router.add_post("/api/estop/release",   self._http_estop_release)
            app.router.add_get( "/api/snapshot",        self._http_snapshot)
            app.router.add_get( "/stream",              self._http_stream)

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, cfg.SERVER_HOST, cfg.HTTP_PORT)
            await site.start()
            logger.info(
                "HTTP démarré : http://%s:%d  (stream: /stream  REST: /api/*)",
                cfg.SERVER_HOST, cfg.HTTP_PORT
            )
        else:
            logger.error("HTTP NON démarré — aiohttp manquant")

        # ── Boucle télémétrie ──────────────────────────────────────────────────
        asyncio.ensure_future(self._telemetry_loop())

        logger.info("Serveur SIANA opérationnel")

        # Maintenir le serveur WS en vie
        if ws_server:
            async with ws_server:
                await asyncio.Future()   # tourne indéfiniment
        else:
            await asyncio.Future()
