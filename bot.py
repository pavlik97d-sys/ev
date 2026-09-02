import io
import os
import re
import time
import json
import base64
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException

TOKEN = '8952822528:AAF8qGUF4bdgYNUaoJ29pHDide4XtBjlRUU'
WEB_APP_URL = 'https://pavlik97d-sys.github.io/ev/?v=200'
OCR_API_KEY = 'K81090819088957'

SUPABASE_REST = 'https://smxvjnlbwiaoudwlbvud.supabase.co/rest/v1/ev_cars'
SUPABASE_KEY = 'sb_publishable_XZpvUvSdYte6jLJsWDMNJg_YWgVHkc2'

bot = telebot.TeleBot(TOKEN, threaded=True)

PENDING_SESSIONS = {}

class HealthCheckHandler(BaseHTTPRequestHandler):
    def _set_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self._set_cors_headers()
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"OK")

    def do_POST(self):
        if self.path == '/api/ocr':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)

            try:
                body = json.loads(post_data.decode('utf-8'))
                base64_image = body.get('base64Image')

                if not base64_image:
                    self.send_response(400)
                    self._set_cors_headers()
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'No image provided'}).encode('utf-8'))
                    return

                # Прямой запрос из Франкфурта к OCR без ограничений РФ
                payload = {
                    'base64Image': base64_image,
                    'apikey': OCR_API_KEY,
                    'language': 'rus',
                    'OCREngine': '1'
                }
                ocr_res = requests.post('https://api.ocr.space/parse/image', data=payload, timeout=20)
                ocr_data = ocr_res.json()

                if ocr_data.get('IsErroredOnProcessing') or not ocr_data.get('ParsedResults'):
                    self.send_response(422)
                    self._set_cors_headers()
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'OCR parse error'}).encode('utf-8'))
                    return

                text = ocr_data['ParsedResults'][0].get('ParsedText', '').replace(',', '.')

                # 1. Поиск кВт⋅ч
                kwh_match = re.search(r'(?:энергия|сумм[\.\s]*эн|energy)[\s:]*([0-9]+(?:\.[0-9]+)?)', text, re.I)
                if not kwh_match:
                    kwh_match = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*(?:kwh|квт)', text, re.I)
                if not kwh_match:
                    kwh_match = re.search(r'([0-9]+\.[0-9]+)', text)

                # 2. Поиск времени
                dur_match = re.search(r'(?:время|time)[\s:]*([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)', text, re.I)
                duration_str = ''
                if dur_match:
                    parts = dur_match.group(1).split(':')
                    duration_str = f"{int(parts[0])}ч {parts[1]}м"

                resp_payload = {
                    'kwh': kwh_match.group(1) if kwh_match else None,
                    'duration': duration_str
                }

                self.send_response(200)
                self._set_cors_headers()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(resp_payload).encode('utf-8'))

            except Exception as e:
                self.send_response(500)
                self._set_cors_headers()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self._set_cors_headers()
            self.end_headers()

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
        res = requests.get(f"{SUPABASE_REST}?select=*", headers=get_supabase_headers(), timeout=10)
        if res.ok:
            cars = res.json()
            user_str = str(user_id)
            for car in cars:
                if str(car.get('owner_id')) == user_str:
                    return car
            for car in cars:
                drivers = car.get('drivers') or []
                if isinstance(drivers, list) and user_str in [str(d) for d in drivers]:
                    return car
            for car in cars:
                if 'geely' in str(car.get('name', '')).lower():
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
        res = requests.patch(url, headers=get_supabase_headers(), json=payload, timeout=10)
        return res.ok
    except Exception as e:
        print(f"Update error: {e}")
        return False

def parse_charging_screen(text):
    clean_text = text.replace(',', '.')
    energy_match = re.search(r'(?:энергия|energy)[\s:]*([0-9]+(?:\.[0-9]+)?)\s*(?:kwh|квт)?', clean_text, re.IGNORECASE)
    if energy_match:
        return float(energy_match.group(1))

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
        response = requests.post(url, files=files, data=payload, timeout=25)
        if response.ok:
            result = response.json()
            if result.get('IsErroredOnProcessing'):
                return None, f"Ошибка OCR: {result.get('ErrorMessage')}"
            
            parsed_results = result.get('ParsedResults', [])
            if not parsed_results:
                return None, "Не удалось распознать текст на фото"
            
            full_text = parsed_results[0].get('ParsedText', '')
            kwh = parse_charging_screen(full_text)
            
            if kwh is not None:
                return kwh, None
            else:
                return None, "Цифры энергии не найдены. Сфотографируйте экран чуть ближе."
        else:
            return None, f"Сервер OCR недоступен: {response.status_code}"
    except Exception as e:
        return None, f"Таймаут OCR: {str(e)}"

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
        "👋 EV Garage на связи!\n\n📸 Отправьте фото экрана зарядки — бот автоматически считает кВт⋅ч.",
        reply_markup=get_main_keyboard()
    )

@bot.message_handler(func=lambda msg: msg.text == "🔄 Пробудить / Обновить бота")
def wake_up_handler(message):
    start_handler(message)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Водитель"
    
    status_msg = bot.reply_to(message, "⚡ Считываю показатели с дисплея...")

    try:
        photo_obj = message.photo[-1]
        file_info = bot.get_file(photo_obj.file_id)
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
        img_res = requests.get(file_url, timeout=12)
        
        if not img_res.ok:
            bot.edit_message_text("❌ Ошибка загрузки фото из Telegram.", message.chat.id, status_msg.message_id)
            return

        kwh_val, err = analyze_photo_with_ocr(img_res.content)

        if err or kwh_val is None:
            bot.edit_message_text(f"⚠️ {err or 'Не удалось считать данные'}", message.chat.id, status_msg.message_id)
            return

        car = find_user_car(user_id)
        if not car:
            bot.edit_message_text("⚠️ Автомобиль не найден в базе Supabase.", message.chat.id, status_msg.message_id)
            return

        logs = car.get('logs') or []
        last_odo = logs[-1].get('odo', 0) if logs else 0
        rates = car.get('rates') or {'night': 2.8, 'day': 6.5, 'work': 0.0, 'ez': 19.0}

        PENDING_SESSIONS[user_id] = {
            'kwh': kwh_val,
            'car': car,
            'odo': last_odo,
            'user_name': user_name
        }

        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_night = types.InlineKeyboardButton(f"🌙 Ночь ({rates.get('night', 2.8)}₽)", callback_data="loc_night")
        btn_day   = types.InlineKeyboardButton(f"☀️ День ({rates.get('day', 6.5)}₽)", callback_data="loc_day")
        btn_work  = types.InlineKeyboardButton(f"🏢 Работа ({rates.get('work', 0.0)}₽)", callback_data="loc_work")
        btn_ez    = types.InlineKeyboardButton(f"⚡ ЭЗС ({rates.get('ez', 19.0)}₽)", callback_data="loc_ez")
        btn_cancel = types.InlineKeyboardButton("❌ Отмена", callback_data="loc_cancel")
        markup.add(btn_night, btn_day, btn_work, btn_ez, btn_cancel)

        bot.edit_message_text(
            f"🔋 На экране обнаружено: **{kwh_val} кВт⋅ч**\n"
            f"🛣️ Текущий пробег: **{last_odo} км**\n\n"
            f"Выберите тариф или отправьте сообщением новый пробег:",
            message.chat.id,
            status_msg.message_id,
            reply_markup=markup,
            parse_mode="Markdown"
        )

    except Exception as e:
        try:
            bot.edit_message_text(f"⚠️ Ошибка обработки: {str(e)}", message.chat.id, status_msg.message_id)
        except Exception:
            bot.send_message(message.chat.id, f"⚠️ Ошибка: {str(e)}")

@bot.message_handler(func=lambda msg: msg.text and msg.text.isdigit())
def handle_mileage_input(message):
    user_id = message.from_user.id
    if user_id in PENDING_SESSIONS:
        new_odo = int(message.text)
        PENDING_SESSIONS[user_id]['odo'] = new_odo
        bot.reply_to(message, f"👌 Пробег обновлен на **{new_odo} км**. Выберите тариф кнопкой выше 👆", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('loc_'))
def handle_location_callback(call):
    user_id = call.from_user.id

    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    if call.data == "loc_cancel":
        if user_id in PENDING_SESSIONS:
            del PENDING_SESSIONS[user_id]
        try:
            bot.edit_message_text("❌ Запись отменена.", call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        return

    data = PENDING_SESSIONS.get(user_id)
    if not data:
        try:
            bot.edit_message_text("⚠️ Сессия устарела. Отправьте фото заново.", call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        return

    car = data['car']
    kwh_val = data['kwh']
    odo_val = data['odo']
    user_name = data['user_name']
    rates = car.get('rates') or {'night': 2.8, 'day': 6.5, 'work': 0.0, 'ez': 19.0}

    loc_map = {
        'loc_night': ('🏠 Дом (Ночь)', rates.get('night', 2.8)),
        'loc_day':   ('☀️ Дом (День)', rates.get('day', 6.5)),
        'loc_work':  ('💼 Работа', rates.get('work', 0.0)),
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
        if user_id in PENDING_SESSIONS:
            del PENDING_SESSIONS[user_id]
        markup = types.InlineKeyboardMarkup()
        web_app = types.WebAppInfo(url=WEB_APP_URL)
        btn = types.InlineKeyboardButton(text="📊 Открыть EV Garage", web_app=web_app)
        markup.add(btn)

        text_res = (
            f"✅ Сессия успешно сохранена!\n\n"
            f"🚗 Авто: {car.get('name')}\n"
            f"🔋 Заряжено: +{kwh_val} кВт⋅ч\n"
            f"📍 Тариф: {loc_val} ({rate_val} ₽/кВт⋅ч)\n"
            f"💰 Стоимость: {total_price} ₽\n"
            f"🛣️ Пробег: {odo_val} км\n"
            f"👤 Записал: {user_name}"
        )
        try:
            bot.edit_message_text(text_res, call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception:
            bot.send_message(call.message.chat.id, text_res, reply_markup=markup)
    else:
        bot.send_message(call.message.chat.id, "❌ Ошибка сохранения в базу данных.")

if __name__ == '__main__':
    threading.Thread(target=run_http_server, daemon=True).start()
    print("EV Garage Bot запущен...")

    while True:
        try:
            bot.infinity_polling(timeout=25, long_polling_timeout=20)
        except Exception as e:
            print(f"Polling loop error: {e}")
            time.sleep(3)
