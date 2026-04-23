#!/usr/bin/env python3

import asyncio
import contextlib
import csv
import json
import logging
import time
from pathlib import Path
from typing import Optional

import pandas as pd
from bleak import BleakClient, BleakScanner
from websockets.server import serve

try:
    import serial
except Exception:
    serial = None

ECG_WRITE = bytearray([0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00])
PMD_CONTROL = "FB005C81-02E7-F387-1CAD-8ACD2D8DF0C8"
PMD_DATA = "FB005C82-02E7-F387-1CAD-8ACD2D8DF0C8"
SERVER_PORT = 8001


class Backend:

    def __init__(self):
        self.hc06_port = "COM9"
        self.hc06_baud = 9600

        self.clients = set()
        self.csv_lock = asyncio.Lock()

        self.recording = False
        self.interval = 0
        self.out_csv: Optional[Path] = None

        self.last_gsr = None
        self.last_ecg = None
        self.last_heart_rate = None

        self.polar_connected = False
        self.hc06_connected = False

    async def start_recording(self):
        ts = time.strftime("%Y-%m-%d_%H-%M-%S")
        self.out_csv = Path(f"data/record_{ts}.csv")
        self.out_csv.parent.mkdir(exist_ok=True)

        self.interval = 0

        with self.out_csv.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["timestamp", "gsr", "ecg", "interval"])

        self.recording = True

        await self.broadcast({"type": "recording", "value": True})
        await self.broadcast({"type": "interval", "value": self.interval})

        logging.info("Recording started")

    async def stop_recording(self):
        self.recording = False
        await self.broadcast({"type": "recording", "value": False})
        logging.info("Recording stopped")
        await self.send_intervals()

    async def next_interval(self):
        if not self.recording:
            return
        self.interval += 1
        await self.broadcast({"type": "interval", "value": self.interval})
        logging.info(f"Interval -> {self.interval}")

    async def write_row(self):
            if not self.recording or self.out_csv is None:
                return
            if self.last_gsr is None or self.last_ecg is None:
                return
            async with self.csv_lock:
                with self.out_csv.open("a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow([
                        int(time.time() * 1000),
                        self.last_gsr,
                        self.last_ecg,
                        self.interval,
                        self.last_heart_rate or 0,   # доп. колонка ЧСС
                    ])

    async def send_intervals(self):
        if self.out_csv is None:
            return
        df = pd.read_csv(self.out_csv)
        intervals = sorted(df["interval"].unique())
        intervals = [int(i) for i in intervals]
        await self.broadcast({"type": "label_intervals", "intervals": intervals})

    async def save_labels(self, labels):
        if self.out_csv is None:
            return
        df = pd.read_csv(self.out_csv)
        labels = {int(k): v for k, v in labels.items()}
        df["label"] = df["interval"].map(labels)
        df.to_csv(self.out_csv, index=False)
        logging.info("Labels saved")

    async def broadcast(self, payload):
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
            "polar": self.polar_connected
        })

    async def emit_gsr(self, value):
        self.last_gsr = value
        await self.write_row()
        await self.broadcast({"type": "data", "gsr": value})

    async def emit_ecg(self, value):
        self.last_ecg = value
        await self.write_row()
        await self.broadcast({"type": "data", "ecg": value})

    async def ws_handler(self, websocket):
        self.clients.add(websocket)
        await self.emit_status()
        try:
            async for message in websocket:
                data = json.loads(message)
                if data.get("type") == "start_record":
                    await self.start_recording()
                if data.get("type") == "stop_record":
                    await self.stop_recording()
                if data.get("type") == "next_interval":
                    await self.next_interval()
                if data.get("type") == "save_labels":
                    await self.save_labels(data["labels"])
        finally:
            self.clients.discard(websocket)

    def parse_hc06_line(self, line):
        line = line.strip()
        if not line.startswith("GSR:"):
            return None
        try:
            return int(line.split(":")[1])
        except:
            return None

    async def run_hc06(self):
        if serial is None:
            return

        while True:
            ser = None
            try:
                ser = serial.Serial(self.hc06_port, self.hc06_baud, timeout=1)
                logging.info(f"HC-06 port {self.hc06_port} opened")

                got_data = False
                buffer = ""

                while True:
                    chunk = await asyncio.to_thread(ser.read, 100)
                    # print("RAW BYTES:", chunk)

                    if not chunk:
                        continue

                    buffer += chunk.decode(errors="ignore")

                    lines = buffer.split("\n")
                    buffer = lines[-1]  # остаток неполной строки

                    for line in lines[:-1]:
                        gsr = self.parse_hc06_line(line)

                        if gsr is not None:
                            if not got_data:
                                got_data = True
                                self.hc06_connected = True
                                await self.emit_status()
                                logging.info("HC-06 data stream detected")

                            await self.emit_gsr(gsr)

            except Exception as e:
                logging.warning("HC-06 error: %s", e)
                await asyncio.sleep(2)
            finally:
                self.hc06_connected = False
                await self.emit_status()
                if ser:
                    with contextlib.suppress(Exception):
                        ser.close()

    async def emit_heart_rate(self, hr_bpm: int):
        # если захотите сохранять ЧСС в CSV — можно отдельное поле
        self.last_heart_rate = hr_bpm
        await self.write_row()
        await self.broadcast({"type": "data", "heart_rate": hr_bpm})

    async def run_polar(self):
        while True:
            try:
                device = None
                while device is None:
                    devices = await BleakScanner.discover(timeout=5)
                    for d in devices:
                        if "Polar" in (d.name or ""):
                            device = d
                            break

                async with BleakClient(device) as client:
                    self.polar_connected = True
                    await self.emit_status()

                    # Heart Rate UUID (стандартный BLE HR)
                    HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
                    HR_CHAR_UUID    = "00002a37-0000-1000-8000-00805f9b34fb"

                    async def on_hr(_, payload: bytearray):
                        if not payload:
                            return
                        flags = payload[0]
                        offset = 1

                        # 8‑бит или 16‑бит bpm
                        if not (flags & 0x1):
                            hr_bpm = payload[offset]
                            offset += 1
                        else:
                            hr_bpm = int.from_bytes(payload[offset:offset+2], "little")
                            offset += 2

                        await self.emit_heart_rate(hr_bpm)

                    # Подключаемся ТОЛЬКО к Heart Rate, без PMD/ECG
                    hr_service = client.services.get_service(HR_SERVICE_UUID)
                    hr_char    = hr_service.get_characteristic(HR_CHAR_UUID)

                    await client.start_notify(hr_char, on_hr)

                    while client.is_connected:
                        await asyncio.sleep(1)

            except Exception as e:
                logging.warning("Polar error: %s", e)
                await asyncio.sleep(2)
            finally:
                self.polar_connected = False
                await self.emit_status()

    async def run(self):
        async with serve(self.ws_handler, "0.0.0.0", SERVER_PORT):
            logging.info(f"Server started ws://localhost:{SERVER_PORT}")
            await asyncio.gather(
                self.run_hc06(),
                self.run_polar()
            )


def main():
    logging.basicConfig(level=logging.INFO)
    backend = Backend()
    asyncio.run(backend.run())


if __name__ == "__main__":
    main()