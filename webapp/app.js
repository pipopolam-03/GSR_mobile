const ui = {
  connectBackendBtn: document.getElementById('connectBackendBtn'),
  backendWsUrl: document.getElementById('backendWsUrl'),

  polarStatus: document.getElementById('polarStatus'),
  hc06Status: document.getElementById('hc06Status'),

  gsrValue: document.getElementById('gsrValue'),
  bpmValue: document.getElementById('bpmValue'),

  log: document.getElementById('log'),

  startRecordBtn: document.getElementById('startRecordBtn'),
  stopRecordBtn: document.getElementById('stopRecordBtn'),

  recordIndicator: document.getElementById('recordIndicator'),

  nextIntervalBtn: document.getElementById('nextIntervalBtn'),
  intervalValue: document.getElementById('intervalValue'),

  labelModal: document.getElementById('labelModal'),
  intervalForms: document.getElementById('intervalForms'),
  saveLabelsBtn: document.getElementById('saveLabelsBtn')
};

let ws = null;

function log(msg) {

  const line = `[${new Date().toLocaleTimeString()}] ${msg}`;

  ui.log.textContent = `${line}\n${ui.log.textContent}`;
}

function showLabelModal(intervals) {

  ui.intervalForms.innerHTML = '';

  for (const i of intervals) {

    const row = document.createElement('div');

    row.innerHTML =
      `Interval ${i}: 
       <input type="text" data-interval="${i}" placeholder="activity">`;

    ui.intervalForms.appendChild(row);
  }

  ui.labelModal.style.display = 'block';
}

function handlePayload(payload) {

  if (payload.type === 'status') {

    ui.hc06Status.textContent =
      `HC-06: ${payload.hc06 ? 'подключен' : 'не подключен'}`;

    ui.polarStatus.textContent =
      `Polar: ${payload.polar ? 'подключен' : 'не подключен'}`;

    return;
  }

  if (payload.type === 'recording') {

    ui.recordIndicator.textContent =
      payload.value ? '● Recording' : 'Recording stopped';

    return;
  }

  if (payload.type === 'interval') {

    ui.intervalValue.textContent = payload.value;

    return;
  }

  if (payload.type === 'label_intervals') {

    showLabelModal(payload.intervals);

    return;
  }

  if (payload.type === 'data') {

    if (typeof payload.gsr === 'number')
      ui.gsrValue.textContent = payload.gsr;

    if (typeof payload.heart_rate === 'number')
      ui.bpmValue.textContent = payload.heart_rate;
  }
}

function connectBackend() {

  ws?.close();

  ws = new WebSocket(ui.backendWsUrl.value);

  ws.onopen = () => log('Connected');

  ws.onmessage = (event) => {

    const payload = JSON.parse(event.data);

    handlePayload(payload);
  };

  ws.onclose = () => log('Disconnected');
}

ui.connectBackendBtn.addEventListener('click', connectBackend);

ui.startRecordBtn.addEventListener('click', () => {

  if (!ws) return;

  ws.send(JSON.stringify({ type: 'start_record' }));
});

ui.stopRecordBtn.addEventListener('click', () => {

  if (!ws) return;

  ws.send(JSON.stringify({ type: 'stop_record' }));
});

ui.nextIntervalBtn.addEventListener('click', () => {

  if (!ws) return;

  ws.send(JSON.stringify({ type: 'next_interval' }));
});

ui.saveLabelsBtn.addEventListener('click', () => {

  const inputs = ui.intervalForms.querySelectorAll('input');

  const labels = {};

  inputs.forEach(input => {

    const interval = input.dataset.interval;

    labels[interval] = input.value;
  });

  ws.send(JSON.stringify({
    type: 'save_labels',
    labels: labels
  }));

  ui.labelModal.style.display = 'none';
});