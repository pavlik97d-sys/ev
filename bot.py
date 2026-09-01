import io
import os
import re
import time
import json
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException

TOKEN = '8952822528:AAF8qGUF4bdgYNUaoJ29pHDide4XtBjlRUU'
WEB_APP_URL = 'https://pavlik97d-sys.github.io/ev/?v=103'
OCR_API_KEY = 'K81090819088957'

SUPABASE_REST = 'https://smxvjnlbwiaoudwlbvud.supabase.co/rest/v1/ev_cars'
SUPABASE_KEY = 'sb_publishable_XZpvUvSdYte6jLJsWDMNJg_YWgVHkc2'

bot = telebot.TeleBot(TOKEN)

# Временное хранилище текущей сессии перед сохранением
# { user_id: { "kwh": 13.2, "car": {...}, "odo": 12000, "user_name": "Pavel" } }
PENDING_SESSIONS = {}

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass

def run_http_server():
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

def get_supabase_headers():
    return {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    }

def find_user_car(user_id):
    try:
        res = requests.get(f"{SUPABASE_REST}?select=*", headers=get_supabase_headers(), timeout=5)
        if res.ok:
            cars = res.json()
            user_str = str(user_id)
            for car in cars:
                if str(car.get('owner_id')) == user_str:
                    return car
                drivers = car.get('drivers') or []
                if isinstance(drivers, list) and user_str in [str(d) for d in drivers]:
                    return car
            if cars:
                return cars[0]
    except Exception as e:
        print(f"Supabase error: {e}")
    return None

def update_car_in_supabase(car):
    try:
        url = f"{SUPABASE_REST}?id=eq.{car['id']}"
        payload = {
            'logs': car.get('logs', []),
            'updated_at': datetime.utcnow().isoformat()
        }
        res = requests.patch(url, headers=get_supabase_headers(), json=payload, timeout=5)
        return res.ok
    except Exception as e:
        print(f"Update error: {e}")
        return False

def parse_charging_screen(text):
    clean_text = text.replace(',', '.')
    
    # Поиск разовой сессии: Энергия XX.X kwh
    energy_match = re.search(r'(?:энергия|energy)[\s:]*([0-9]+(?:\.[0-9]+)?)\s*(?:kwh|квт)?', clean_text, re.IGNORECASE)
    if energy_match:
        return float(energy_match.group(1))

    # Резервный поиск числа перед kwh
    kwh_match = re.findall(r'([0-9]+(?:\.[0-9]+)?)\s*(?:kwh|квт)', clean_text, re.IGNORECASE)
    if kwh_match:
        return float(kwh_match[0])

    return None

def analyze_photo_with_ocr(image_bytes):
    try:
        url = 'https://api.ocr.space/parse/image'
        files = {'file': ('screen.jpg', image_bytes, 'image/jpeg')}
        payload = {
            'apikey': OCR_API_KEY,
            'language': 'rus',
            'isOverlayRequired': False,
            'detectOrientation': True,
            'scale': True,
            'OCREngine': 2
        }
        response = requests.post(url, files=files, data=payload, timeout=15)
        if response.ok:
            result = response.json()
            if result.get('IsErroredOnProcessing'):
                return None, f"Ошибка OCR: {result.get('ErrorMessage')}"
            
            parsed_results = result.get('ParsedResults', [])
            if not parsed_results:
                return None, "Не удалось прочитать текст на фото"
            
            full_text = parsed_results[0].get('ParsedText', '')
            kwh = parse_charging_screen(full_text)
            
            if kwh is not None:
                return kwh, None
            else:
                return None, "Цифры зарядки (кВт⋅ч) не обнаружены на дисплее"
        else:
            return None, f"Ошибка сервера OCR: {response.status_code}"
    except Exception as e:
        return None, f"Ошибка сервиса: {str(e)}"

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    web_app = types.WebAppInfo(url=WEB_APP_URL)
    markup.add(
        types.KeyboardButton(text="⚡ Открыть EV Garage", web_app=web_app),
        types.KeyboardButton(text="🔄 Пробудить / Обновить бота")
    )
    return markup

@bot.message_handler(commands=['start'])
def start_handler(message):
    bot.send_message(
        message.chat.id,
        "👋 EV Garage готов к работе!\n\n📸 Отправьте фото экрана зарядной станции.",
        reply_markup=get_main_keyboard()
    )

@bot.message_handler(func=lambda msg: msg.text == "🔄 Пробудить / Обновить бота")
def wake_up_handler(message):
    start_handler(message)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Водитель"
    
    status_msg = bot.reply_to(message, "⚡ Считываю показатели с фото...")

    try:
        photo_obj = message.photo[-2] if len(message.photo) > 1 else message.photo[-1]
        file_info = bot.get_file(photo_obj.file_id)
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
        img_res = requests.get(file_url, timeout=8)
        
        if not img_res.ok:
            bot.send_message(message.chat.id, "❌ Не удалось скачать фото из Telegram.")
            return

        kwh_val, err = analyze_photo_with_ocr(img_res.content)

        try:
            bot.delete_message(message.chat.id, status_msg.message_id)
        except Exception:
            pass

        if err or kwh_val is None:
            bot.send_message(message.chat.id, f"⚠️ {err or 'Не удалось распознать кВт⋅ч'}")
            return

        car = find_user_car(user_id)
        if not car:
            bot.send_message(message.chat.id, "⚠️ Автомобиль не найден в базе Supabase.")
            return

        logs = car.get('logs') or []
        last_odo = logs[-1].get('odo', 0) if logs else 0
        rates = car.get('rates') or {'night': 2.8, 'day': 6.5, 'work': 0.0, 'ez': 19.0}

        # Сохраняем во временный буфер
        PENDING_SESSIONS[user_id] = {
            'kwh': kwh_val,
            'car': car,
            'odo': last_odo,
            'user_name': user_name
        }

        # Клавиатура выбора локации и тарифа
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_night = types.InlineKeyboardButton(f"🌙 Ночь ({rates.get('night', 2.8)}₽)", callback_data="loc_night")
        btn_day   = types.InlineKeyboardButton(f"☀️ День ({rates.get('day', 6.5)}₽)", callback_data="loc_day")
        btn_work  = types.InlineKeyboardButton(f"🏢 Работа ({rates.get('work', 0.0)}₽)", callback_data="loc_work")
        btn_ez    = types.InlineKeyboardButton(f"⚡ ЭЗС ({rates.get('ez', 19.0)}₽)", callback_data="loc_ez")
        btn_cancel = types.InlineKeyboardButton("❌ Отмена", callback_data="loc_cancel")
        markup.add(btn_night, btn_day, btn_work, btn_ez, btn_cancel)

        bot.send_message(
            message.chat.id,
            f"🔋 Распознано: **{kwh_val} кВт⋅ч**\n"
            f"🛣️ Текущий пробег в базе: **{last_odo} км**\n\n"
            f"Выберите тариф и локацию для сохранения (или отправьте число, чтобы обновить пробег):",
            reply_markup=markup,
            parse_mode="Markdown"
        )

    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Ошибка обработки: {str(e)}")

# Обработка ввода нового пробега текстом
@bot.message_handler(func=lambda msg: msg.text and msg.text.isdigit())
def handle_mileage_input(message):
    user_id = message.from_user.id
    if user_id in PENDING_SESSIONS:
        new_odo = int(message.text)
        PENDING_SESSIONS[user_id]['odo'] = new_odo
        bot.reply_to(message, f"👌 Пробег обновлен на **{new_odo} км**. Теперь выберите тариф выше 👆", parse_mode="Markdown")

# Обработка клика по кнопке тарифа
@bot.callback_query_handler(func=lambda call: call.data.startswith('loc_'))
def handle_location_callback(call):
    user_id = call.from_user.id
    data = PENDING_SESSIONS.get(user_id)

    if not data:
        bot.answer_callback_query(call.id, "Сессия устарела. Отправьте фото заново.", show_alert=True)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        return

    if call.data == "loc_cancel":
        del PENDING_SESSIONS[user_id]
        bot.edit_message_text("❌ Запись отменена.", call.message.chat.id, call.message.message_id)
        return

    car = data['car']
    kwh_val = data['kwh']
    odo_val = data['odo']
    user_name = data['user_name']
    rates = car.get('rates') or {'night': 2.8, 'day': 6.5, 'work': 0.0, 'ez': 19.0}

    loc_map = {
        'loc_night': ('🏠 Дом (Ночь)', rates.get('night', 2.8)),
        'loc_day':   ('☀️ Дом (День)', rates.get('day', 6.5)),
        'loc_work':  ('🏢 Работа', rates.get('work', 0.0)),
        'loc_ez':    ('⚡ ЭЗС', rates.get('ez', 19.0))
    }

    loc_val, rate_val = loc_map.get(call.data, ('🏠 Дом', 2.8))
    total_price = round(float(kwh_val) * float(rate_val), 2)

    logs = car.get('logs') or []
    new_entry = {
        'id': str(int(datetime.utcnow().timestamp() * 1000)),
        'odo': float(odo_val),
        'kwh': float(kwh_val),
        'rate': float(rate_val),
        'location': loc_val,
        'totalPrice': total_price,
        'price': total_price,
        'author': user_name,
        'author_id': str(user_id),
        'date': datetime.utcnow().isoformat()
    }
    logs.append(new_entry)
    car['logs'] = logs

    if update_car_in_supabase(car):
        del PENDING_SESSIONS[user_id]
        markup = types.InlineKeyboardMarkup()
        web_app = types.WebAppInfo(url=WEB_APP_URL)
        btn = types.InlineKeyboardButton(text="📊 Открыть EV Garage", web_app=web_app)
        markup.add(btn)

        text_res = (
            f"✅ Сессия успешно сохранена!\n\n"
            f"🚗 Авто: {car.get('name')}\n"
            f"🔋 Заряжено: +{kwh_val} кВт⋅ч\n"
            f"📍 Локация: {loc_val} ({rate_val} ₽/кВт⋅ч)\n"
            f"💰 Стоимость: {total_price} ₽\n"
            f"🛣️ Пробег: {odo_val} км\n"
            f"👤 Записал: {user_name}"
        )
        bot.edit_message_text(text_res, call.message.chat.id, call.message.message_id, reply_markup=markup)
    else:
        bot.send_message(call.message.chat.id, "❌ Ошибка сохранения в Supabase.")

if __name__ == '__main__':
    threading.Thread(target=run_http_server, daemon=True).start()
    try:
        bot.set_my_commands([types.BotCommand("start", "⚡ Меню / Пробудить бота")])
    except Exception:
        pass
    print("Сервер запущен. Бот слушает Telegram...")

    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20, skip_pending=True)
        except ApiTelegramException as e:
            if e.error_code == 409:
                time.sleep(5)
            else:
                time.sleep(3)
        except Exception as e:
            time.sleep(3)
