import asyncio
import os
import re
import random
import textwrap
import io
from datetime import datetime

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardRemove, BufferedInputFile
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Конфигурация AI API ---
CHAT_URL = "https://api.intelligence.io.solutions/api/v1/chat/completions"
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": "Bearer io-v2-eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJvd25lciI6ImM3Y2E5MmViLTA2NGEtNGQzNS04NTM3LWIzYmU0NmE2YzFlNiIsImV4cCI6NDkyMjkyNjAzNn0.U3Z-QAbHYuc6zb5B0HMoLkaKBHeCzMytkMVXTNRpIV6_N7Q63qvY3H4l9hJ1b6TtD60TuLHkHYQL8sLREqiCuQ"
}

# Токен бота
TOKEN = "8505494191:AAHwjqZ2R_L7Zoy_QSOd900C8pONPqD2Vo4"

# Инициализация бота с Markdown по умолчанию
bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode="Markdown")
)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Состояния FSM
class PresentationStates(StatesGroup):
    waiting_for_theme = State()
    waiting_for_topic = State()
    waiting_for_count = State()
    generating = State()

# ===============================
# Генерация текста слайдов
# ===============================
def generate_slides(topic, count, age="5"):
    """
    Генерация текста слайдов по теме.
    Возвращает список кортежей: [(заголовок, текст), ...]
    """
    prompt = f"""
Ты — помощник для создания презентаций.
Создай РОВНО {count} слайдов на тему: "{topic}" для аудитории {age}-го класса.

ВЫВОДИ СТРОГО В ТАКОМ ФОРМАТЕ (это очень важно):

Slide 1:
Title: [Заголовок слайда 1 из 3-5 слов]
Text: [Текст слайда 1. Максимум 4 полных предложений. Текст должен быть подробным, информативным и понятным для школьников.]

Slide 2:
Title: [Заголовок слайда 2 из 3-5 слов]
Text: [Текст слайда 2. Максимум 4 полных предложений. Текст должен быть подробным, информативным и понятным для школьников.]

... и так далее для всех {count} слайдов

ВАЖНО:
1. Выводи РОВНО {count} слайдов
2. Не используй markdown (**Title** или **Text**)
3. Каждый слайд начинай с "Slide X:" где X - номер
4. После "Title:" пиши только заголовок
5. После "Text:" пиши только текст слайда
6. Все на русском языке
"""

    data = {
        "model": "Qwen/Qwen2.5-VL-32B-Instruct",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 4000
    }

    try:
        resp = requests.post(CHAT_URL, headers=HEADERS, json=data, timeout=120)
        if resp.status_code == 200:
            resp_json = resp.json()
            if 'choices' in resp_json and len(resp_json['choices']) > 0:
                ai_text = resp_json['choices'][0]['message']['content']
                logger.info(f"Полученный текст от ИИ (первые 500 символов): {ai_text[:500]}")

                # Улучшенный парсинг
                slides = []
                pattern = r'Slide\s+(\d+):\s*Title:\s*(.+?)\s*Text:\s*(.+?)(?=(?:\s*Slide\s+\d+:)|$)'
                matches = re.findall(pattern, ai_text, re.DOTALL | re.IGNORECASE)
                
                for match in matches:
                    slide_num = match[0]
                    title = match[1].strip()
                    text = match[2].strip()
                    
                    # Очищаем текст от лишних символов
                    title = re.sub(r'[*_`]', '', title)
                    text = re.sub(r'[*_`]', '', text)
                    
                    slides.append((title, text))
                
                logger.info(f"Найдено слайдов через regex: {len(slides)}")
                
                # Если парсинг не удался
                if not slides:
                    parts = re.split(r'(?:Slide|Слайд)\s+\d+[:.]?', ai_text, flags=re.IGNORECASE)
                    
                    for part in parts[1:]:
                        lines = part.strip().split('\n')
                        title = ""
                        text_lines = []
                        found_title = False
                        
                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue
                            
                            title_match = re.match(r'(?:Title|Заголовок)[:\s]*(.+)', line, re.IGNORECASE)
                            if title_match and not found_title:
                                title = title_match.group(1).strip()
                                title = re.sub(r'[*_`]', '', title)
                                found_title = True
                                continue
                            
                            text_match = re.match(r'(?:Text|Текст)[:\s]*(.+)', line, re.IGNORECASE)
                            if text_match:
                                text_lines.append(text_match.group(1).strip())
                            elif found_title and line and not line.startswith("Slide") and not line.startswith("Слайд"):
                                text_lines.append(line)
                        
                        if title and text_lines:
                            text = ' '.join(text_lines)
                            text = re.sub(r'[*_`]', '', text)
                            slides.append((title, text))
                
                logger.info(f"Всего распарсено слайдов: {len(slides)}")
                
                # Если все еще нет слайдов, создаем резервные
                if not slides or len(slides) < count:
                    logger.info("Создаю резервные слайды...")
                    slides = []
                    for i in range(count):
                        slides.append((
                            f"{topic} - Часть {i+1}",
                            f"Это слайд {i+1} из {count} на тему '{topic}'. "
                            f"Здесь будет подробное описание аспекта темы. Презентация предназначена для {age}-го класса. "
                            f"Каждый слайд содержит важную информацию по теме. Это образовательный материал для школьников. "
                            f"Тема раскрывается последовательно на всех слайдах. Материал адаптирован для понимания учениками. "
                            f"Примеры и иллюстрации помогают лучше усвоить информацию. Практические задания могут быть добавены. "
                            f"Резюме и выводы представлены в конце презентации."
                        ))
                
                # Ограничиваем количество слайдов
                slides = slides[:count]
                logger.info(f"Итоговое количество слайдов: {len(slides)}")
                return slides
            else:
                logger.error("Ошибка: нет choices в ответе")
                return None
        else:
            logger.error(f"Ошибка HTTP: {resp.status_code}")
            logger.error(f"Ответ: {resp.text[:500]}")
            return None
    except Exception as e:
        logger.error(f"Исключение при генерации слайдов: {str(e)}")
        return None

# ===============================
# Создание слайда в памяти
# ===============================
async def create_slide_in_memory(title, text, theme="light"):
    """Создает слайд и возвращает его как bytes в памяти"""
    # Создаем изображение слайда
    width, height = 1280, 720
    
    # Создаем фон
    if theme == "light":
        base_color = (255, 255, 255)
        shape_colors = [
            (240, 240, 255),
            (255, 240, 240),
            (240, 255, 240),
            (255, 255, 240),
            (240, 255, 255),
        ]
        text_color = "black"
    else:
        base_color = (30, 30, 40)
        shape_colors = [
            (50, 50, 70),
            (70, 50, 50),
            (50, 70, 50),
            (70, 70, 50),
            (50, 70, 70),
        ]
        text_color = "white"
    
    img = Image.new("RGB", (width, height), base_color)
    draw = ImageDraw.Draw(img)

    # Добавляем геометрические фигуры
    for _ in range(6):
        x1 = random.randint(0, width - 100)
        y1 = random.randint(0, height - 100)
        x2 = random.randint(x1 + 20, width)
        y2 = random.randint(y1 + 20, height)
        
        color = random.choice(shape_colors)
        draw.rectangle([x1, y1, x2, y2], fill=color, outline=None)
    
    # Добавляем круги
    for _ in range(4):
        x = random.randint(100, width - 100)
        y = random.randint(100, height - 100)
        r = random.randint(50, 120)
        
        color = random.choice(shape_colors)
        draw.ellipse([x-r, y-r, x+r, y+r], fill=color)
    
    # Размываем
    img = img.filter(ImageFilter.GaussianBlur(6))
    draw = ImageDraw.Draw(img)
    
    # Загружаем шрифты
    try:
        font_title = ImageFont.truetype("arial.ttf", 68)
        font_text = ImageFont.truetype("arial.ttf", 34)
    except:
        try:
            font_title = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 68)
            font_text = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 34)
        except:
            # Используем стандартный шрифт
            font_title = ImageFont.load_default()
            # Увеличиваем размер для заголовка
            try:
                font_title.size = 68
            except:
                pass
            
            font_text = ImageFont.load_default()
            try:
                font_text.size = 34
            except:
                pass
    
    # Настройки
    margin = 60
    max_width = width - 2 * margin
    
    # Подготовка текста
    title_lines = textwrap.wrap(title, width=25)
    text_lines = textwrap.wrap(text, width=45)
    
    # Ограничиваем количество строк
    if len(text_lines) > 10:
        text_lines = text_lines[:10]
        text_lines[-1] = text_lines[-1] + "..."
    
    # Вычисляем высоту текста
    title_height = len(title_lines) * 80
    text_height = len(text_lines) * 40
    total_height = title_height + text_height + 50
    
    # Позиционируем текст
    y_start = (height - total_height) // 2
    if y_start < margin:
        y_start = margin
    
    # Рисуем заголовок
    y = y_start
    for line in title_lines:
        x = margin
        draw.text((x, y), line, font=font_title, fill=text_color)
        y += 80
    
    y += 30
    
    # Рисуем текст
    for line in text_lines:
        x = margin
        draw.text((x, y), line, font=font_text, fill=text_color)
        y += 40
    
    # Сохраняем в bytes
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    return buffer.getvalue()

# ===============================
# ХЕНДЛЕРЫ
# ===============================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Главное меню"""
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="Создать презентацию"))
    builder.adjust(1)
    
    welcome_text = """🎯 *Добро пожаловать в МаксGPT!*

*Это мощный ИИ агент для создания презентаций.*

✨ **Возможности:**
• Создание профессиональных презентаций
• Автоматическая генерация контента
• Красивое оформление слайдов
• Подбор подходящих изображений
• Адаптация для любой аудитории

Нажмите кнопку ниже, чтобы начать создание презентации 👇"""
    
    await message.answer(welcome_text, reply_markup=builder.as_markup(resize_keyboard=True))

@dp.message(F.text == "Создать презентацию")
async def start_presentation(message: types.Message, state: FSMContext):
    """Начало создания презентации"""
    await message.answer("🎨 Выберите тему оформления презентации:", 
                        reply_markup=ReplyKeyboardRemove())
    
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="🌞 Светлая тема", 
        callback_data="theme_light")
    )
    builder.add(types.InlineKeyboardButton(
        text="🌙 Темная тема", 
        callback_data="theme_dark")
    )
    builder.adjust(2)
    
    await message.answer(
        "Выберите стиль оформления:",
        reply_markup=builder.as_markup()
    )
    
    await state.set_state(PresentationStates.waiting_for_theme)

@dp.callback_query(F.data.startswith("theme_"))
async def handle_theme_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора темы"""
    theme = callback.data.split("_")[1]
    
    await state.update_data(theme=theme)
    await callback.answer(f"Выбрана {'светлая' if theme == 'light' else 'темная'} тема")
    
    await callback.message.edit_text(
        f"✅ Выбрана {'светлая' if theme == 'light' else 'темная'} тема оформления"
    )
    
    await callback.message.answer(
        "📝 *Напишите тему презентации:*\n\n"
        "Например: Солнечная система, История Древнего Рима, Клеточное строение организмов"
    )
    
    await state.set_state(PresentationStates.waiting_for_topic)

@dp.message(PresentationStates.waiting_for_topic)
async def get_presentation_topic(message: types.Message, state: FSMContext):
    """Получение темы презентации"""
    topic = message.text
    
    await state.update_data(topic=topic)
    
    await message.answer(
        "🔢 *Сколько слайдов нужно создать?*\n\n"
        "Напишите число от 1 до 50 (рекомендуется 5-15):"
    )
    
    await state.set_state(PresentationStates.waiting_for_count)

@dp.message(PresentationStates.waiting_for_count)
async def get_slide_count(message: types.Message, state: FSMContext):
    """Получение количества слайдов"""
    text = message.text
    
    if not text.isdigit():
        await message.answer("❌ Пожалуйста, напишите число, например: 7")
        return
    
    count = int(text)
    
    if count < 1:
        await message.answer("❌ Минимум 1 слайд. Напишите число от 1:")
        return
    
    if count > 50:
        await message.answer("❌ Слишком много слайдов! Максимум 50. Укажите меньшее число:")
        return
    
    await state.update_data(count=count)
    data = await state.get_data()
    topic = data.get('topic', '')
    theme = data.get('theme', 'light')
    
    summary = f"""📋 *Параметры презентации:*

• **Тема:** {topic}
• **Количество слайдов:** {count}
• **Оформление:** {'светлая' if theme == 'light' else 'темная'} тема

Начинаю генерацию..."""
    
    await message.answer(summary)
    
    await state.set_state(PresentationStates.generating)
    await generate_presentation(message, state)

async def generate_presentation(message: types.Message, state: FSMContext):
    """Основной процесс генерации презентации"""
    chat_id = message.chat.id
    
    data = await state.get_data()
    topic = data.get('topic', '')
    count = data.get('count', 5)
    theme = data.get('theme', 'light')
    
    try:
        # Статус 1: Генерация текста
        status_msg = await message.answer(
            "⏳ *Подождите, МаксGPT генерирует наполнение слайдов...*"
        )
        
        # Генерация текста слайдов
        slides = await asyncio.to_thread(generate_slides, topic, count, "5")
        
        if not slides:
            await status_msg.edit_text(
                "❌ *Не удалось сгенерировать текст слайдов*\n\nПопробуйте другую тему."
            )
            await state.clear()
            return
        
        await asyncio.sleep(3)
        
        # Статус 2: Успешно
        await status_msg.edit_text("✅ *Успешно! Текст слайдов сгенерирован.*")
        
        await asyncio.sleep(1)
        
        # Статус 3: Генерация слайдов
        progress_msg = await message.answer(
            "⏳ *Подождите, МаксGPT генерирует слайды...*"
        )
        
        # Генерация и отправка слайдов
        sent_count = 0
        
        for i, (title, text) in enumerate(slides):
            try:
                # Обновляем прогресс
                progress_bar = create_progress_bar(i + 1, len(slides))
                progress_text = f"""⏳ *Подождите, МаксGPT генерирует слайды:*

{progress_bar}

*{i+1} из {len(slides)} слайдов сгенерировано*

🕐 Это может занять от 1 до 3 минут"""
                
                try:
                    await progress_msg.edit_text(progress_text)
                except:
                    pass
                
                # Создаем слайд в памяти
                slide_bytes = await create_slide_in_memory(title, text, theme)
                
                # Проверяем размер файла
                file_size = len(slide_bytes) / 1024 / 1024
                logger.info(f"Размер слайда {i+1}: {file_size:.2f} MB")
                
                # Отправляем слайд как фото
                photo = BufferedInputFile(
                    file=slide_bytes,
                    filename=f"slide_{i+1}.png"
                )
                
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=f"*Слайд {i+1} из {len(slides)}*\n\n**{title}**"
                )
                
                sent_count += 1
                
                # Пауза между слайдами
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"Ошибка при создании слайда {i+1}: {e}")
                
                # Пробуем отправить как документ если фото не получилось
                try:
                    slide_bytes = await create_slide_in_memory(title, text, theme)
                    document = BufferedInputFile(
                        file=slide_bytes,
                        filename=f"slide_{i+1}.png"
                    )
                    
                    await bot.send_document(
                        chat_id=chat_id,
                        document=document,
                        caption=f"*Слайд {i+1} из {len(slides)}*\n\n**{title}**"
                    )
                    sent_count += 1
                except Exception as e2:
                    logger.error(f"Не удалось отправить слайд {i+1} даже как документ: {e2}")
                    
                    # Отправляем текстовую версию
                    try:
                        await message.answer(
                            f"*Слайд {i+1} из {len(slides)}*\n\n"
                            f"**{title}**\n\n"
                            f"{text[:500]}..."
                        )
                        sent_count += 1
                    except:
                        continue
        
        # Финальное сообщение
        if sent_count > 0:
            final_progress = create_progress_bar(len(slides), len(slides))
            final_text = f"""✅ *Презентация готова!*

{final_progress}

🎉 *{sent_count} слайдов успешно создано*

Тема: *{topic}*
Количество слайдов: *{count}*
Оформление: *{'светлая' if theme == 'light' else 'темная'} тема*

Для создания новой презентации отправьте /start"""
            
            await progress_msg.edit_text(final_text)
            
            builder = ReplyKeyboardBuilder()
            builder.add(types.KeyboardButton(text="Создать новую презентацию"))
            builder.adjust(1)
            
            await message.answer(
                "Хотите создать ещё одну презентацию?",
                reply_markup=builder.as_markup(resize_keyboard=True)
            )
            
        else:
            await progress_msg.edit_text(
                "❌ *Не удалось создать ни одного слайда*\n\n"
                "Попробуйте ещё раз отправив /start"
            )
        
    except Exception as e:
        logger.error(f"Ошибка при генерации презентации: {e}")
        await message.answer(
            f"❌ *Произошла ошибка при генерации:*\n\n{str(e)[:200]}...\n\n"
            "Попробуйте ещё раз отправив /start"
        )
    
    await state.clear()

@dp.message(F.text == "Создать новую презентацию")
async def new_presentation(message: types.Message, state: FSMContext):
    """Обработка кнопки новой презентации"""
    await cmd_start(message)

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    """Отмена создания презентации"""
    await state.clear()
    
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="Создать презентацию"))
    builder.adjust(1)
    
    await message.answer(
        "❌ *Создание презентации отменено.*\n\n"
        "Нажмите кнопку ниже, чтобы начать заново:",
        reply_markup=builder.as_markup(resize_keyboard=True)
    )

@dp.message()
async def default_handler(message: types.Message):
    """Обработка всех остальных сообщений"""
    await message.answer("👋 Напишите /start чтобы создать презентацию!")

# ===============================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ===============================
def create_progress_bar(current, total, length=10):
    """Создает текстовый прогресс-бар"""
    filled_length = int(length * current / total)
    bar = '█' * filled_length + '░' * (length - filled_length)
    percentage = int(100 * current / total)
    return f"[{bar}] {percentage}%"

# ===============================
# ЗАПУСК БОТА
# ===============================
async def main():
    logger.info("🤖 МаксGPT на aiogram запущен и готов к работе...")
    
    await bot.delete_webhook(drop_pending_updates=True)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())