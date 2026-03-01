const PMD_SERVICE = 'fb005c80-02e7-f387-1cad-8acd2d8df0c8';
const PMD_CONTROL = 'fb005c81-02e7-f387-1cad-8acd2d8df0c8';
const PMD_DATA = 'fb005c82-02e7-f387-1cad-8acd2d8df0c8';
const ECG_START = new Uint8Array([0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0e, 0x00]);

const ui = {
  connectPolarBtn: document.getElementById('connectPolarBtn'),
  connectHc06Btn: document.getElementById('connectHc06Btn'),
  hc06WsUrl: document.getElementById('hc06WsUrl'),
  polarStatus: document.getElementById('polarStatus'),
  hc06Status: document.getElementById('hc06Status'),
  gsrValue: document.getElementById('gsrValue'),
  ecgValue: document.getElementById('ecgValue'),
  startRecBtn: document.getElementById('startRecBtn'),
  stopRecBtn: document.getElementById('stopRecBtn'),
  downloadBtn: document.getElementById('downloadBtn'),
  log: document.getElementById('log'),
};

let recording = false;
const rows = [['timestamp', 'gsr', 'ecg']];

function log(msg) {
  const line = `[${new Date().toLocaleTimeString()}] ${msg}`;
  ui.log.textContent = `${line}\n${ui.log.textContent}`;
}

function writeRow({ gsr = '', ecg = '' }) {
  if (!recording) return;
  rows.push([Date.now(), gsr, ecg]);
  ui.downloadBtn.disabled = rows.length <= 1;
}

function updateValues({ gsr, ecg }) {
  if (gsr !== undefined) {
    ui.gsrValue.textContent = String(gsr);
    writeRow({ gsr });
  }
  if (ecg !== undefined) {
    ui.ecgValue.textContent = String(ecg);
    writeRow({ ecg });
  }
}

function parseEcgPacket(value) {
  const bytes = new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  if (bytes.length <= 10 || bytes[0] !== 0x00) return;

  for (let i = 10; i + 2 < bytes.length; i += 3) {
    let raw = bytes[i] | (bytes[i + 1] << 8) | (bytes[i + 2] << 16);
    if (raw & 0x800000) raw |= ~0xffffff;
    updateValues({ ecg: raw });
  }
}

async function connectPolar() {
  try {
    const device = await navigator.bluetooth.requestDevice({
      filters: [{ namePrefix: 'Polar' }],
      optionalServices: [PMD_SERVICE],
    });

    const gatt = await device.gatt.connect();
    const service = await gatt.getPrimaryService(PMD_SERVICE);
    const control = await service.getCharacteristic(PMD_CONTROL);
    const data = await service.getCharacteristic(PMD_DATA);

    await control.startNotifications();
    control.addEventListener('characteristicvaluechanged', (event) => {
      const bytes = new Uint8Array(event.target.value.buffer);
      log(`Polar control: ${Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join(' ')}`);
    });

    await data.startNotifications();
    data.addEventListener('characteristicvaluechanged', (event) => parseEcgPacket(event.target.value));

    await control.writeValueWithResponse(ECG_START);

    ui.polarStatus.textContent = `Polar: подключен (${device.name || 'unknown'})`;
    log('Polar connected, ECG stream requested');
  } catch (e) {
    log(`Polar error: ${e?.message || e}`);
  }
}

function parseHc06Message(raw) {
  try {
    const parsed = JSON.parse(raw);
    if (typeof parsed.gsr === 'number') {
      updateValues({ gsr: parsed.gsr });
      return;
    }
  } catch (_) {
    // ignore, maybe plain text line
  }

  const match = raw.match(/GSR\s*:?\s*(\d+)/i);
  if (match) updateValues({ gsr: Number(match[1]) });
}

function connectHc06Bridge() {
  try {
    const ws = new WebSocket(ui.hc06WsUrl.value.trim());
    ws.onopen = () => {
      ui.hc06Status.textContent = 'HC-06: подключен (bridge)';
      log('HC-06 bridge connected');
    };
    ws.onmessage = (event) => parseHc06Message(String(event.data));
    ws.onerror = () => log('HC-06 bridge error');
    ws.onclose = () => {
      ui.hc06Status.textContent = 'HC-06: не подключен';
      log('HC-06 bridge disconnected');
    };
  } catch (e) {
    log(`HC-06 bridge connect failed: ${e?.message || e}`);
  }
}

function startRecording() {
  recording = true;
  ui.startRecBtn.disabled = true;
  ui.stopRecBtn.disabled = false;
  log('Recording started');
}

function stopRecording() {
  recording = false;
  ui.startRecBtn.disabled = false;
  ui.stopRecBtn.disabled = true;
  log('Recording stopped');
}

function downloadCsv() {
  const csv = rows.map((r) => r.join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `GSR_${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

ui.connectPolarBtn.addEventListener('click', connectPolar);
ui.connectHc06Btn.addEventListener('click', connectHc06Bridge);
ui.startRecBtn.addEventListener('click', startRecording);
ui.stopRecBtn.addEventListener('click', stopRecording);
ui.downloadBtn.addEventListener('click', downloadCsv);

if (!('bluetooth' in navigator)) {
  log('Web Bluetooth не поддерживается в этом браузере');
}
