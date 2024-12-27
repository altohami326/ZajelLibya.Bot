import logging
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from flask import Flask
from threading import Thread
import math
from uisp_utils import UispMonitor

# إعداد البيانات
TELEGRAM_BOT_TOKEN = '7051781121:AAHthFAnh0dgPi93kAzOaVsBpKJIWPK-uv0'
UISP_API_URL = 'https://zajel.unmsapp.com/nms/api/v2.1'
UISP_API_TOKEN = '3028da87-0fe9-438b-b13c-b3932499a5bf'
STATION_GROUP_CHAT_ID = '-4709273496'

logging.basicConfig(level=logging.INFO)

# إعداد Flask
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    thread = Thread(target=run_flask)
    thread.start()

# حساب المسافة بين إحداثيات جغرافية
def distance_between(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    R = 6371000  # نصف قطر الأرض بالمتر
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# إرسال إشعارات الأجهزة المنقطعة
async def send_disconnected_device_alert(device, disconnection_duration, application):
    try:
        name = device['identification']['name']
        device_id = device['identification']['id']
        mac_address = device['identification'].get('mac', 'غير متوفر')
        cable_status = device['overview'].get('cable', 'غير متوفر')
        signal_strength = device['overview'].get('signal', 'غير متوفر')

        if "أيام" in disconnection_duration:
            days = int(disconnection_duration.split()[0])
            if days > 20:
                keyboard = [[
                    InlineKeyboardButton("🗑️ إزالة الجهاز", callback_data=f"remove_{device_id}"),
                    InlineKeyboardButton("🔄 إعادة الربط", callback_data=f"reconnect_{device_id}")
                ]]
                msg = (
                    f"⚠️ الجهاز '{name}' انقطاعه تجاوز 20 يومًا ({disconnection_duration}).\n"
                    f"MAC: {mac_address}\n"
                    f"حالة الكابل: {cable_status}\n"
                    f"الإشارة: {signal_strength}\n"
                )
                await application.bot.send_message(chat_id=STATION_GROUP_CHAT_ID, text=msg, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logging.error(f"Error in send_disconnected_device_alert: {e}")

# التعامل مع الأجهزة من نوع Station
async def handle_station_device(device, application):
    try:
        name = device['identification']['name']
        mac_address = device['identification'].get('mac', 'غير متوفر')
        cable_status = device['overview'].get('cable', 'غير متوفر')
        signal_strength = device['overview'].get('signal', 'غير متوفر')
        status = device['overview']['status']

        if status == 'connected' and (cable_status in ["10mp", "unplugged"] or (signal_strength != "غير متوفر" and float(signal_strength) < -70)):
            msg = (
                f"⚠️ الجهاز '{name}' متصل، لكن يوجد مشكلة:\n"
                f"MAC: {mac_address}\n"
                f"حالة الكابل: {cable_status}\n"
                f"الإشارة: {signal_strength}\n"
            )
            await application.bot.send_message(chat_id=STATION_GROUP_CHAT_ID, text=msg)

        disconnection_duration = device['overview'].get('lastSeen')
        if disconnection_duration:
            await send_disconnected_device_alert(device, disconnection_duration, application)
    except Exception as e:
        logging.error(f"Error in handle_station_device: {e}")

# مراقبة الشبكة
async def monitor_network(application):
    logging.info("Starting network monitoring...")
    uisp_monitor = UispMonitor(UISP_API_URL, UISP_API_TOKEN)

    while True:
        try:
            response = requests.get(f"{UISP_API_URL}/devices", headers=uisp_monitor.headers)
            if response.status_code == 200:
                devices = response.json()
                for device in devices:
                    role = device['identification'].get('role')
                    if role and isinstance(role, str) and role.lower() == 'station':
                        await handle_station_device(device, application)
            else:
                logging.error(f"Error fetching devices: {response.status_code}")
            await asyncio.sleep(300)
        except Exception as e:
            logging.error(f"Error in monitor_network: {e}")
            await asyncio.sleep(10)

# تشغيل الأزرار التفاعلية
async def handle_device_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("remove_"):
        device_id = data.split("_")[1]
        await query.edit_message_text(f"🗑️ تم طلب إزالة الجهاز {device_id}.")
    elif data.startswith("reconnect_"):
        device_id = data.split("_")[1]
        await query.edit_message_text(f"🔄 تم طلب إعادة ربط الجهاز {device_id}.")

# تشغيل البوت
async def run_bot():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler('start', lambda update, context: update.message.reply_text("البوت يعمل!")))
    application.add_handler(CallbackQueryHandler(handle_device_action))

    loop = asyncio.get_event_loop()
    loop.create_task(monitor_network(application))
    await application.run_polling()

if __name__ == '__main__':
    keep_alive()
    asyncio.get_event_loop().run_forever()
