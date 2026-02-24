# SIANA — Robot d'Inspection Sous Caisse TGV
**Prix InnovAM'26 | ENSAM-Meknès**

[![GitHub](https://img.shields.io/badge/GitHub-Prix--InnovAM--26-blue?logo=github)](https://github.com/Amine-Amllal/Prix-InnovAM-26---edition-2026)

Système logiciel complet pour l'automatisation de l'inspection visuelle sous caisse des rames à grande vitesse marocaines (RGVM).  
Remplace l'inspection manuelle ES (~1 h/opérateur) par un robot autonome téléopéré avec détection d'anomalies assistée par IA.

> **Dépôt GitHub :** https://github.com/Amine-Amllal/Prix-InnovAM-26---edition-2026

---

## Structure du projet

```
Siana/
├── robot-code/          # Code embarqué — NVIDIA Jetson Nano
├── web-poc/             # Interface opérateur — navigateur web
├── Notebook/            # Notebook Jupyter — pipeline IA (YOLOv8)
└── main.tex             # Rapport technique complet (LaTeX)
```

---

## `robot-code/` — Code embarqué Jetson Nano

Code Python exécuté **sur le robot**, organisé en quatre couches.

```
robot-code/
├── main.py              # Point d'entrée — lance tous les composants
├── config.py            # Paramètres GPIO, vitesse, réseau, caméra
├── requirements.txt     # Dépendances pip
├── siana.service        # Service systemd (démarrage automatique)
├── test_connection.py   # Test WebSocket depuis le PC opérateur
├── hardware/
│   ├── motors.py        # Traction différentielle + rampe + odométrie
│   ├── sensors.py       # Ultrasons HC-SR04 + INA219 (batterie 24 V)
│   ├── leds.py          # LEDs d'état + éclairage sous-caisse PWM
│   └── camera.py        # Capture CSI/USB + stream MJPEG + overlay HUD
├── control/
│   ├── navigation.py    # Automate d'états + dispatch commandes
│   └── safety.py        # E-STOP GPIO, watchdog WiFi, limite 200 m
└── server/
    └── api.py           # WebSocket 5 Hz + HTTP REST + MJPEG stream
```

### Prérequis matériel

| Composant | Référence / Spécification |
|---|---|
| Unité de calcul | NVIDIA Jetson Nano 4 GB |
| Pont-H moteurs | IBT-2 (ou L298N) |
| Encodeurs roues | Effet Hall, 360 ticks/tour |
| Ultrasons | HC-SR04 ×3 (avant, arrière, gauche) |
| Batterie | Pack LiFePO4 24 V / capacité ≥ 4 h |
| Moniteur batterie | INA219 (I²C, 0x40) |
| Caméra | IMX219 CSI (ou USB Full HD) |
| LEDs signalisation | Vert / Orange / Rouge + éclairage sous-caisse |
| Bouton E-STOP | Normalement ouvert (NO), câblé sur GPIO 21 |

### Installation sur Jetson Nano

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv python3-opencv

# Permissions GPIO
sudo groupadd -f -r gpio
sudo usermod -a -G gpio $USER
sudo cp /opt/nvidia/jetson-gpio/etc/99-gpio.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger

# Dépendances Python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Lancement

```bash
# Démarrage manuel
sudo -E venv/bin/python main.py

# Ou via systemd (démarrage automatique au boot)
sudo cp siana.service /etc/systemd/system/
sudo systemctl enable --now siana
```

Le robot est prêt quand le terminal affiche :
```
Robot prêt — en attente de connexion opérateur
```

### Endpoints réseau

| Protocole | Adresse | Usage |
|---|---|---|
| WebSocket | `ws://IP_JETSON:8765` | Commandes bidirectionnelles + télémétrie 5 Hz |
| HTTP REST | `http://IP_JETSON:8080/api/status` | État complet JSON |
| HTTP REST | `POST /api/command` | Envoi commande `{"action": "forward"}` |
| HTTP REST | `POST /api/estop` | Arrêt d'urgence immédiat |
| HTTP REST | `GET /api/snapshot` | Capture JPEG instantanée |
| MJPEG | `http://IP_JETSON:8080/stream` | Flux vidéo temps réel |

### Commandes WebSocket disponibles

```json
{"action": "forward"}          {"action": "backward"}
{"action": "turn_left"}        {"action": "turn_right"}
{"action": "pivot_left"}       {"action": "pivot_right"}
{"action": "stop"}             {"action": "brake"}
{"action": "speed_up"}         {"action": "speed_down"}
{"action": "set_speed", "value": 70}
{"action": "inspect_start"}    {"action": "inspect_stop"}
{"action": "inspect_pause"}    {"action": "inspect_resume"}
{"action": "estop"}            {"action": "estop_release"}
{"action": "light_on"}         {"action": "light_off"}
{"action": "light_set", "value": 80}
{"action": "snapshot"}         {"action": "ping"}
```

### Test de connexion

Depuis le PC opérateur, avec l'IP du Jetson Nano :

```bash
pip install websockets
python test_connection.py 192.168.1.100
```

---

## `web-poc/` — Interface opérateur

Tableau de bord web (HTML/CSS/JS pur, aucune dépendance serveur) simulant
l'interface opérateur complète. Ouvrir directement `index.html` dans un navigateur.

```
web-poc/
├── index.html   # Interface 6 onglets
├── app.js       # Logique métier, WebSocket client, rendu Canvas
└── style.css    # Thème sombre SIANA
```

**Onglets :**
1. **Dashboard** — KPIs temps réel (distance, anomalies, batterie, vitesse)
2. **Inspection Live** — Flux caméra simulé + détections IA + timeline
3. **Preuves & Validation** — Galerie anomalies, workflow confirm/reject
4. **Système IA** — Pipeline YOLOv8, métriques, courbe Précision/Rappel
5. **Architecture** — Schéma réseau robot ↔ station
6. **Rapport** — Tableau anomalies confirmées + conclusion opérationnelle

> Pour connecter le web-poc au robot réel, modifier l'URL WebSocket dans `app.js` :
> `const WS_URL = "ws://IP_JETSON:8765";`

---

## `Notebook/` — Pipeline IA (`siana.ipynb`)

Notebook Jupyter documentant le **fine-tuning de YOLOv8** sur le dataset MVTec AD pour la détection d'anomalies ferroviaires, depuis la préparation des données jusqu'au rapport d'inspection opérationnel.  
Le modèle **YOLOv8n pré-entraîné (COCO)** est ré-entraîné (fine-tuning par transfer learning) sur 6 classes d'anomalies ferroviaires propres à SIANA, sans avoir besoin d'un dataset ferroviaire annoté.  
Reproductible sur **Kaggle Free Tier** (GPU P100/T4 ou CPU) sans modification.

```
Notebook/
└── siana.ipynb   # Pipeline YOLOv8 bout-en-bout
```

### Pipeline automatisé (étapes)

1. **Exploration du dataset MVTec AD** — détection automatique du chemin, comptage des images, statistiques par catégorie.
2. **Conversion masques → bounding boxes YOLO** — les masques binaires pixel-level sont transformés en annotations YOLO (`class_id x_center y_center width height`) par analyse de composantes connexes. Un filtre de bruit élimine les composantes inférieures à 0,05 % de la surface.
3. **Split stratifié** — 70 % / 15 % / 15 % (train/val/test), distribution par classe respectée.
4. **Fine-tuning YOLOv8n** — transfer learning sur les 6 classes ferroviaires SIANA.
5. **Évaluation** — matrice de confusion, courbe Précision/Rappel, métriques globales.
6. **Rapport d'inspection** — pour chaque image, le système génère un statut global et la liste des anomalies détectées avec score de confiance et bounding box.

### Mapping sémantique MVTec AD → classes ferroviaires

| ID | Classe ferroviaire | Défauts MVTec AD correspondants |
|---|---|---|
| 0 | **Fissure** | crack, broken, cut_\*, broken_teeth |
| 1 | **Corrosion** | color, contamination, stain, faulty_imprint |
| 2 | **Fuite** | oil, liquid, glue, glue_strip |
| 3 | **Pièce manquante** | hole, missing_wire, missing_cable, cut_lead |
| 4 | **Pièce desserrée** | bent, flip, misplaced, poke, bent_wire |
| 5 | **Usure** | scratch, rough, thread, combined |

### Grille de sévérité intégrée

| Classe | Sévérité | Action déclenchée |
|---|---|---|
| Fissure | 🔴 CRITIQUE | Alerte immédiate — immobilisation |
| Fuite | 🔴 CRITIQUE | Alerte immédiate — immobilisation |
| Pièce manquante | 🔴 CRITIQUE | Alerte immédiate — immobilisation |
| Corrosion | 🟠 MAJEUR | Maintenance prioritaire planifiée |
| Pièce desserrée | 🟠 MAJEUR | Maintenance prioritaire planifiée |
| Usure | 🟡 MINEUR | Surveillance — maintenance préventive |

### Métriques du modèle (PoC)

| Métrique | Valeur |
|---|---|
| mAP@0.5 | **0.847** |
| Précision | **0.891** |
| Rappel | **0.823** |
| Inférence GPU (T4/P100) | < 15 ms |

### Limites et feuille de route

- MVTec AD est un dataset de laboratoire — les performances sur images réelles d'inspection sous TGV seront différentes.  
- Prochaines étapes : dataset ferroviaire dédié (> 5 000 images annotées), passage à YOLOv8s/m, segmentation d'instance (YOLOv8-seg), intégration TensorRT sur **Jetson Orin Nano** (< 10 ms/image).

```bash
pip install ultralytics jupyter
jupyter notebook Notebook/siana.ipynb
```

---

## Architecture globale

```
┌──────────────────────────────────────────────────────────┐
│  Station de contrôle (PC opérateur)                      │
│  ┌──────────────┐   ┌────────────────────────────────┐   │
│  │  web-poc     │   │  siana.ipynb (IA — YOLOv8)     │   │
│  │  (navigateur)│   │  Inférence GPU — détection      │   │
│  └──────┬───────┘   └────────────────────────────────┘   │
│         │ WebSocket ws://IP:8765 + HTTP :8080             │
└─────────┼────────────────────────────────────────────────┘
          │ WiFi 802.11ac (portée ≥ 50 m)
┌─────────┼────────────────────────────────────────────────┐
│  Robot (NVIDIA Jetson Nano)                               │
│         │                                                 │
│  ┌──────┴───────────────────────────────────────────┐    │
│  │  server/api.py  — WebSocket + HTTP REST + MJPEG  │    │
│  ├──────────────────────────────────────────────────┤    │
│  │  control/navigation.py — automate d'états        │    │
│  │  control/safety.py     — E-STOP, watchdog, fosse │    │
│  ├──────────────────────────────────────────────────┤    │
│  │  hardware/motors.py    — traction différentielle  │    │
│  │  hardware/camera.py    — stream MJPEG 1080p/30fps │    │
│  │  hardware/sensors.py   — ultrasons + batterie     │    │
│  │  hardware/leds.py      — signalisation + éclairage│    │
│  └──────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────┘
          Fosse d'inspection RGVM — 200 m
```

---

## Exigences couvertes (CdC 2026)

| Exigence | Valeur CdC | Implémentation |
|---|---|---|
| Vitesse déplacement | 3–5 km/h | PWM 20 kHz + rampe `motors.py` |
| Autonomie batterie | ≥ 4 h | INA219 + alerte SOC `sensors.py` |
| Résolution caméra | Full HD | 1920×1080 @ 30 fps `camera.py` |
| Latence streaming | < 500 ms | MJPEG direct + WebSocket 5 Hz |
| Portée pilotage | ≥ 50 m | WiFi 802.11ac `server/api.py` |
| Protocoles réseau | TCP/IP, HTTP, WebSocket | `server/api.py` |
| Arrêt d'urgence | Physique + sans fil | GPIO interrupt + commande WS |
| Signalisation LED | Rouge/Orange/Vert | 8 patterns `leds.py` |
| Watchdog connexion | Oui | 15 s sans commande → arrêt |
| Limite fosse | 200 m | Odométrie + arrêt auto `safety.py` |

---

## Équipe

| Membre | Spécialité | Contribution |
|---|---|---|
| **AMLLAL Amine** | Intelligence Artificielle et Data Technologies : Systemes industriels | Architecture logicielle, IA, téléopération |
| **SAIH Rania** | Génie industriel | Organisation des processus d'inspection, analyse fonctionnelle |
| **LAOUNI Ikhlass** | Génie électromécanique | Motorisation, câblage, actionneurs, capteurs |
| **BENHSAIN Maryam** | Génie mécanique | Conception structurelle, châssis, dimensionnement |
| **BOUKILI Rouaya** | Génie mécanique | Intégration mécanique, compatibilité gabarit fosse |

**Établissement** : ENSAM-Meknès  
**Compétition** : Prix InnovAM'26 — Édition 2026
