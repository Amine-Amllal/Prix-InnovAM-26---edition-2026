#!/usr/bin/env python3
# =============================================================================
# SIANA — test_connection.py
# Script de test à exécuter sur PC opérateur pour vérifier
# la connexion WebSocket avec le robot
# Usage : python test_connection.py <IP_ROBOT>
# =============================================================================

import asyncio
import json
import sys
import time

try:
    import websockets
except ImportError:
    print("Installer websockets : pip install websockets")
    sys.exit(1)


COMMANDS_SEQUENCE = [
    {"action": "ping"},
    {"action": "inspect_start"},
    {"action": "light_on"},
    {"action": "forward"},
    {"action": "stop"},
    {"action": "turn_left"},
    {"action": "stop"},
    {"action": "inspect_stop"},
    {"action": "ping"},
]


async def test_robot(ip: str, port: int = 8765):
    uri = f"ws://{ip}:{port}"
    print(f"\n📡 Connexion à {uri}...")

    try:
        async with websockets.connect(uri, open_timeout=5) as ws:
            print("✓ Connecté au robot SIANA\n")

            for cmd in COMMANDS_SEQUENCE:
                t0 = time.time()
                msg = json.dumps(cmd)
                await ws.send(msg)
                print(f"→ Envoi  : {msg}")

                response = await asyncio.wait_for(ws.recv(), timeout=3.0)
                rtt_ms = (time.time() - t0) * 1000
                data = json.loads(response)
                status = "✓" if data.get("ok", True) else "✗"
                print(f"← Réponse: {status}  {data.get('msg', data.get('type', ''))}  [{rtt_ms:.0f} ms]")
                print()
                await asyncio.sleep(0.5)

            print("Test terminé avec succès.")

    except ConnectionRefusedError:
        print(f"✗ Connexion refusée — le robot est-il démarré ?")
        sys.exit(1)
    except asyncio.TimeoutError:
        print("✗ Timeout — pas de réponse du robot")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Erreur : {e}")
        sys.exit(1)


if __name__ == "__main__":
    robot_ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.100"
    asyncio.run(test_robot(robot_ip))
