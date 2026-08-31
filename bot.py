import os
import time
import threading
import http.server
import socketserver
import telebot
from telebot import types

TOKEN = '8952822528:AAF8qGUF4bdgYNUaoJ29pHDide4XtBjlRUU'
WEB_APP_URL = 'https://pavlik97d-sys.github.io/ev/?v=20'

# Фоновый сервер для Render 24/7
class SimpleHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("", port), SimpleHandler) as httpd:
            httpd.serve_forever()
    except Exception as e:
        print("Server error:", e)

threading.Thread(target=run_web_server, daemon=True).start()

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(func=lambda m: True)
def handle_all(message):
    try:
        kb = types.InlineKeyboardMarkup()
        btn = types.InlineKeyboardButton(text="⚡ Открыть EV Garage", web_app=types.WebAppInfo(url=WEB_APP_URL))
        kb.add(btn)

        text = (
            "🚗 **Бортовой журнал электромобилей**\n\n"
            "• Учет личных зарядок и затрат\n"
            "• Просмотр статистики любого авто в каталоге\n"
            "• Экспорт данных в Excel\n\n"
            "Нажмите кнопку ниже для перехода:"
        )

        bot.send_message(
            message.chat.id,
            text,
            parse_mode="Markdown",
            reply_markup=kb
        )
    except Exception as e:
        print("Error:", e)

if __name__ == '__main__':
    print("BOT RUNNING")
    try:
        bot.remove_webhook()
    except Exception:
        pass
    
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=15)
        except Exception as e:
            time.sleep(3)
