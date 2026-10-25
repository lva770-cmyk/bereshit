// Project 50 — 3D plant view (three.js). Generic 50 MW / 100 MWh, 5 PCS skids x 4 battery containers.
// Driven by the same simulated dispatch as the single-line diagram: update(netMW, socFraction).
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

const C = { out: 0xffb000, in: 0x6ea8ff, idle: 0x5fd38a, steel: 0x8d9299, dark: 0x2b2e33, white: 0xe9ebe6, concrete: 0x9a978e };

function canvasTex(w, h, draw, rep) {
  const c = document.createElement('canvas'); c.width = w; c.height = h; const g = c.getContext('2d'); draw(g, w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  if (rep) { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(rep[0], rep[1]); }
  return t;
}
// corrugated container wall
const ribTex = () => canvasTex(256, 64, (g, w, h) => {
  g.fillStyle = '#e8eae5'; g.fillRect(0, 0, w, h);
  for (let x = 0; x < w; x += 16) { const gr = g.createLinearGradient(x, 0, x + 16, 0);
    gr.addColorStop(0, '#d2d5cf'); gr.addColorStop(.35, '#f4f5f1'); gr.addColorStop(.7, '#dcdfd9'); gr.addColorStop(1, '#c9ccc5');
    g.fillStyle = gr; g.fillRect(x, 0, 16, h); }
}, [6, 1]);
const grilleTex = () => canvasTex(128, 128, (g, w, h) => {
  g.fillStyle = '#9aa1a8'; g.fillRect(0, 0, w, h); g.strokeStyle = '#5d646b'; g.lineWidth = 3; g.strokeRect(3, 3, w - 6, h - 6);
  for (let y = 6; y < h; y += 10) { g.beginPath(); g.moveTo(4, y); g.lineTo(w - 4, y); g.stroke(); }
});
const gravelTex = () => canvasTex(512, 512, (g, w, h) => {
  g.fillStyle = '#34342f'; g.fillRect(0, 0, w, h);
  for (let i = 0; i < 9000; i++) { const v = 40 + Math.random() * 40 | 0; g.fillStyle = `rgb(${v},${v},${v - 4})`; g.fillRect(Math.random() * w, Math.random() * h, 2, 2); }
}, [14, 8]);
const cabinetTex = () => canvasTex(256, 256, (g, w, h) => {
  g.fillStyle = '#b8c2cc'; g.fillRect(0, 0, w, h); g.strokeStyle = '#7d8893'; g.lineWidth = 4;
  for (let i = 0; i < 4; i++) g.strokeRect(6 + i * 62, 8, 56, h - 16);
  g.fillStyle = '#2a2e33'; for (let i = 0; i < 4; i++) g.fillRect(22 + i * 62, 30, 24, 40);
});

export function mount(host) {
  const W = () => host.clientWidth, H = () => host.clientHeight;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75)); renderer.setSize(W(), H());
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05; renderer.outputColorSpace = THREE.SRGBColorSpace;
  host.prepend(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = canvasTex(4, 256, (g, w, h) => { const gr = g.createLinearGradient(0, 0, 0, h); gr.addColorStop(0, '#0e1320'); gr.addColorStop(.55, '#1d2230'); gr.addColorStop(.8, '#2b2a24'); gr.addColorStop(1, '#22221c'); g.fillStyle = gr; g.fillRect(0, 0, w, h); });
  scene.fog = new THREE.Fog(0x24241f, 170, 360);
  const camera = new THREE.PerspectiveCamera(38, W() / H(), 0.5, 600);
  const home = { pos: new THREE.Vector3(), target: new THREE.Vector3(-22, 0, 0) };
  const frameHome = () => { const asp = W() / H(); const dist = 92 / Math.min(1.0, Math.max(0.42, asp * 0.6));
    home.pos.copy(home.target).add(new THREE.Vector3(0.42, 0.55, 0.72).normalize().multiplyScalar(dist)); };
  frameHome(); camera.position.copy(home.pos);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(home.target); controls.enableDamping = true; controls.dampingFactor = 0.08;
  controls.maxPolarAngle = Math.PI * 0.47; controls.minDistance = 18; controls.maxDistance = 190; controls.update();

  // lights
  scene.add(new THREE.HemisphereLight(0xdfe8ff, 0x3a3428, 0.75));
  const sun = new THREE.DirectionalLight(0xfff1dc, 2.1); sun.position.set(-50, 80, 40); sun.castShadow = true;
  const big = W() > 700; sun.shadow.mapSize.set(big ? 2048 : 1024, big ? 2048 : 1024);
  Object.assign(sun.shadow.camera, { left: -75, right: 75, top: 45, bottom: -45, near: 10, far: 220 }); sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.04;
  scene.add(sun); const fill = new THREE.DirectionalLight(0x9fb8ff, 0.35); fill.position.set(60, 30, -50); scene.add(fill);

  const M = (o) => new THREE.MeshStandardMaterial(Object.assign({ roughness: 0.7, metalness: 0.1 }, o));
  const mat = {
    ground: M({ map: gravelTex(), roughness: 1 }), concrete: M({ color: C.concrete, roughness: 0.95 }),
    wall: M({ map: ribTex(), roughness: 0.55, metalness: 0.15 }), roof: M({ color: 0xd9dbd6, roughness: 0.5, metalness: 0.2 }),
    grille: M({ map: grilleTex(), roughness: 0.6, metalness: 0.4 }), steel: M({ color: C.steel, roughness: 0.45, metalness: 0.75 }),
    dark: M({ color: C.dark, roughness: 0.55, metalness: 0.5 }), cabinet: M({ map: cabinetTex(), roughness: 0.5, metalness: 0.3 }),
    tank: M({ color: 0x6f7a72, roughness: 0.5, metalness: 0.55 }), porcelain: M({ color: 0x8a5a3c, roughness: 0.35, metalness: 0.05 }),
    copper: M({ color: 0xb87333, roughness: 0.35, metalness: 0.9 }), building: M({ color: 0xbfb9ab, roughness: 0.9 }),
    glass: M({ color: 0x223040, roughness: 0.15, metalness: 0.6 }), accent: M({ color: 0x2f7f86, roughness: 0.5, metalness: 0.2 }), fence: new THREE.LineBasicMaterial({ color: 0x77786f, transparent: true, opacity: 0.55 }),
  };
  const add = (geo, m, x, y, z, parent = scene, cast = true) => { const o = new THREE.Mesh(geo, m); o.position.set(x, y, z); o.castShadow = cast; o.receiveShadow = true; parent.add(o); return o; };

  // ground, pads, fence
  const gnd = add(new THREE.PlaneGeometry(260, 150), mat.ground, 0, 0, 0, scene, false); gnd.rotation.x = -Math.PI / 2;
  add(new THREE.BoxGeometry(60, 0.3, 16), mat.concrete, -3, 0.15, -11); add(new THREE.BoxGeometry(60, 0.3, 16), mat.concrete, -3, 0.15, 11);
  add(new THREE.BoxGeometry(70, 0.05, 4.5), M({ color: 0x4a4a44, roughness: 0.95 }), -12, 0.03, 0);
  add(new THREE.BoxGeometry(30, 0.3, 26), mat.concrete, -54, 0.15, 2);
  { const pts = [[-72, -22], [32, -22], [32, 22], [-72, 22], [-72, -22]];
    const g = new THREE.BufferGeometry(); const v = [];
    for (let i = 0; i < pts.length - 1; i++) { const [x1, z1] = pts[i], [x2, z2] = pts[i + 1]; const n = Math.ceil(Math.hypot(x2 - x1, z2 - z1) / 3);
      for (let k = 0; k < n; k++) { const x = x1 + (x2 - x1) * k / n, z = z1 + (z2 - z1) * k / n; v.push(x, 0, z, x, 2.2, z); }
      v.push(x1, 2.2, z1, x2, 2.2, z2, x1, 1.1, z1, x2, 1.1, z2); }
    g.setAttribute('position', new THREE.Float32BufferAttribute(v, 3)); scene.add(new THREE.LineSegments(g, mat.fence)); }

  // ---------------- battery containers + PCS skids
  const containers = [], skids = [], gauges = [], leds = [], fans = [];
  const contGeo = new RoundedBoxGeometry(2.44, 2.9, 6.06, 2, 0.06);
  const groupX = (i) => [-22, -3, 16, -3, 16][i], groupZ = (i) => [-11, -11, -11, 11, 11][i];
  for (let s = 0; s < 5; s++) {
    const gx = groupX(s), gz = groupZ(s);
    // skid (center): steel base, 2 inverter cabinet rows, MV transformer, RMU
    const sk = new THREE.Group(); sk.position.set(gx, 0.3, gz); scene.add(sk);
    add(new THREE.BoxGeometry(3.0, 0.35, 7.2), mat.dark, 0, 0.18, 0, sk);
    for (let r = 0; r < 2; r++) {
      const cab = add(new RoundedBoxGeometry(2.6, 2.3, 1.1, 2, 0.04), mat.cabinet, 0, 1.5, -2.6 + r * 1.35, sk);
      for (let k = 0; k < 4; k++) {   // one LED + one fan per inverter (8 per skid)
        const led = add(new THREE.BoxGeometry(0.42, 0.06, 0.02), new THREE.MeshStandardMaterial({ color: 0x223322, emissive: C.idle, emissiveIntensity: 0.4 }), -0.95 + k * 0.63, 2.35, -2.6 + r * 1.35 + 0.56, sk, false);
        leds.push(led);
        const fan = new THREE.Group(); fan.position.set(-0.95 + k * 0.63, 2.68, -2.6 + r * 1.35); sk.add(fan);
        add(new THREE.CylinderGeometry(0.26, 0.26, 0.06, 20), mat.dark, 0, 0, 0, fan);
        for (let b = 0; b < 4; b++) { const bl = add(new THREE.BoxGeometry(0.4, 0.02, 0.07), mat.steel, 0, 0.05, 0, fan, false); bl.rotation.y = b * Math.PI / 4; }
        fans.push(fan);
      }
    }
    // MV transformer with fins + bushings
    add(new RoundedBoxGeometry(1.9, 1.9, 1.6, 2, 0.05), mat.tank, 0, 1.3, 0.9, sk);
    for (let f = 0; f < 9; f++) add(new THREE.BoxGeometry(0.04, 1.5, 0.5), mat.tank, -0.85 + f * 0.21, 1.2, 1.95, sk);
    for (let b = 0; b < 3; b++) add(new THREE.CylinderGeometry(0.07, 0.09, 0.45, 10), mat.porcelain, -0.5 + b * 0.5, 2.45, 0.9, sk);
    add(new RoundedBoxGeometry(2.2, 2.0, 1.0, 2, 0.04), mat.cabinet, 0, 1.35, 2.9, sk);   // RMU
    skids.push(sk);
    // 4 containers: two on each side
    [-6.4, -3.4, 3.4, 6.4].forEach((dx, j) => {
      const g = new THREE.Group(); g.position.set(gx + dx, 0.3, gz); scene.add(g);
      add(contGeo, mat.wall, 0, 1.45, 0, g);
      add(new THREE.BoxGeometry(2.5, 0.08, 6.1), mat.roof, 0, 2.94, 0, g);
      add(new THREE.BoxGeometry(2.47, 0.16, 6.08), mat.accent, 0, 2.62, 0, g, false);
      // HVAC unit on the end wall + side door
      add(new THREE.BoxGeometry(1.9, 1.4, 0.35), mat.grille, 0, 1.6, 3.18, g);
      add(new THREE.BoxGeometry(0.02, 2.2, 1.0), mat.dark, (dx < 0 ? -1 : 1) * 1.23, 1.3, -1.8, g);
      // state-of-charge gauge on the outward long side
      const side = dx < 0 ? -1 : 1;
      add(new THREE.BoxGeometry(0.03, 2.2, 0.5), new THREE.MeshStandardMaterial({ color: 0x101214, roughness: 0.4 }), side * 1.235, 1.45, 1.2, g, false);
      const fillMat = new THREE.MeshStandardMaterial({ color: C.idle, emissive: C.idle, emissiveIntensity: 0.9, roughness: 0.4 });
      const fillM = add(new THREE.BoxGeometry(0.04, 2.0, 0.38), fillMat, side * 1.25, 0.45, 1.2, g, false);
      fillM.geometry.translate(0, 1.0, 0);   // scale from the bottom
      gauges.push(fillM);
      const led = add(new THREE.SphereGeometry(0.09, 12, 8), new THREE.MeshStandardMaterial({ color: 0x113311, emissive: C.idle, emissiveIntensity: 1.2 }), 0.9, 3.02, 2.7, g, false);
      leds.push(led); containers.push(g);
    });
  }

  // ---------------- substation: control building, MV switchgear, aux TX, main TX, HV bay, gantry, tower
  const sub = new THREE.Group(); scene.add(sub);
  add(new THREE.BoxGeometry(12, 3.6, 5.5), mat.building, -48, 2.1, 9.5, sub);
  add(new THREE.BoxGeometry(12.6, 0.3, 6.1), mat.dark, -48, 4.05, 9.5, sub);
  for (let w = 0; w < 4; w++) add(new THREE.BoxGeometry(1.4, 0.9, 0.05), mat.glass, -52.5 + w * 3, 2.6, 6.73, sub, false);
  // aux transformer
  add(new RoundedBoxGeometry(1.6, 1.7, 1.3, 2, 0.04), mat.tank, -39, 1.15, 10.5, sub);
  // main transformer
  const mt = new THREE.Group(); mt.position.set(-54, 0.3, -3); sub.add(mt);
  add(new THREE.BoxGeometry(6.5, 0.5, 4.2), mat.concrete, 0, 0.25, 0, mt);
  add(new RoundedBoxGeometry(4.6, 3.6, 2.8, 3, 0.12), mat.tank, 0, 2.3, 0, mt);
  for (const side of [-1, 1]) for (let f = 0; f < 12; f++) add(new THREE.BoxGeometry(0.05, 2.8, 0.9), mat.tank, -2.0 + f * 0.36, 2.2, side * 1.95, mt);
  const cons = add(new THREE.CylinderGeometry(0.42, 0.42, 3.2, 20), mat.tank, 0.4, 4.7, -0.6, mt); cons.rotation.z = Math.PI / 2;
  for (let b = 0; b < 3; b++) { add(new THREE.CylinderGeometry(0.12, 0.2, 2.2, 14), mat.porcelain, -1.4 + b * 1.4, 5.2, 0.6, mt);
    for (let r = 0; r < 7; r++) add(new THREE.CylinderGeometry(0.28, 0.28, 0.06, 14), mat.porcelain, -1.4 + b * 1.4, 4.4 + r * 0.26, 0.6, mt, false);
    add(new THREE.CylinderGeometry(0.08, 0.1, 0.9, 12), mat.porcelain, -1.2 + b * 1.2, 4.55, -1.0, mt); }
  // HV bay: breaker + disconnector + instrument transformers on steel stands, gantry
  const bay = new THREE.Group(); bay.position.set(-63, 0.3, -3); sub.add(bay);
  const stand = (x, z, h) => { add(new THREE.BoxGeometry(0.25, h, 0.25), mat.steel, x, h / 2, z, bay); };
  for (let p = 0; p < 3; p++) { const z = -1.4 + p * 1.4;
    stand(2.2, z, 2.6); add(new THREE.CylinderGeometry(0.22, 0.26, 1.6, 14), mat.porcelain, 2.2, 3.4, z, bay);   // CT
    stand(-0.5, z, 2.6); add(new THREE.CylinderGeometry(0.28, 0.28, 1.4, 16), mat.dark, -0.5, 3.3, z, bay);  // breaker pole
    add(new THREE.CylinderGeometry(0.1, 0.14, 1.2, 12), mat.porcelain, -0.5, 4.5, z, bay);
    stand(-3.2, z, 2.6); add(new THREE.CylinderGeometry(0.12, 0.16, 1.4, 12), mat.porcelain, -3.2, 3.3, z, bay); }
  for (const z of [-2.6, 2.6]) { add(new THREE.BoxGeometry(0.35, 8, 0.35), mat.steel, -5.5, 4, z, bay); }
  add(new THREE.BoxGeometry(0.35, 0.35, 5.6), mat.steel, -5.5, 8, 0, bay);
  // lattice tower outside the fence (grid)
  const tw = new THREE.Group(); tw.position.set(-92, 0, -3); scene.add(tw);
  { const legs = [[-1.6, -1.6], [1.6, -1.6], [1.6, 1.6], [-1.6, 1.6]], top = 0.5, h = 22;
    const g = new THREE.BufferGeometry(); const v = [];
    legs.forEach(([x, z]) => v.push(x, 0, z, x * top / 1.6 * 0.6, h, z * top / 1.6 * 0.6));
    for (let y = 0; y < h; y += 2.5) { const s1 = 1.6 - (1.6 - 0.3) * y / h, s2 = 1.6 - (1.6 - 0.3) * (y + 2.5) / h;
      for (let k = 0; k < 4; k++) { const a = legs[k], b = legs[(k + 1) % 4]; v.push(a[0] / 1.6 * s1, y, a[1] / 1.6 * s1, b[0] / 1.6 * s2, y + 2.5, b[1] / 1.6 * s2, b[0] / 1.6 * s1, y, b[1] / 1.6 * s1, a[0] / 1.6 * s2, y + 2.5, a[1] / 1.6 * s2); } }
    v.push(-5, 18, 0, 5, 18, 0, -4, 15, 0, 4, 15, 0);
    g.setAttribute('position', new THREE.Float32BufferAttribute(v, 3)); tw.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0x9aa0a6 }))); }
  { // conductors tower -> gantry (catenary)
    const g = new THREE.BufferGeometry(); const v = [];
    for (const z of [-1.6, 0, 1.6]) { const a = new THREE.Vector3(-92 + (z ? Math.sign(z) * 0 : 0), 18, -3 + z * 1.8), b = new THREE.Vector3(-68.5, 8.2, -3 + z);
      for (let i = 0; i < 24; i++) { const t0 = i / 24, t1 = (i + 1) / 24; const p0 = a.clone().lerp(b, t0), p1 = a.clone().lerp(b, t1);
        p0.y -= Math.sin(Math.PI * t0) * 2.2; p1.y -= Math.sin(Math.PI * t1) * 2.2; v.push(p0.x, p0.y, p0.z, p1.x, p1.y, p1.z); } }
    g.setAttribute('position', new THREE.Float32BufferAttribute(v, 3)); scene.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0xc9a46b }))); }

  // ---------------- energy flow paths (cable trenches) with moving particles
  const paths = [];
  const mvBusX = -45;
  for (let s = 0; s < 5; s++) {   // skid -> central trench -> MV switchgear (in the control building)
    const gx = groupX(s), gz = groupZ(s), side = gz < 0 ? -1 : 1;
    paths.push({ pts: [[gx, 0.45, gz - side * 3.9], [gx, 0.45, 0], [-44, 0.45, 0], [-44, 0.45, 6.7]], skid: s });
    for (const dx of [-6.4, -3.4, 3.4, 6.4]) paths.push({ pts: [[gx + dx, 0.45, gz + side * 3.3], [gx + dx, 0.45, gz + side * 4.4], [gx, 0.45, gz + side * 4.4], [gx, 0.45, gz + side * 3.7]], skid: s, dc: true });
  }
  paths.push({ pts: [[-50, 0.45, 6.7], [-50, 0.45, 2.0], [-54, 0.45, 0.8]], main: true });          // switchgear -> main TX
  paths.push({ pts: [[-54, 4.8, -3.0], [-58, 4.6, -3.0], [-63.5, 4.6, -3.0], [-68.5, 8.2, -3.0]], main: true, hv: true });  // TX -> bay -> gantry
  paths.push({ pts: [[-68.5, 8.2, -3.0], [-80, 9.5, -3.0], [-92, 18, -3.0]], main: true, hv: true });       // gantry -> grid
  const curves = paths.map(p => { const c = new THREE.CurvePath(); for (let i = 0; i < p.pts.length - 1; i++) c.add(new THREE.LineCurve3(new THREE.Vector3(...p.pts[i]), new THREE.Vector3(...p.pts[i + 1]))); return c; });
  // trench lines
  { const g = new THREE.BufferGeometry(); const v = [];
    paths.forEach(p => { if (p.hv) return; for (let i = 0; i < p.pts.length - 1; i++) v.push(p.pts[i][0], 0.32, p.pts[i][2], p.pts[i + 1][0], 0.32, p.pts[i + 1][2]); });
    g.setAttribute('position', new THREE.Float32BufferAttribute(v, 3)); scene.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0x55574f }))); }
  const cnt = curves.map(c => Math.max(1, Math.round(c.getLength() / 5))), total = cnt.reduce((a, b) => a + b, 0);
  const dotMat = new THREE.MeshBasicMaterial({ color: C.out, transparent: true, opacity: 0.95 });
  const dots = new THREE.InstancedMesh(new THREE.SphereGeometry(0.2, 10, 8), dotMat, total); dots.frustumCulled = false; scene.add(dots);
  const glowMat = new THREE.MeshBasicMaterial({ color: C.out, transparent: true, opacity: 0.18, blending: THREE.AdditiveBlending, depthWrite: false });
  const glow = new THREE.InstancedMesh(new THREE.SphereGeometry(0.42, 10, 8), glowMat, total); glow.frustumCulled = false; scene.add(glow);

  // ---------------- labels (HTML overlay, Hebrew-safe)
  const layer = document.createElement('div'); layer.className = 'p3l'; host.appendChild(layer);
  const label = (pos, cls) => { const d = document.createElement('div'); d.className = 'p3t ' + (cls || ''); layer.appendChild(d); return { d, pos: new THREE.Vector3(...pos) }; };
  const L = { grid: label([-92, 23, -3], 'g'), tx: label([-54, 7.8, -3]), bld: label([-48, 6.2, 9.5], 'g'),
    sk: [0, 1, 2, 3, 4].map(s => label([groupX(s), 4.4, groupZ(s)], 'sk')) };
  const hud = document.createElement('div'); hud.className = 'p3hud'; host.appendChild(hud);
  const bdi = s => `<bdi dir="ltr">${s}</bdi>`;
  L.grid.d.innerHTML = 'רשת מתח עליון'; L.bld.d.innerHTML = 'מבנה בקרה';

  // ---------------- state, update(), loop
  const st = { v: 0, soc: 0.5, phase: 0 };
  function update(v, soc) {
    st.v = v; st.soc = Math.max(0, Math.min(1, soc));
    const a = Math.abs(v), dir = v > 0.3 ? 'out' : v < -0.3 ? 'in' : 'idle', col = C[dir];
    gauges.forEach(g => { g.scale.y = Math.max(0.02, st.soc); g.material.color.setHex(col); g.material.emissive.setHex(col); });
    leds.forEach(l => l.material.emissive.setHex(col));
    dotMat.color.setHex(col); glowMat.color.setHex(col);
    const per = v / 5; const sg = per > 0 ? '+' : per < 0 ? '−' : '';
    L.sk.forEach((l, i) => l.d.innerHTML = `ממירים ${i + 1} · ${bdi(sg + Math.abs(per).toFixed(1) + ' MW')}`);
    L.tx.d.innerHTML = `שנאי ראשי · ${bdi(Math.round(a / 50 * 100) + '%')}`;
    const hx = '#' + col.toString(16).padStart(6, '0');
    hud.innerHTML = `<div class="k">נקודת החיבור</div><div class="v">${bdi((v > 0 ? '+' : v < 0 ? '−' : '') + a.toFixed(1) + ' MW')}</div>
      <div class="s"><i style="background:${hx}"></i>${dir === 'out' ? 'פריקה לרשת' : dir === 'in' ? 'טעינה מהרשת' : 'ממתינה'}</div>
      <div class="k" style="margin-top:6px">20 מכולות · מצב טעינה</div><div class="bar"><b style="width:${(st.soc * 100).toFixed(0)}%;background:${hx}"></b></div><div class="s">${bdi(Math.round(st.soc * 100) + '%')}</div>`;
  }
  const tmp = new THREE.Object3D(), v3 = new THREE.Vector3();
  let visible = true, last = performance.now();
  const io = new IntersectionObserver(es => { visible = es[0].isIntersecting; }, { threshold: 0.01 }); io.observe(host);
  function frame(now) {
    requestAnimationFrame(frame);
    if (!visible || document.hidden) { last = now; return; }
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const a = Math.abs(st.v), active = a > 0.3, dir = st.v > 0 ? 1 : -1;
    st.phase += dt * (0.12 + 0.5 * a / 50) * (active ? 1 : 0);
    fans.forEach((f, i) => f.rotation.y += dt * (active ? 6 + 18 * a / 50 : 0.4) * (i % 2 ? 1 : -1));
    let k = 0;
    curves.forEach((c, ci) => { const PER = cnt[ci]; for (let j = 0; j < PER; j++, k++) {
      if (!active) { tmp.position.set(0, -50, 0); tmp.updateMatrix(); dots.setMatrixAt(k, tmp.matrix); glow.setMatrixAt(k, tmp.matrix); continue; }
      // every path is drawn from the batteries towards the grid: discharge runs forward, charge runs backward
      let t = (j / PER + st.phase * (paths[ci].hv ? 1.4 : 1)) % 1; if (dir < 0) t = 1 - t;
      c.getPointAt(t, v3); tmp.position.copy(v3); tmp.scale.setScalar(paths[ci].hv ? 1.2 : 1); tmp.updateMatrix();
      dots.setMatrixAt(k, tmp.matrix); glow.setMatrixAt(k, tmp.matrix); } });
    dots.instanceMatrix.needsUpdate = true; glow.instanceMatrix.needsUpdate = true;
    controls.update(); renderer.render(scene, camera);
    // project labels
    const w = W(), h = H();
    const place = (l) => { v3.copy(l.pos).project(camera); const on = v3.z < 1 && Math.abs(v3.x) < 1.05 && Math.abs(v3.y) < 1.05;
      l.d.style.display = on ? '' : 'none'; if (on) l.d.style.transform = `translate(${(v3.x * .5 + .5) * w}px,${(-v3.y * .5 + .5) * h}px) translate(-50%,-100%)`; };
    [L.grid, L.tx, L.bld, ...L.sk].forEach(place);
  }
  requestAnimationFrame(frame);
  new ResizeObserver(() => { camera.aspect = W() / H(); camera.updateProjectionMatrix(); renderer.setSize(W(), H()); }).observe(host);
  function reset() { frameHome(); camera.position.copy(home.pos); controls.target.copy(home.target); controls.update(); }
  update(0, 0.5);
  return { update, reset };
}
