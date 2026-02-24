/* ============================================================
   SIANA — TGV Inspection Robot PoC — Main Application Logic
   ============================================================ */

'use strict';

// ─── STATE ──────────────────────────────────────────────────────────────────
const state = {
  started: false,
  startTime: Date.now(),
  sessionId: 'INS-2026-0224-001',
  frames: 0,
  distance: 0,
  battery: 87,
  cpuTemp: 42,
  latency: 18,
  wifi: 94,
  robotX: 0, robotY: 0, robotTheta: 0,
  speed: 30,
  zoom: 1,
  aiMode: 'continuous',
  alertCount: 0,
  detections: [],       // current frame detections
  evidence: [],         // stored evidence list
  filter: 'all',
  inspectionRunning: true,
  frameTime: 0,
  currentDetectionColor: null,
  // Proba parameters for anomaly generation
  anomalyProb: 0.006,
  // Chart references
  anomChart: null,
  prChart: null,
  // Counters by type
  typeCount: { crack: 0, scratch: 0, corrosion: 0, loose_part: 0, missing_bolt: 0, deformation: 0 },
  reportGenerated: false,
  duration: 0,
};

// ─── CONSTANTS ────────────────────────────────────────────────────────────────
const ANOM_TYPES = ['crack', 'scratch', 'corrosion', 'loose_part', 'missing_bolt', 'deformation'];
const ANOM_COLORS = {
  crack: '#e55',
  scratch: '#f0883e',
  corrosion: '#d29922',
  loose_part: '#8957e5',
  missing_bolt: '#58a6ff',
  deformation: '#3fb950',
};
const ANOM_LABELS = {
  crack: 'Fissure',
  scratch: 'Rayure',
  corrosion: 'Corrosion',
  loose_part: 'Pièce desserrée',
  missing_bolt: 'Boulon manquant',
  deformation: 'Déformation',
};
const SEVERITY_COLORS = { low: '#3fb950', medium: '#d29922', high: '#f0883e', critical: '#e55' };

// ─── TAB NAVIGATION ──────────────────────────────────────────────────────────
const BREADCRUMBS = {
  dashboard: 'Tableau de bord',
  inspection: 'Inspection Live',
  evidence: 'Preuves & Validation',
  ai: 'Système IA',
  architecture: 'Architecture',
  report: 'Rapport',
};

function initTabs() {
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      const tab = item.dataset.tab;
      document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
      item.classList.add('active');
      document.getElementById('tab-' + tab).classList.add('active');
      document.getElementById('breadcrumb').textContent = BREADCRUMBS[tab];
      if (tab === 'evidence') renderEvidence();
      if (tab === 'report') updateReport();
    });
  });

  // Sidebar toggle
  const sidebar = document.getElementById('sidebar');
  const mainContent = document.querySelector('.main-content');
  document.getElementById('sidebarToggle').addEventListener('click', () => {
    sidebar.classList.toggle('collapsed');
    mainContent.classList.toggle('full');
  });
}

// ─── CLOCK ───────────────────────────────────────────────────────────────────
function updateClock() {
  const now = new Date();
  document.getElementById('topbarTime').textContent = now.toLocaleTimeString('fr-FR');
  state.duration = Math.floor((Date.now() - state.startTime) / 1000);
}

// ─── CANVAS DRAWING ──────────────────────────────────────────────────────────
// Simulate industrial camera view of train undercarriage
const BG_COLORS = ['#0a0d13', '#0c1018', '#0d1117', '#0b0e16'];
const PIPE_PATTERNS = [];

function buildSceneParticles(canvas) {
  const parts = [];
  const W = canvas.width, H = canvas.height;
  // horizontal pipes/rails
  for (let i = 0; i < 4; i++) {
    parts.push({ type: 'pipe', y: H * (.15 + i * .2), r: 6 + Math.random() * 8, color: ['#2a3547','#344055','#1e2d3d','#263347'][i % 4] });
  }
  // bolts
  for (let i = 0; i < 18; i++) {
    parts.push({ type: 'bolt', x: (i * 47 + 20) % W, y: 30 + Math.random() * (H - 60), r: 5 + Math.random() * 3 });
  }
  // surface marks
  for (let i = 0; i < 30; i++) {
    parts.push({ type: 'mark', x: Math.random() * W, y: Math.random() * H, w: 2 + Math.random() * 60, h: 1 });
  }
  return parts;
}

function drawScene(ctx, W, H, time, zoom = 1) {
  // Background
  ctx.fillStyle = '#090c13';
  ctx.fillRect(0, 0, W, H);

  const offsetX = Math.sin(time * 0.3) * 15 * zoom;
  const offsetY = time * 2 % H;

  // Main body panels
  ctx.fillStyle = '#111926';
  ctx.fillRect(0, H * .1, W, H * .8);

  // Horizontal ribs / beams
  const ribColors = ['#1a2535', '#1f2d40', '#162030', '#1c2940'];
  for (let i = 0; i < 5; i++) {
    const ry = (H * (.08 + i * .17) + offsetY * .3) % H;
    const gradient = ctx.createLinearGradient(0, ry, 0, ry + 22);
    gradient.addColorStop(0, ribColors[i % 4]);
    gradient.addColorStop(.5, '#253348');
    gradient.addColorStop(1, ribColors[i % 4]);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, ry, W, 24);
  }

  // Vertical supports
  for (let i = 0; i < 7; i++) {
    const vx = ((i * (W / 6)) + offsetX * .5 + W) % W;
    ctx.fillStyle = '#1d2b3d';
    ctx.fillRect(vx - 8, H * .1, 16, H * .8);
    ctx.fillStyle = '#243347';
    ctx.fillRect(vx - 4, H * .1, 8, H * .8);
  }

  // Bolts
  for (let i = 0; i < 20; i++) {
    const bx = ((i * 53 + 15 + offsetX * .7) % (W - 20)) + 10;
    const by = ((i * 37 + 10 + offsetY * .2) % (H - 20)) + 10;
    ctx.beginPath();
    ctx.arc(bx, by, 5, 0, Math.PI * 2);
    ctx.fillStyle = '#3a4e68';
    ctx.fill();
    ctx.strokeStyle = '#5a7090';
    ctx.lineWidth = 1.5;
    ctx.stroke();
    // bolt cross
    ctx.strokeStyle = '#4a6080';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(bx - 4, by); ctx.lineTo(bx + 4, by); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(bx, by - 4); ctx.lineTo(bx, by + 4); ctx.stroke();
  }

  // Cables
  for (let c = 0; c < 3; c++) {
    ctx.beginPath();
    const cy = H * (.3 + c * .15);
    ctx.moveTo(-20, cy + Math.sin(offsetX * .02) * 8);
    for (let x = 0; x <= W + 20; x += 10) {
      ctx.lineTo(x, cy + Math.sin((x + offsetX) * .05) * 6);
    }
    ctx.strokeStyle = ['#2a7a5a', '#3a4f6a', '#4a3a6a'][c];
    ctx.lineWidth = 3;
    ctx.stroke();
  }

  // Surface texture noise
  for (let i = 0; i < 60; i++) {
    const nx = (i * 71 + time * 80) % W;
    const ny = (i * 43 + time * 30) % H;
    ctx.fillStyle = `rgba(255,255,255,${0.01 + Math.random() * 0.02})`;
    ctx.fillRect(nx, ny, 1 + Math.random() * 40, 1);
  }

  // Scan line effect
  const scanY = (time * 60) % (H + 40) - 20;
  const scanGrad = ctx.createLinearGradient(0, scanY, 0, scanY + 40);
  scanGrad.addColorStop(0, 'rgba(0,150,255,0)');
  scanGrad.addColorStop(.5, 'rgba(0,150,255,0.04)');
  scanGrad.addColorStop(1, 'rgba(0,150,255,0)');
  ctx.fillStyle = scanGrad;
  ctx.fillRect(0, scanY, W, 40);
}

function drawDetectionBoxes(ctx, dets, W, H) {
  dets.forEach(det => {
    const col = ANOM_COLORS[det.type] || '#ff0';
    ctx.strokeStyle = col;
    ctx.lineWidth = 2.5;
    ctx.setLineDash([]);
    ctx.strokeRect(det.bx, det.by, det.bw, det.bh);

    // Corners accent
    const cs = 12;
    ctx.lineWidth = 3;
    const corners = [
      [det.bx, det.by, cs, 0, 0, cs],
      [det.bx + det.bw, det.by, -cs, 0, 0, cs],
      [det.bx, det.by + det.bh, cs, 0, 0, -cs],
      [det.bx + det.bw, det.by + det.bh, -cs, 0, 0, -cs],
    ];
    corners.forEach(([x, y, dx1, dy1, dx2, dy2]) => {
      ctx.beginPath(); ctx.moveTo(x + dx1, y); ctx.lineTo(x, y); ctx.lineTo(x, y + dy2); ctx.stroke();
    });

    // Label
    const label = `${ANOM_LABELS[det.type] || det.type}  ${(det.conf * 100).toFixed(0)}%`;
    ctx.font = 'bold 12px monospace';
    const tw = ctx.measureText(label).width;
    const lx = det.bx, ly = det.by > 20 ? det.by - 20 : det.by + 24;
    ctx.fillStyle = col;
    ctx.fillRect(lx, ly - 14, tw + 10, 18);
    ctx.fillStyle = '#000';
    ctx.fillText(label, lx + 5, ly);
  });
}

function drawHUD(ctx, W, H, state) {
  // Top-left info
  ctx.font = '11px monospace';
  ctx.fillStyle = 'rgba(0,200,100,0.85)';
  ctx.fillText(`POS: (${state.robotX.toFixed(2)}, ${state.robotY.toFixed(2)}) θ:${state.robotTheta.toFixed(1)}°`, 10, 18);
  ctx.fillText(`FRAME: ${state.frames}  |  DIST: ${state.distance.toFixed(2)}m`, 10, 32);

  // Top-right AI status
  const aiText = state.aiMode === 'off' ? 'IA: OFF' : 'IA: ACTIF (YOLOv8)';
  ctx.fillStyle = state.aiMode === 'off' ? 'rgba(200,80,80,0.9)' : 'rgba(0,200,100,0.9)';
  ctx.font = 'bold 11px monospace';
  const tw = ctx.measureText(aiText).width;
  ctx.fillText(aiText, W - tw - 10, 18);

  // Bottom right timestamp
  const ts = new Date().toLocaleTimeString('fr-FR', { hour12: false });
  ctx.font = '10px monospace';
  ctx.fillStyle = 'rgba(180,200,220,0.6)';
  ctx.fillText(ts, W - ctx.measureText(ts).width - 8, H - 8);

  // Grid overlay (faint)
  ctx.strokeStyle = 'rgba(40,80,120,0.15)';
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 8]);
  for (let x = 0; x <= W; x += W / 4) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
  for (let y = 0; y <= H; y += H / 3) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
  ctx.setLineDash([]);
}

// ─── SLAM MAP ────────────────────────────────────────────────────────────────
const slamPath = [];
function drawSlam(canvas) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  ctx.fillStyle = '#0a0e14';
  ctx.fillRect(0, 0, W, H);

  // Grid
  ctx.strokeStyle = 'rgba(40,80,120,0.3)';
  ctx.lineWidth = 1;
  for (let x = 0; x <= W; x += 20) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
  for (let y = 0; y <= H; y += 20) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }

  // Path
  if (slamPath.length > 1) {
    ctx.beginPath();
    const cx = W / 2, cy = H / 2, scale = 25;
    ctx.moveTo(cx + slamPath[0].x * scale, cy - slamPath[0].y * scale);
    slamPath.forEach(p => ctx.lineTo(cx + p.x * scale, cy - p.y * scale));
    ctx.strokeStyle = 'rgba(10,110,255,0.6)';
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  // Evidence markers on map
  state.evidence.forEach(ev => {
    const cx = W / 2, cy = H / 2, scale = 25;
    const mx = cx + ev.pos.x * scale, my = cy - ev.pos.y * scale;
    ctx.beginPath();
    ctx.arc(mx, my, 4, 0, Math.PI * 2);
    ctx.fillStyle = ev.status === 'confirmed' ? '#3fb950' : ev.status === 'rejected' ? '#8b949e' : '#e55';
    ctx.fill();
  });

  // Robot position
  const cx2 = W / 2, cy2 = H / 2, scale2 = 25;
  const rx = cx2 + state.robotX * scale2, ry = cy2 - state.robotY * scale2;
  ctx.save();
  ctx.translate(rx, ry);
  ctx.rotate(state.robotTheta * Math.PI / 180);
  ctx.beginPath();
  ctx.moveTo(0, -10); ctx.lineTo(6, 6); ctx.lineTo(-6, 6); ctx.closePath();
  ctx.fillStyle = '#0A6EFF';
  ctx.fill();
  ctx.restore();
}

// ─── MAIN CANVAS LOOP ────────────────────────────────────────────────────────
const miniCanvas = document.getElementById('miniCanvas');
const mainCanvas = document.getElementById('mainCanvas');
const miniCtx = miniCanvas ? miniCanvas.getContext('2d') : null;
const mainCtx = mainCanvas ? mainCanvas.getContext('2d') : null;
const slamCanvas = document.getElementById('slamCanvas');

let lastAnimTime = 0;
let sceneTime = 0;

function animationLoop(ts) {
  const dt = (ts - lastAnimTime) / 1000;
  lastAnimTime = ts;
  sceneTime += dt;

  if (!state.inspectionRunning) { requestAnimationFrame(animationLoop); return; }

  // Update physics
  state.frames++;
  const speedM = (state.speed / 100) * 0.15;
  state.robotX += Math.cos(state.robotTheta * Math.PI / 180) * speedM * dt;
  state.robotY += Math.sin(state.robotTheta * Math.PI / 180) * speedM * dt;
  state.robotTheta += (Math.random() - 0.48) * 2;
  state.distance += speedM * dt;

  // Add to SLAM path periodically
  if (state.frames % 5 === 0 && slamPath.length < 500) {
    slamPath.push({ x: state.robotX, y: state.robotY });
  }

  // Update dashboard position
  if (state.frames % 3 === 0) {
    const dEl = d => document.getElementById(d);
    dEl('posX') && (dEl('posX').textContent = state.robotX.toFixed(2) + ' m');
    dEl('posY') && (dEl('posY').textContent = state.robotY.toFixed(2) + ' m');
    dEl('posTheta') && (dEl('posTheta').textContent = state.robotTheta.toFixed(1) + '°');
    dEl('posSpeed') && (dEl('posSpeed').textContent = (speedM * 100 * state.speed / 30).toFixed(1) + ' cm/s');
    dEl('miniPos') && (dEl('miniPos').textContent = `Pos: (${state.robotX.toFixed(2)}, ${state.robotY.toFixed(2)})`);
  }

  // AI detections
  let currentDets = [];
  if (state.aiMode !== 'off' && Math.random() < state.anomalyProb) {
    const type = ANOM_TYPES[Math.floor(Math.random() * ANOM_TYPES.length)];
    const W = mainCanvas.width, H = mainCanvas.height;
    const bw = 60 + Math.random() * 120, bh = 50 + Math.random() * 90;
    const bx = Math.random() * (W - bw), by = Math.random() * (H - bh);
    const conf = 0.52 + Math.random() * 0.44;
    const det = { type, conf, bx, by, bw, bh, id: Date.now(), x: state.robotX, y: state.robotY };
    currentDets = [det];
    state.detections = [det];
    handleNewDetection(det);
  } else {
    if (Math.random() > 0.05) state.detections = [];
  }

  // Draw main canvas
  if (mainCtx) {
    const W = mainCanvas.width, H = mainCanvas.height;
    drawScene(mainCtx, W, H, sceneTime, state.zoom);
    if (state.detections.length) drawDetectionBoxes(mainCtx, state.detections, W, H);
    drawHUD(mainCtx, W, H, state);
  }

  // Draw mini canvas (same scene, smaller)
  if (miniCtx) {
    const W2 = miniCanvas.width, H2 = miniCanvas.height;
    drawScene(miniCtx, W2, H2, sceneTime, 1);
    if (state.detections.length) {
      const scaleX = W2 / mainCanvas.width, scaleY = H2 / mainCanvas.height;
      const scaledDets = state.detections.map(d => ({ ...d, bx: d.bx * scaleX, by: d.by * scaleY, bw: d.bw * scaleX, bh: d.bh * scaleY }));
      drawDetectionBoxes(miniCtx, scaledDets, W2, H2);
    }
  }

  // Draw SLAM
  if (slamCanvas) drawSlam(slamCanvas);

  // Update KPIs
  if (state.frames % 10 === 0) updateKPIs();

  // Sensor fluctuation
  if (state.frames % 30 === 0) {
    state.battery = Math.max(0, state.battery - 0.05);
    state.cpuTemp = 38 + Math.abs(Math.sin(sceneTime * 0.2)) * 18 + (state.speed / 10);
    state.latency = 12 + Math.abs(Math.sin(sceneTime * 0.5)) * 20;
    state.wifi = 85 + Math.random() * 12;
    updateSensorBars();
  }

  requestAnimationFrame(animationLoop);
}

// ─── HANDLE NEW AI DETECTION ─────────────────────────────────────────────────
function handleNewDetection(det) {
  state.alertCount++;
  document.getElementById('alertCount').textContent = state.alertCount;
  state.typeCount[det.type] = (state.typeCount[det.type] || 0) + 1;

  // Add to evidence
  const ev = {
    id: 'EV-' + String(state.evidence.length + 1).padStart(3, '0'),
    type: det.type,
    conf: det.conf,
    pos: { x: parseFloat(state.robotX.toFixed(2)), y: parseFloat(state.robotY.toFixed(2)) },
    timestamp: new Date(),
    source: 'ai',
    status: 'pending',
    desc: '',
    imgData: captureCanvasSnapshot(mainCanvas),
  };
  state.evidence.unshift(ev);

  // Toast notification
  showToast(
    'warn',
    '⚠ Détection IA',
    `${ANOM_LABELS[det.type]} — Conf. ${(det.conf * 100).toFixed(0)}% @ (${ev.pos.x}, ${ev.pos.y})`,
    5000
  );

  // Update detection list in inspection tab
  renderDetectionList();
  updateEvidenceCounts();
  updateAnomalyChart();
  addTimelineEvent('warn', `IA: ${ANOM_LABELS[det.type]} détecté (${(det.conf * 100).toFixed(0)}%)`);
}

// Capture snapshot of current canvas frame
function captureCanvasSnapshot(canvas) {
  try { return canvas.toDataURL('image/jpeg', 0.7); } catch { return null; }
}

// ─── DETECTION LIST PANEL ─────────────────────────────────────────────────────
function renderDetectionList() {
  const list = document.getElementById('detectionList');
  if (!list) return;
  const pending = state.evidence.filter(e => e.status === 'pending').slice(0, 5);
  if (!pending.length) {
    list.innerHTML = '<div class="empty-state">Aucune détection en attente</div>';
    return;
  }
  list.innerHTML = pending.map(ev => `
    <div class="detection-item alert" id="det-${ev.id}">
      <div class="det-type" style="color:${ANOM_COLORS[ev.type]}">${ANOM_LABELS[ev.type]}</div>
      <div class="det-conf">Confiance: ${(ev.conf * 100).toFixed(0)}% — Pos: (${ev.pos.x}, ${ev.pos.y})</div>
      <div class="conf-bar"><div class="conf-fill" style="width:${ev.conf * 100}%;background:${ANOM_COLORS[ev.type]}"></div></div>
      <div class="det-actions">
        <button class="btn btn-sm btn-success" onclick="validateEvidence('${ev.id}')">✓ Confirmer</button>
        <button class="btn btn-sm btn-secondary" onclick="rejectEvidence('${ev.id}')">✕ Rejeter</button>
      </div>
    </div>
  `).join('');
}

// ─── EVIDENCE PAGE ────────────────────────────────────────────────────────────
function renderEvidence() {
  const grid = document.getElementById('evidenceGrid');
  if (!grid) return;
  const filtered = state.evidence.filter(ev => state.filter === 'all' || ev.status === state.filter);

  if (!filtered.length) {
    grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;opacity:.5;">
      Aucune preuve enregistrée${state.filter !== 'all' ? ' dans cette catégorie' : ''}.</div>`;
    return;
  }

  grid.innerHTML = filtered.map(ev => `
    <div class="evidence-card ev-${ev.status}" id="ev-${ev.id}">
      <div class="ev-img-wrap">
        ${ev.imgData
          ? `<img src="${ev.imgData}" style="width:100%;height:100%;object-fit:cover;" />`
          : `<canvas width="300" height="180" style="width:100%;height:100%;" data-evid="${ev.id}" class="ev-scene-canvas"></canvas>`
        }
        <span class="ev-source-badge ${ev.source}">${ev.source === 'ai' ? 'IA' : 'Manuel'}</span>
      </div>
      <div class="ev-body">
        <div class="ev-type" style="color:${ANOM_COLORS[ev.type]}">${ANOM_LABELS[ev.type] || ev.type}</div>
        <div class="ev-meta">
          ${ev.source === 'ai' ? `Conf. IA: <strong>${(ev.conf * 100).toFixed(0)}%</strong><br>` : ''}
          Position: (${ev.pos.x}, ${ev.pos.y})<br>
          ${ev.timestamp.toLocaleString('fr-FR')}<br>
          ${ev.desc ? `Note: ${ev.desc}` : ''}
        </div>
        ${ev.status === 'pending' ? `
          <div class="ev-actions">
            <button class="btn btn-sm btn-success" onclick="validateEvidence('${ev.id}')">✓ Confirmer</button>
            <button class="btn btn-sm btn-secondary" onclick="rejectEvidence('${ev.id}')">✕ Rejeter</button>
          </div>
        ` : `<span class="ev-status-label ${ev.status}">${ev.status === 'confirmed' ? '✓ Confirmée' : '✕ Rejetée'}</span>`}
      </div>
    </div>
  `).join('');

  // Draw scene on canvases that don't have images
  grid.querySelectorAll('.ev-scene-canvas').forEach(c => {
    const ctx = c.getContext('2d');
    drawScene(ctx, c.width, c.height, Math.random() * 10, 1);
    const ev = state.evidence.find(e => e.id === c.dataset.evid);
    if (ev && ev.type) {
      const bx = 80 + Math.random() * 100, by = 60 + Math.random() * 60;
      drawDetectionBoxes(ctx, [{ type: ev.type, conf: ev.conf, bx, by, bw: 100, bh: 70 }], c.width, c.height);
    }
  });

  updateEvidenceCounts();
}

function updateEvidenceCounts() {
  const all = state.evidence.length;
  const pending = state.evidence.filter(e => e.status === 'pending').length;
  const confirmed = state.evidence.filter(e => e.status === 'confirmed').length;
  const rejected = state.evidence.filter(e => e.status === 'rejected').length;
  const s = id => document.getElementById(id);
  s('countAll') && (s('countAll').textContent = all);
  s('countPending') && (s('countPending').textContent = pending);
  s('countConfirmed') && (s('countConfirmed').textContent = confirmed);
  s('countRejected') && (s('countRejected').textContent = rejected);
  s('kpiAnomalies') && (s('kpiAnomalies').textContent = all);
  s('kpiValidated') && (s('kpiValidated').textContent = confirmed);
}

window.validateEvidence = function(id) {
  const ev = state.evidence.find(e => e.id === id);
  if (ev) {
    ev.status = 'confirmed';
    showToast('success', '✓ Anomalie confirmée', `${ANOM_LABELS[ev.type]} validée par l'opérateur`, 3000);
    addTimelineEvent('success', `Anomalie confirmée: ${ANOM_LABELS[ev.type]}`);
    renderEvidence();
    renderDetectionList();
    updateEvidenceCounts();
  }
};

window.rejectEvidence = function(id) {
  const ev = state.evidence.find(e => e.id === id);
  if (ev) {
    ev.status = 'rejected';
    showToast('info', '✕ Rejeté', `Détection rejetée par l'opérateur`, 2000);
    renderEvidence();
    renderDetectionList();
    updateEvidenceCounts();
  }
};

// Filter buttons
document.querySelectorAll('[data-filter]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('[data-filter]').forEach(b => b.classList.remove('active-filter'));
    btn.classList.add('active-filter');
    state.filter = btn.dataset.filter;
    renderEvidence();
  });
});

document.getElementById('btnValidateAll')?.addEventListener('click', () => {
  state.evidence.filter(e => e.status === 'pending').forEach(e => e.status = 'confirmed');
  renderEvidence();
  updateEvidenceCounts();
  showToast('success', '✓ Validation groupée', 'Toutes les preuves en attente ont été confirmées', 3000);
});

// ─── KPI UPDATE ───────────────────────────────────────────────────────────────
function updateKPIs() {
  const s = id => document.getElementById(id);
  s('kpiDist') && (s('kpiDist').textContent = state.distance.toFixed(1) + ' m');
  s('kpiFrames') && (s('kpiFrames').textContent = state.frames.toLocaleString('fr-FR'));
  s('rDist') && (s('rDist').textContent = state.distance.toFixed(1) + ' m');
  // Duration
  const mins = String(Math.floor(state.duration / 60)).padStart(2, '0');
  const secs = String(state.duration % 60).padStart(2, '0');
  s('rDuration') && (s('rDuration').textContent = `${mins}:${secs}`);
}

function updateSensorBars() {
  const s = id => document.getElementById(id);
  const setBar = (id, val, maxVal, unit) => {
    const bar = document.getElementById(id + 'Bar');
    const valEl = document.getElementById(id + 'Val');
    if (bar) bar.style.width = Math.min(100, (val / maxVal) * 100) + '%';
    if (valEl) valEl.textContent = val.toFixed(0) + (unit || '');
  };
  setBar('batt', state.battery, 100, '%');
  setBar('cpu', state.cpuTemp, 85, '°C');
  setBar('lat', state.latency, 100, ' ms');
  setBar('wifi', state.wifi, 100, '%');

  // Color update
  const cpuBar = document.getElementById('cpuBar');
  if (cpuBar) {
    cpuBar.className = 'progress-fill ' + (state.cpuTemp > 70 ? 'red' : state.cpuTemp > 55 ? 'orange' : 'green');
  }
}

// ─── TIMELINE ────────────────────────────────────────────────────────────────
const tlQueue = [];
function addTimelineEvent(type, text) {
  const tl = document.getElementById('timeline');
  if (!tl) return;
  const time = new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const item = document.createElement('li');
  item.className = 'timeline-item';
  item.innerHTML = `<div class="tl-dot ${type}"></div><span class="tl-time">${time}</span><span>${text}</span>`;
  tl.insertBefore(item, tl.firstChild);
  // Keep max 20
  while (tl.children.length > 20) tl.removeChild(tl.lastChild);
}

// ─── CHARTS ──────────────────────────────────────────────────────────────────
function initAnomalyChart() {
  const ctx = document.getElementById('anom-chart')?.getContext('2d');
  if (!ctx) return;
  state.anomChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: Object.keys(state.typeCount).map(k => ANOM_LABELS[k] || k),
      datasets: [{
        label: 'Détections',
        data: Object.values(state.typeCount),
        backgroundColor: Object.keys(state.typeCount).map(k => ANOM_COLORS[k] + '80'),
        borderColor: Object.keys(state.typeCount).map(k => ANOM_COLORS[k]),
        borderWidth: 1.5,
        borderRadius: 4,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: '#30363d' }, ticks: { color: '#8b949e', font: { size: 11 } } },
        y: { grid: { color: '#30363d' }, ticks: { color: '#8b949e', stepSize: 1 }, beginAtZero: true },
      },
    },
  });
}

function updateAnomalyChart() {
  if (!state.anomChart) return;
  state.anomChart.data.datasets[0].data = Object.values(state.typeCount);
  state.anomChart.update('none');
}

function initPRChart() {
  const ctx = document.getElementById('prChart')?.getContext('2d');
  if (!ctx) return;
  const pr = [];
  for (let i = 0; i <= 20; i++) {
    const r = i / 20;
    pr.push({ x: r, y: Math.min(1, 0.94 - 0.6 * r * r + 0.1 * Math.random()) });
  }
  state.prChart = new Chart(ctx, {
    type: 'line',
    data: {
      datasets: [{
        label: 'Précision / Rappel',
        data: pr,
        borderColor: '#0A6EFF',
        backgroundColor: 'rgba(10,110,255,0.1)',
        fill: true,
        pointRadius: 2,
        tension: 0.35,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: true,
      plugins: { legend: { labels: { color: '#8b949e', font: { size: 11 } } } },
      scales: {
        x: { type: 'linear', title: { display: true, text: 'Rappel', color: '#8b949e' }, grid: { color: '#30363d' }, ticks: { color: '#8b949e' }, min: 0, max: 1 },
        y: { title: { display: true, text: 'Précision', color: '#8b949e' }, grid: { color: '#30363d' }, ticks: { color: '#8b949e' }, min: 0, max: 1 },
      },
    },
  });
}

// ─── CONTROLS ─────────────────────────────────────────────────────────────────
document.getElementById('speedSlider')?.addEventListener('input', e => {
  state.speed = parseInt(e.target.value);
  document.getElementById('speedVal').textContent = state.speed + '%';
});
document.getElementById('zoomSlider')?.addEventListener('input', e => {
  state.zoom = parseFloat(e.target.value);
  document.getElementById('zoomVal').textContent = '×' + state.zoom.toFixed(1);
});
document.getElementById('aiMode')?.addEventListener('change', e => {
  state.aiMode = e.target.value;
  addTimelineEvent('info', `Mode IA changé: ${e.target.value}`);
});

// ─── MODALS ───────────────────────────────────────────────────────────────────
function openModal(id) { document.getElementById(id)?.classList.add('open'); }
function closeModal(id) { document.getElementById(id)?.classList.remove('open'); }

document.getElementById('btnAnomaly')?.addEventListener('click', () => openModal('anomalyModal'));
document.getElementById('closeAnomalyModal')?.addEventListener('click', () => closeModal('anomalyModal'));
document.getElementById('cancelAnomalyModal')?.addEventListener('click', () => closeModal('anomalyModal'));
document.getElementById('confirmAnomalyModal')?.addEventListener('click', () => {
  const type = document.getElementById('manualAnoType').value;
  const severity = document.getElementById('manualSeverity').value;
  const desc = document.getElementById('manualDesc').value.trim();
  const ev = {
    id: 'EV-' + String(state.evidence.length + 1).padStart(3, '0'),
    type, conf: 1.0, severity,
    pos: { x: parseFloat(state.robotX.toFixed(2)), y: parseFloat(state.robotY.toFixed(2)) },
    timestamp: new Date(),
    source: 'manual',
    status: 'confirmed',
    desc,
    imgData: captureCanvasSnapshot(mainCanvas),
  };
  state.evidence.unshift(ev);
  state.typeCount[type] = (state.typeCount[type] || 0) + 1;
  updateAnomalyChart();
  updateEvidenceCounts();
  addTimelineEvent('danger', `Manuel: ${ANOM_LABELS[type]} déclaré (${severity})`);
  showToast('danger', '⚠ Anomalie manuelle', `${ANOM_LABELS[type]} enregistrée`, 3000);
  closeModal('anomalyModal');
  document.getElementById('manualDesc').value = '';
});

document.getElementById('btnRemark')?.addEventListener('click', () => openModal('remarkModal'));
document.getElementById('closeRemarkModal')?.addEventListener('click', () => closeModal('remarkModal'));
document.getElementById('cancelRemarkModal')?.addEventListener('click', () => closeModal('remarkModal'));
document.getElementById('confirmRemarkModal')?.addEventListener('click', () => {
  const desc = document.getElementById('remarkDesc').value.trim();
  if (!desc) { showToast('warn', 'Description requise', 'Une remarque nécessite une description.', 3000); return; }
  const ev = {
    id: 'RQ-' + String(state.evidence.length + 1).padStart(3, '0'),
    type: 'remarque', conf: 0, severity: 'info',
    pos: { x: parseFloat(state.robotX.toFixed(2)), y: parseFloat(state.robotY.toFixed(2)) },
    timestamp: new Date(),
    source: 'manual',
    status: 'confirmed',
    desc,
    imgData: captureCanvasSnapshot(mainCanvas),
  };
  state.evidence.unshift(ev);
  addTimelineEvent('info', `Remarque: "${desc.slice(0, 30)}..."`);
  showToast('info', '📷 Remarque enregistrée', desc.slice(0, 50), 3000);
  closeModal('remarkModal');
  document.getElementById('remarkDesc').value = '';
});

// Close modal on overlay click
document.querySelectorAll('.modal-overlay').forEach(overlay => {
  overlay.addEventListener('click', e => {
    if (e.target === overlay) overlay.classList.remove('open');
  });
});

// ─── TOAST ───────────────────────────────────────────────────────────────────
function showToast(type, title, msg, duration = 4000) {
  const container = document.getElementById('toastContainer');
  const icons = { warn: '⚠', danger: '🔴', success: '✓', info: 'ℹ' };
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<div class="toast-icon">${icons[type] || '•'}</div>
    <div class="toast-content"><div class="toast-title">${title}</div><div class="toast-msg">${msg}</div></div>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'slideOut .3s ease forwards';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// ─── REPORT ──────────────────────────────────────────────────────────────────
function updateReport() {
  const confirmed = state.evidence.filter(e => e.status === 'confirmed' && e.type !== 'remarque');
  const tbody = document.getElementById('reportTableBody');
  const summary = document.getElementById('reportSummary');
  const conclusion = document.getElementById('reportConclusion');

  document.getElementById('rDist') && (document.getElementById('rDist').textContent = state.distance.toFixed(1) + ' m');
  const mins = String(Math.floor(state.duration / 60)).padStart(2, '0');
  const secs = String(state.duration % 60).padStart(2, '0');
  document.getElementById('rDuration') && (document.getElementById('rDuration').textContent = `${mins}:${secs}`);

  if (confirmed.length === 0) {
    tbody && (tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;opacity:0.5">Aucune anomalie confirmée</td></tr>');
    summary && (summary.textContent = `Inspection en cours. ${state.evidence.length} preuves enregistrées, aucune anomalie confirmée à ce stade.`);
    conclusion && (conclusion.textContent = 'En attente de la fin de l\'inspection et de la validation complète.');
    return;
  }

  tbody && (tbody.innerHTML = confirmed.map((ev, i) => `
    <tr>
      <td>${i + 1}</td>
      <td><span style="color:${ANOM_COLORS[ev.type]};font-weight:700">${ANOM_LABELS[ev.type] || ev.type}</span></td>
      <td>${ev.source === 'ai' ? (ev.conf * 100).toFixed(0) + '%' : 'N/A (Manuel)'}</td>
      <td>(${ev.pos.x}, ${ev.pos.y})</td>
      <td>${ev.timestamp.toLocaleString('fr-FR')}</td>
      <td><span style="font-size:11px;text-transform:uppercase">${ev.source}</span></td>
      <td><span style="color:var(--green);font-weight:700">✓ Confirmée</span></td>
    </tr>
  `).join(''));

  const criticals = confirmed.filter(e => e.severity === 'critical').length;
  const highs = confirmed.filter(e => e.severity === 'high').length;
  summary && (summary.innerHTML = `
    <strong>${confirmed.length} anomalie(s) confirmée(s)</strong> lors de cette inspection.<br>
    Distance inspectée : ${state.distance.toFixed(1)} m — Durée : ${mins}:${secs}<br>
    ${criticals > 0 ? `⚠ <strong style="color:var(--red)">${criticals} anomalie(s) critique(s)</strong> — Intervention immédiate requise.` : ''}
    ${highs > 0 ? `<br>🔶 ${highs} anomalie(s) de haute sévérité.` : ''}
  `);

  conclusion && (conclusion.innerHTML = `
    ${criticals > 0
      ? '🔴 <strong>IMMOBILISATION RECOMMANDÉE</strong> — Des anomalies critiques ont été détectées. Ne pas remettre ce TGV en service avant intervention maintenance.'
      : highs > 0
        ? '🟠 <strong>MAINTENANCE PRIORITAIRE</strong> — Programmer une intervention dans les meilleurs délais.'
        : '🟢 <strong>REMISE EN SERVICE AUTORISÉE</strong> — Anomalies mineures détectées, surveillance recommandée.'
    }
  `);
}

document.getElementById('btnGenerateReport')?.addEventListener('click', () => {
  updateReport();
  showToast('success', '📄 Rapport généré', `${state.evidence.filter(e => e.status === 'confirmed').length} anomalie(s) confirmée(s)`, 4000);
  addTimelineEvent('success', 'Rapport d\'inspection généré');
});

// ─── INIT DEMO DATA ──────────────────────────────────────────────────────────
function seedDemoData() {
  const types = ['crack', 'corrosion', 'missing_bolt', 'scratch', 'loose_part'];
  const statuses = ['confirmed', 'confirmed', 'pending', 'rejected', 'pending', 'confirmed'];
  types.forEach((t, i) => {
    const ev = {
      id: 'EV-DEMO-' + (i + 1),
      type: t,
      conf: 0.65 + Math.random() * 0.3,
      pos: { x: parseFloat((Math.random() * 3).toFixed(2)), y: parseFloat((Math.random() * 1.5).toFixed(2)) },
      timestamp: new Date(Date.now() - (types.length - i) * 45000),
      source: i % 3 === 2 ? 'manual' : 'ai',
      status: statuses[i],
      desc: i === 2 ? 'Boulon côté droit bras de suspension avant' : '',
      imgData: null,
    };
    state.evidence.push(ev);
    state.typeCount[t]++;
    if (ev.status === 'pending') state.alertCount++;
  });
  document.getElementById('alertCount').textContent = state.alertCount;
  updateEvidenceCounts();
  updateAnomalyChart();

  // Initial timeline
  addTimelineEvent('info', 'Session d\'inspection démarrée');
  addTimelineEvent('info', 'Connexion robot établie (WiFi 94 Mbps)');
  addTimelineEvent('info', 'Flux vidéo actif — 1920×1080 @ 30fps');
  addTimelineEvent('info', 'Système IA YOLOv8 initialisé');
  addTimelineEvent('warn', 'IA: Corrosion détectée (74%) @ (1.23, 0.45)');
  addTimelineEvent('success', 'Anomalie confirmée: Fissure');
}

// ─── MAIN INIT ───────────────────────────────────────────────────────────────
function init() {
  initTabs();
  initAnomalyChart();
  initPRChart();
  seedDemoData();
  setInterval(updateClock, 1000);
  updateClock();
  requestAnimationFrame(animationLoop);
  addTimelineEvent('success', 'Interface PoC initialisée');
}

document.addEventListener('DOMContentLoaded', init);
