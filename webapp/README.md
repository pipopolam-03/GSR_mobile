# Web app: GSR + Polar

Базовое веб-приложение с UI для:
- Polar ECG через **Web Bluetooth** (PMD service/control/data).
- GSR (HC-06) через **WebSocket bridge** (браузер не умеет прямой Bluetooth Classic SPP).
- Совместной записи в один CSV (`timestamp,gsr,ecg`).

## Быстрый старт
```bash
python3 -m http.server 8080 --directory webapp
```
Откройте `http://localhost:8080` в Chromium/Chrome.

## Ограничения
- Для Polar нужен браузер с Web Bluetooth.
- Для HC-06 нужен внешний bridge, который публикует GSR по WebSocket.

## Формат входящих данных HC-06 bridge
Поддерживаются:
- JSON: `{"gsr": 512}`
- Текст: `GSR:512`
