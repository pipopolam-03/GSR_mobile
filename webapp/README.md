# Web app + backend

Новая архитектура:
- `backend/server.py` — **один файл** с подключением к Polar (bleak) и HC-06 (serial),
  записью в общий CSV (`timestamp,gsr,ecg`) и трансляцией live-данных по WebSocket.
- `webapp/` — простой UI-клиент, который получает статусы/данные от backend.

## Запуск backend
```bash
python3 backend/server.py --hc06-port /dev/rfcomm0 --hc06-baud 9600 --ws-port 8765 --out data/gsr_polar.csv
```

## Запуск web UI
```bash
python3 -m http.server 8080 --directory webapp
```
Открыть `http://localhost:8080`.

## Зависимости backend
- `bleak`
- `websockets`
- `pyserial`
