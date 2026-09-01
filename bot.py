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
    
    # 1. Поиск блока разовой сессии: Энергия XX.X kwh
    energy_match = re.search(r'(?:энергия|energy)[\s:]*([0-9]+(?:\.[0-9]+)?)\s*(?:kwh|квт)?', clean_text, re.IGNORECASE)
    if energy_match:
        return float(energy_match.group(1))

    # 2. Поиск любого числа перед kwh/квт
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
                return {"odo": None, "kwh": kwh, "location_type": "🏠 Дом"}, None
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
        "👋 EV Garage активен!\n\n📸 Отправьте фотографию экрана зарядки или одометра для автоматической записи.",
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

        parsed, err = analyze_photo_with_ocr(img_res.content)

        try:
            bot.delete_message(message.chat.id, status_msg.message_id)
        except Exception:
            pass

        if err:
            bot.send_message(message.chat.id, f"⚠️ {err}")
            return

        if not parsed or parsed.get('kwh') is None:
            bot.send_message(message.chat.id, "⚠️ Не удалось распознать кВт⋅ч на экране. Попробуйте сфотографировать дисплей ближе.")
            return

        car = find_user_car(user_id)
        if not car:
            bot.send_message(message.chat.id, "⚠️ Автомобиль не найден в базе Supabase.")
            return

        logs = car.get('logs') or []
        odo_val = parsed.get('odo') or (logs[-1].get('odo', 0) if logs else 0)
        kwh_val = parsed.get('kwh') or 0.0
        loc_val = parsed.get('location_type') or '🏠 Дом'
        
        rates = car.get('rates') or {'night': 2.8, 'day': 6.5, 'work': 0, 'ez': 19.0}
        rate_val = rates.get('night', 2.8) if 'Дом' in loc_val else (rates.get('work', 0.0) if 'Работа' in loc_val else rates.get('ez', 19.0))
        total_price = round(float(kwh_val) * float(rate_val), 2)

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
            bot.send_message(message.chat.id, text_res, reply_markup=markup)
        else:
            bot.send_message(message.chat.id, "❌ Ошибка сохранения в Supabase.")

    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Ошибка обработки: {str(e)}")

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
