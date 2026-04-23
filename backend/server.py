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

SERVER_PORT = 8001

HR_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

PMD_CONTROL = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"
PMD_DATA = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"


class Backend:

    def __init__(self):
        self.hc06_port = "COM6"
        self.hc06_baud = 9600

        self.clients = set()
        self.csv_lock = asyncio.Lock()

        self.recording = False
        self.interval = 0
        self.out_csv: Optional[Path] = None

        self.last_gsr = None
        self.last_heart_rate = None
        self.last_ecg = None

        self.polar_connected = False
        self.hc06_connected = False

    async def start_recording(self):
        ts = time.strftime("%Y-%m-%d_%H-%M-%S")
        self.out_csv = Path(f"data/record_{ts}.csv")
        self.out_csv.parent.mkdir(exist_ok=True)

        self.interval = 0

        with self.out_csv.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                ["timestamp", "gsr", "bpm", "ecg", "interval"]
            )

        self.recording = True

        await self.broadcast({"type": "recording", "value": True})
        await self.broadcast({"type": "interval", "value": self.interval})

    async def stop_recording(self):
        self.recording = False
        await self.broadcast({"type": "recording", "value": False})
        await self.send_intervals()

    async def next_interval(self):
        if not self.recording:
            return

        self.interval += 1
        await self.broadcast({"type": "interval", "value": self.interval})

    async def write_row(self):
        if not self.recording or self.out_csv is None:
            return

        if self.last_gsr is None:
            return

        async with self.csv_lock:
            with self.out_csv.open("a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([
                    int(time.time() * 1000),
                    self.last_gsr,
                    self.last_heart_rate,
                    self.last_ecg,
                    self.interval
                ])

    async def send_intervals(self):
        if self.out_csv is None:
            return

        df = pd.read_csv(self.out_csv)
        intervals = sorted(df["interval"].unique())
        intervals = [int(i) for i in intervals]

        await self.broadcast({
            "type": "label_intervals",
            "intervals": intervals
        })

    async def save_labels(self, labels):
        if self.out_csv is None:
            return

        df = pd.read_csv(self.out_csv)

        labels = {int(k): v for k, v in labels.items()}
        df["label"] = df["interval"].map(labels)

        df.to_csv(self.out_csv, index=False)

    async def broadcast(self, payload):
        if not self.clients:
            return

        data = json.dumps(payload, ensure_ascii=False)

        stale = []

        for ws in list(self.clients):
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

        await self.broadcast({
            "type": "data",
            "gsr": value
        })

    async def emit_heart_rate(self, bpm):
        self.last_heart_rate = bpm
        await self.write_row()

        await self.broadcast({
            "type": "data",
            "heart_rate": bpm
        })

    async def emit_ecg(self, ecg):
        self.last_ecg = ecg
        await self.write_row()

        await self.broadcast({
            "type": "data",
            "ecg": ecg
        })

    async def ws_handler(self, websocket):
        self.clients.add(websocket)

        await self.emit_status()

        try:
            async for message in websocket:
                data = json.loads(message)

                if data.get("type") == "start_record":
                    await self.start_recording()

                elif data.get("type") == "stop_record":
                    await self.stop_recording()

                elif data.get("type") == "next_interval":
                    await self.next_interval()

                elif data.get("type") == "save_labels":
                    await self.save_labels(data["labels"])

        finally:
            self.clients.discard(websocket)

    def parse_hc06_line(self, line):
        line = line.strip()

        if not line.startswith("GSR:"):
            return None

        try:
            return int(line.split(":")[1])
        except Exception:
            return None

    async def run_hc06(self):
        if serial is None:
            return

        while True:
            ser = None

            try:
                ser = serial.Serial(
                    self.hc06_port,
                    self.hc06_baud,
                    timeout=1
                )

                got_data = False
                buffer = ""

                while True:
                    chunk = await asyncio.to_thread(ser.read, 100)

                    if not chunk:
                        continue

                    buffer += chunk.decode(errors="ignore")

                    lines = buffer.split("\n")
                    buffer = lines[-1]

                    for line in lines[:-1]:
                        gsr = self.parse_hc06_line(line)

                        if gsr is not None:

                            if not got_data:
                                got_data = True
                                self.hc06_connected = True
                                await self.emit_status()

                            await self.emit_gsr(gsr)

            except Exception as e:
                logging.warning("HC06 error: %s", e)
                await asyncio.sleep(2)

            finally:
                self.hc06_connected = False
                await self.emit_status()

                if ser:
                    with contextlib.suppress(Exception):
                        ser.close()

    async def run_polar(self):
        while True:
            try:
                devices = await BleakScanner.discover(timeout=6)

                device = None

                for d in devices:
                    if d.name and "Polar" in d.name:
                        device = d
                        break

                if device is None:
                    await asyncio.sleep(3)
                    continue

                async with BleakClient(device) as client:
                    self.polar_connected = True
                    await self.emit_status()

                    def on_hr(_, data):
                        if not data:
                            return

                        flags = data[0]

                        if flags & 1:
                            bpm = int.from_bytes(data[1:3], "little")
                        else:
                            bpm = data[1]

                        asyncio.create_task(
                            self.emit_heart_rate(bpm)
                        )

                    def on_ecg(_, data):
                        if len(data) < 10:
                            return

                        payload = data[10:]

                        for i in range(0, len(payload), 3):
                            if i + 2 >= len(payload):
                                break

                            raw = int.from_bytes(
                                payload[i:i+3],
                                byteorder="little",
                                signed=True
                            )

                            asyncio.create_task(
                                self.emit_ecg(raw)
                            )

                    await client.start_notify(
                        HR_CHAR_UUID,
                        on_hr
                    )

                    await client.write_gatt_char(
                        PMD_CONTROL,
                        bytearray([
                            0x02, 0x00,
                            0x00, 0x01,
                            0x82, 0x00,
                            0x01, 0x01,
                            0x0E, 0x00
                        ]),
                        response=True
                    )

                    await client.start_notify(
                        PMD_DATA,
                        on_ecg
                    )

                    while client.is_connected:
                        await asyncio.sleep(1)

            except Exception as e:
                logging.warning("Polar error: %s", e)
                await asyncio.sleep(3)

            finally:
                self.polar_connected = False
                await self.emit_status()

    async def run(self):
        async with serve(self.ws_handler, "0.0.0.0", SERVER_PORT):
            hc_task = asyncio.create_task(self.run_hc06())

            await asyncio.sleep(5)

            polar_task = asyncio.create_task(self.run_polar())

            await asyncio.gather(hc_task, polar_task)


def main():
    logging.basicConfig(level=logging.INFO)
    backend = Backend()
    asyncio.run(backend.run())


if __name__ == "__main__":
    main()