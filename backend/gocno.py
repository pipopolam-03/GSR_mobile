import serial
import serial.tools.list_ports
import sys
import time
import psutil

COM_PORT = "COM6"  # порт HC-06

def find_port_processes(port_name):
    """Ищем процессы, которые могут держать порт занятым"""
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'])
            if port_name in cmdline:
                processes.append(proc)
        except Exception:
            continue
    return processes

def kill_processes(processes):
    """Принудительно закрываем процессы"""
    for proc in processes:
        try:
            print(f"Killing process {proc.info['pid']} ({proc.info['name']})")
            proc.kill()
        except Exception as e:
            print(f"Не удалось убить процесс: {e}")

def check_port_free(port_name):
    """Проверяем, можно ли открыть порт"""
    try:
        s = serial.Serial(port_name)
        s.close()
        return True
    except serial.SerialException:
        return False

if __name__ == "__main__":
    # Шаг 1: закрываем зависшие процессы
    procs = find_port_processes(COM_PORT)
    if procs:
        print(f"Найдены процессы, держащие {COM_PORT}: {len(procs)}")
        kill_processes(procs)
        time.sleep(1)
    else:
        print(f"Процессы на {COM_PORT} не найдены")

    # Шаг 2: проверяем порт
    if check_port_free(COM_PORT):
        print(f"{COM_PORT} свободен и готов к использованию")
    else:
        print(f"{COM_PORT} всё ещё занят, попробуйте отключить устройство и перезапустить компьютер")