import os
import sqlite3
import threading
import asyncio
from flask import Flask, render_template, request, jsonify
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery

# ==========================================
# 1. ИНИЦИАЛИЗАЦИЯ И НАСТРОЙКА ПРИЛОЖЕНИЯ
# ==========================================

app = Flask(__name__)

# Токен Telegram-бота
BOT_TOKEN = "8970932287:AAEvRQHEVqHHFyeQlXRPS6GvbLA6hkUlXME"
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_NAME = "osint_database.db"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            attempts INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ==========================================
# 2. МАРШРУТЫ И API ДЛЯ ВЕБ-САЙТА (FLASK)
# ==========================================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/user_status', methods=['POST'])
def user_status():
    data = request.json or {}
    user_id = data.get('user_id')
    
    if not user_id:
        return jsonify({'error': 'No user_id provided'}), 400

    conn = get_db_connection()
    user = conn.execute('SELECT attempts FROM users WHERE user_id = ?', (user_id,)).fetchone()

    if not user:
        conn.execute('INSERT INTO users (user_id, attempts) VALUES (?, ?)', (user_id, 1))
        conn.commit()
        attempts = 1
    else:
        attempts = user['attempts']

    conn.close()
    
    balance_display = "∞ (Админ)" if attempts >= 999999 else attempts
    return jsonify({'balance': balance_display, 'raw_attempts': attempts})

@app.route('/api/search', methods=['POST'])
def search():
    data = request.json or {}
    user_id = data.get('user_id')
    search_type = data.get('type')
    query = data.get('query')

    if not user_id or not query:
        return jsonify({'error': 'Некорректные параметры'}), 400

    conn = get_db_connection()
    user = conn.execute('SELECT attempts FROM users WHERE user_id = ?', (user_id,)).fetchone()

    if not user or user['attempts'] <= 0:
        conn.close()
        return jsonify({'error': 'У вас закончились попытки! Пополните баланс.'}), 403

    if user['attempts'] < 999999:
        conn.execute('UPDATE users SET attempts = attempts - 1 WHERE user_id = ?', (user_id,))
        conn.commit()

    updated_user = conn.execute('SELECT attempts FROM users WHERE user_id = ?', (user_id,)).fetchone()
    remaining = updated_user['attempts'] if updated_user else 0
    conn.close()

    # Динамическая генерация отчёта OSINT на основе введенного запроса
    clean_query = query.strip()

    if search_type == 'phone':
        # Очищаем номер от лишних символов для ссылок
        phone_digits = ''.join(filter(str.isdigit, clean_query))
        result_data = {
            "ТИП ЗАПРОСА": "Поиск по номеру телефона",
            "ИСХОДНЫЙ НОМЕР": clean_query,
            "ПРОВЕРКА В WHATSAPP": f"https://wa.me/{phone_digits}",
            "ПРОВЕРКА В TELEGRAM": f"https://t.me/+{phone_digits}",
            "ПОИСК СОВПАДЕНИЙ В GOOGLE": [
                f"https://www.google.com/search?q=%22{phone_digits}%22",
                f"https://www.google.com/search?q=%22{clean_query}%22"
            ],
            "ПОИСК СОВПАДЕНИЙ В ЯНДЕКС": f"https://yandex.ru/search/?text={clean_query}",
            "РЕКОМЕНДАЦИЯ": "Перейдите по ссылкам выше, чтобы проверить привязку мессенджеров и упоминания номера в сети.",
            "СТАТУС": "Данные успешно сформированы"
        }
    elif search_type == 'person':
        result_data = {
            "ТИП ЗАПРОСА": "Поиск физического лица",
            "ФИО / ДАННЫЕ": clean_query,
            "ПОИСК ВКОНТАКТЕ": [
                f"https://vk.com/search?c%5Bq%5D={clean_query}&c%5Bsection%5D=people"
            ],
            "ПОИСК В GOOGLE": [
                f"https://www.google.com/search?q=%22{clean_query}%22"
            ],
            "ПРОВЕРКА В РЕЕСТРАХ НАЛОГОПЛАТЕЛЬЩИКОВ (РК)": [
                "https://kgd.gov.kz/ru/services/taxpayer_search"
            ],
            "РЕКОМЕНДАЦИЯ": "Используйте открытые источники выше для совпадений по социальным сетям и публичным базам.",
            "СТАТУС": "Данные успешно сформированы"
        }
    elif search_type == 'social':
        result_data = {
            "ТИП ЗАПРОСА": "Поиск по никнейму / аккаунту",
            "НИКНЕЙМ": clean_query,
            "ПРОФИЛЬ TELEGRAM": f"https://t.me/{clean_query.replace('@', '')}",
            "ПРОФИЛЬ INSTAGRAM": f"https://instagram.com/{clean_query.replace('@', '')}",
            "ПРОФИЛЬ VK": f"https://vk.com/{clean_query.replace('@', '')}",
            "ПОИСК СОВПАДЕНИЙ В GOOGLE": [
                f"https://www.google.com/search?q=%22{clean_query}%22"
            ],
            "СТАТУС": "Данные успешно сформированы"
        }
    else:
        result_data = {
            "ТИП ЗАПРОСА": f"Общий поиск ({search_type})",
            "ЗАПРОС": clean_query,
            "ПОИСК В GOOGLE": [
                f"https://www.google.com/search?q={clean_query}"
            ],
            "ПОИСК В ЯНДЕКС": [
                f"https://yandex.ru/search/?text={clean_query}"
            ],
            "СТАТУС": "Данные успешно сформированы"
        }

    display_remaining = "∞" if remaining >= 999999 else remaining
    return jsonify({'success': True, 'data': result_data, 'remaining_attempts': display_remaining})

@app.route('/api/buy_attempts', methods=['POST'])
def buy_attempts():
    data = request.json or {}
    user_id = data.get('user_id')
    code = (data.get('code') or '').strip().upper()

    if not user_id:
        return jsonify({'error': 'No user_id provided'}), 400

    VALID_CODES = {
        "PROMO100": 5,
        "VIP1000": 20,
        "ADMIN_PASS": 100,
        "OSINT_CREATOR_9999_SECRET": 999999  # Администраторский промокод
    }

    if code in VALID_CODES:
        add_attempts = VALID_CODES[code]
        conn = get_db_connection()
        conn.execute('UPDATE users SET attempts = attempts + ? WHERE user_id = ?', (add_attempts, user_id))
        conn.commit()

        updated_user = conn.execute('SELECT attempts FROM users WHERE user_id = ?', (user_id,)).fetchone()
        new_balance = updated_user['attempts'] if updated_user else 0
        conn.close()

        msg_balance = "∞ (Бесконечно)" if new_balance >= 999999 else new_balance
        return jsonify({'success': True, 'message': f'Активировано! Ваш баланс: {msg_balance}'})
    else:
        return jsonify({'success': False, 'error': 'Неверный ключ доступа или промокод.'})

# ==========================================
# 3. ЛОГИКА TELEGRAM-БОТА (AIOGRAM 3)
# ==========================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 5 попыток (50 Stars)", callback_data="buy_5")],
        [InlineKeyboardButton(text="🚀 20 попыток (150 Stars)", callback_data="buy_20")]
    ])
    await message.answer(
        "👋 **Добро пожаловать в бот оплаты OSINT Search Engine!**\n\n"
        "Выберите желаемый пакет попыток для покупки за Telegram Stars:",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery):
    action = callback.data
    if action == "buy_5":
        title = "5 попыток поиска"
        description = "Пополнение баланса OSINT Search Engine на 5 запросов"
        payload = "promo_5_attempts"
        price = 50
    elif action == "buy_20":
        title = "20 попыток поиска"
        description = "Пополнение баланса OSINT Search Engine на 20 запросов"
        payload = "promo_20_attempts"
        price = 150
    else:
        await callback.answer("Ошибка выбора пакета", show_alert=True)
        return

    prices = [LabeledPrice(label=title, amount=price)]
    
    await callback.message.answer_invoice(
        title=title,
        description=description,
        payload=payload,
        provider_token="",  # Для Telegram Stars оставляем пустым
        currency="XTR",     # Валюта Telegram Stars
        prices=prices
    )
    await callback.answer()

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout.id, ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    payload = message.successful_payment.invoice_payload
    
    if payload == "promo_5_attempts":
        promo_code = "PROMO100"
    elif payload == "promo_20_attempts":
        promo_code = "VIP1000"
    else:
        promo_code = "PROMO100"

    await message.answer(
        f"✅ **Оплата прошла успешно!**\n\n"
        f"Ваш промокод доступа: `{promo_code}`\n\n"
        f"Введите его на сайте во вкладке «Пополнить», чтобы активировать попытки.",
        parse_mode="Markdown"
    )

# ==========================================
# 4. ЗАПУСК БОТА В ФОНОВОМ ПОТОКЕ И FLASK
# ==========================================

def run_bot():
    async def main():
        # Сбрасываем старые вебхуки для правильной работы поллинга
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())

# Запуск бота в отдельном Daemon-потоке
threading.Thread(target=run_bot, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
