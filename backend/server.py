#!/usr/bin/env python3
"""
Single-file backend for Polar (BLE/bleak) + HC-06 (serial) data collection.
- Collects ECG from Polar PMD (based on original user script).
- Collects GSR from HC-06 serial line parser.
- Writes both streams into one CSV file: timestamp,gsr,ecg.
- Broadcasts live values/status over WebSocket to web clients.
"""

import argparse
import asyncio
import contextlib
import csv
import json
import logging
import time
from pathlib import Path
from typing import Optional

from bleak import BleakClient, BleakScanner
from websockets.server import serve

try:
    import serial  # pyserial
except Exception:  # pragma: no cover
    serial = None

MODEL_NBR_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
MANUFACTURER_NAME_UUID = "00002a29-0000-1000-8000-00805f9b34fb"

ECG_WRITE = bytearray([0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00])
PMD_SERVICE = "FB005C80-02E7-F387-1CAD-8ACD2D8DF0C8"
PMD_CONTROL = "FB005C81-02E7-F387-1CAD-8ACD2D8DF0C8"
PMD_DATA = "FB005C82-02E7-F387-1CAD-8ACD2D8DF0C8"

POLAR_ID_HINTS = ("A92CA320", "A92C1224", "9DF0C423")


class Backend:
    def __init__(self, hc06_port: str, hc06_baud: int, out_csv: Path):
        self.hc06_port = hc06_port
        self.hc06_baud = hc06_baud
        self.out_csv = out_csv

        self.clients = set()
        self.csv_lock = asyncio.Lock()

        self.polar_connected = False
        self.hc06_connected = False

        self._stop = asyncio.Event()

    async def write_row(self, *, gsr: Optional[int] = None, ecg: Optional[int] = None):
        async with self.csv_lock:
            with self.out_csv.open("a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([int(time.time() * 1000), "" if gsr is None else gsr, "" if ecg is None else ecg])

    async def broadcast(self, payload: dict):
        if not self.clients:
            return
        data = json.dumps(payload, ensure_ascii=False)
        stale = []
        for ws in self.clients:
            try:
                await ws.send(data)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.clients.discard(ws)

    async def emit_status(self):
        await self.broadcast({
            "type": "status",
            "hc06": self.hc06_connected,
            "polar": self.polar_connected,
        })

    async def emit_gsr(self, value: int):
        await self.write_row(gsr=value)
        await self.broadcast({"type": "data", "gsr": value})

    async def emit_ecg(self, value: int):
        await self.write_row(ecg=value)
        await self.broadcast({"type": "data", "ecg": value})

    async def ws_handler(self, websocket):
        self.clients.add(websocket)
        await self.emit_status()
        try:
            await websocket.wait_closed()
        finally:
            self.clients.discard(websocket)

    def parse_hc06_line(self, line: str) -> Optional[int]:
        # supported: "GSR:512" or "512"
        line = line.strip()
        if not line:
            return None
        if "GSR:" in line.upper():
            try:
                return int(line.split(":", 1)[1].strip())
            except Exception:
                return None
        try:
            return int(line)
        except Exception:
            return None

    async def run_hc06(self):
        if serial is None:
            logging.warning("pyserial is not installed; HC-06 reader disabled")
            return

        while not self._stop.is_set():
            ser = None
            try:
                ser = serial.Serial(self.hc06_port, self.hc06_baud, timeout=1)
                self.hc06_connected = True
                await self.emit_status()
                logging.info("HC-06 connected on %s @ %s", self.hc06_port, self.hc06_baud)

                buf = ""
                while not self._stop.is_set():
                    chunk = await asyncio.to_thread(ser.read, 256)
                    if not chunk:
                        continue
                    buf += chunk.decode(errors="ignore")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        gsr = self.parse_hc06_line(line)
                        if gsr is not None:
                            await self.emit_gsr(gsr)
            except Exception as e:
                logging.warning("HC-06 error: %s", e)
                await asyncio.sleep(2)
            finally:
                self.hc06_connected = False
                await self.emit_status()
                if ser is not None:
                    with contextlib.suppress(Exception):
                        ser.close()

    @staticmethod
    def pick_polar_device(devices):
        for d in devices:
            name = (d.name or "")
            addr = (d.address or "").replace(":", "").upper()
            if "POLAR" in name.upper() and any(h in addr for h in POLAR_ID_HINTS):
                return d
        for d in devices:
            if "POLAR" in ((d.name or "").upper()):
                return d
        return None

    @staticmethod
    def parse_ecg_samples(data: bytearray):
        if not data or data[0] != 0x00 or len(data) <= 10:
            return []
        out = []
        for i in range(10, len(data), 3):
            if i + 2 >= len(data):
                break
            raw = int.from_bytes(data[i:i+3], byteorder="little", signed=True)
            out.append(raw)
        return out

    async def run_polar(self):
        while not self._stop.is_set():
            try:
                device = None
                while device is None and not self._stop.is_set():
                    devices = await BleakScanner.discover(timeout=5.0)
                    device = self.pick_polar_device(devices)
                    if device is None:
                        logging.info("Polar not found yet; retrying scan")
                        await asyncio.sleep(1)

                if device is None:
                    continue

                logging.info("Polar chosen: %s %s", device.name, device.address)
                async with BleakClient(device) as client:
                    while not client.is_connected and not self._stop.is_set():
                        await asyncio.sleep(0.2)

                    self.polar_connected = True
                    await self.emit_status()

                    with contextlib.suppress(Exception):
                        model = await client.read_gatt_char(MODEL_NBR_UUID)
                        man = await client.read_gatt_char(MANUFACTURER_NAME_UUID)
                        logging.info("Polar model=%s manufacturer=%s", model.decode(errors='ignore'), man.decode(errors='ignore'))

                    async def on_data(_: int, payload: bytearray):
                        for ecg in self.parse_ecg_samples(payload):
                            await self.emit_ecg(ecg)

                    await client.write_gatt_char(PMD_CONTROL, ECG_WRITE, response=True)
                    await client.start_notify(PMD_DATA, on_data)
                    logging.info("Polar ECG stream started")

                    while client.is_connected and not self._stop.is_set():
                        await asyncio.sleep(1)

                    with contextlib.suppress(Exception):
                        await client.stop_notify(PMD_DATA)
            except Exception as e:
                logging.warning("Polar error: %s", e)
                await asyncio.sleep(2)
            finally:
                self.polar_connected = False
                await self.emit_status()

    async def run(self, ws_host: str, ws_port: int):
        self.out_csv.parent.mkdir(parents=True, exist_ok=True)
        if not self.out_csv.exists():
            with self.out_csv.open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["timestamp", "gsr", "ecg"])

        async with serve(self.ws_handler, ws_host, ws_port):
            logging.info("WebSocket server started at ws://%s:%s", ws_host, ws_port)
            await asyncio.gather(self.run_hc06(), self.run_polar())


def parse_args():
    p = argparse.ArgumentParser(description="GSR+Polar backend in one file")
    p.add_argument("--hc06-port", default="/dev/rfcomm0", help="HC-06 serial port")
    p.add_argument("--hc06-baud", default=9600, type=int)
    p.add_argument("--ws-host", default="0.0.0.0")
    p.add_argument("--ws-port", default=8765, type=int)
    p.add_argument("--out", default="data/gsr_polar.csv", help="Output CSV path")
    return p.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(asctime)s %(message)s")
    backend = Backend(hc06_port=args.hc06_port, hc06_baud=args.hc06_baud, out_csv=Path(args.out))
    try:
        asyncio.run(backend.run(args.ws_host, args.ws_port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
