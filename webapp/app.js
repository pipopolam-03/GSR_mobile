const ui = {
  connectBackendBtn: document.getElementById('connectBackendBtn'),
  backendWsUrl: document.getElementById('backendWsUrl'),
  polarStatus: document.getElementById('polarStatus'),
  hc06Status: document.getElementById('hc06Status'),
  gsrValue: document.getElementById('gsrValue'),
  ecgValue: document.getElementById('ecgValue'),
  log: document.getElementById('log'),
};

let ws = null;

function log(msg) {
  const line = `[${new Date().toLocaleTimeString()}] ${msg}`;
  ui.log.textContent = `${line}\n${ui.log.textContent}`;
}

function handlePayload(payload) {
  if (payload.type === 'status') {
    ui.hc06Status.textContent = `HC-06: ${payload.hc06 ? 'подключен' : 'не подключен'}`;
    ui.polarStatus.textContent = `Polar: ${payload.polar ? 'подключен' : 'не подключен'}`;
    return;
  }

  if (payload.type === 'data') {
    if (typeof payload.gsr === 'number') {
      ui.gsrValue.textContent = String(payload.gsr);
    }
    if (typeof payload.ecg === 'number') {
      ui.ecgValue.textContent = String(payload.ecg);
    }
  }
}

function connectBackend() {
  try {
    ws?.close();
    ws = new WebSocket(ui.backendWsUrl.value.trim());

    ws.onopen = () => {
      log('Connected to backend');
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(String(event.data));
        handlePayload(payload);
      } catch {
        log(`Invalid message: ${event.data}`);
      }
    };

    ws.onerror = () => log('Backend socket error');
    ws.onclose = () => log('Backend socket closed');
  } catch (e) {
    log(`Connect failed: ${e?.message || e}`);
  }
}

ui.connectBackendBtn.addEventListener('click', connectBackend);
