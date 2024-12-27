# main.py (محدث مع معالجة نهائية لمشكلة event loop)

import logging
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from flask import Flask
from threading import Thread
import math

from uisp_utils import UispMonitor

# -----------------------------------------------------------------------------------
# إعداد البيانات
TELEGRAM_BOT_TOKEN = '7051781121:AAHthFAnh0dgPi93kAzOaVsBpKJIWPK-uv0'
UISP_API_URL = 'https://zajel.unmsapp.com/nms/api/v2.1'
UISP_API_TOKEN = '3028da87-0fe9-438b-b13c-b3932499a5bf'

CHAT_IDS = ['2082013863', '-4695079640']
STATION_GROUP_CHAT_ID = '-4709273496'

logging.basicConfig(level=logging.DEBUG)

app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ----------------------------------------------------------
# دالة حساب المسافة بين إحداثيات جغرافية

def distance_between(lat1, lon1, lat2, lon2):
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    R = 6371000  # نصف قطر الأرض بالمتر
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lat2 - lon2)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# ----------------------------------------------------------
# إشعار الأجهزة المنقطعة مع أزرار (للأجهزة التي تجاوز انقطاعها 20 يومًا)

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
                keyboard = [
                    [
                        InlineKeyboardButton("🗑️ إزالة الجهاز", callback_data=f"confirm_remove_{device_id}"),
                        InlineKeyboardButton("🔄 إعادة الربط", callback_data=f"confirm_reconnect_{device_id}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                msg = (
                    f"⚠️ الجهاز '{name}' انقطاعه تجاوز 20 يومًا ({disconnection_duration}).\n"
                    f"MAC: {mac_address}\n"
                    f"حالة الكابل: {cable_status}\n"
                    f"الإشارة: {signal_strength}\n\n"
                    f"يرجى اتخاذ إجراء إذا لزم الأمر:"
                )
                await application.bot.send_message(chat_id=STATION_GROUP_CHAT_ID, text=msg, reply_markup=reply_markup)
    except Exception as e:
        logging.error(f"Error in send_disconnected_device_alert for {device['identification']['name']}: {str(e)}")

# ----------------------------------------------------------
# التعامل مع الأجهزة من نوع Station

async def handle_station_device(device, application):
    try:
        name = device['identification']['name']
        device_id = device['identification']['id']
        ip_address = device['overview'].get('ipAddress', 'غير متوفر')
        mac_address = device['identification'].get('mac', 'غير متوفر')
        cable_status = device['overview'].get('cable', 'غير متوفر')
        signal_strength = device['overview'].get('signal', 'غير متوفر')

        # تحقق من حالة الاتصال
        if device['overview']['status'] == 'connected':
            if cable_status in ["10mp", "unplugged"] or (signal_strength != "غير متوفر" and float(signal_strength) < -70):
                msg = (
                    f"⚠️ الجهاز '{name}'\n"
                    f"MAC: {mac_address}\n"
                    f"عنوان IP: {ip_address}\n"
                    f"حالة الكابل: {cable_status}\n"
                    f"الإشارة: {signal_strength}\n"
                    f"يرجى اتخاذ إجراء."
                )
                await application.bot.send_message(chat_id=STATION_GROUP_CHAT_ID, text=msg)

        # تحقق من الأجهزة المنقطعة لمدة تزيد عن 20 يومًا
        disconnection_duration = device['overview'].get('lastSeen')
        if disconnection_duration:
            await send_disconnected_device_alert(device, disconnection_duration, application)
    except Exception as e:
        logging.error(f"Error in handle_station_device for {device['identification']['name']}: {str(e)}")

# ----------------------------------------------------------
# التعامل مع الأزرار التفاعلية

async def handle_device_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("confirm_remove_"):
        device_id = data.split("_")[2]
        await query.edit_message_text(
            f"🗑️ تأكيد إزالة الجهاز {device_id}:\n"
            f"اكتب كلمة 'دليل' في هذه المحادثة لتأكيد الإزالة."
        )
        context.user_data[query.from_user.id] = f"remove_device_{device_id}"

    elif data.startswith("confirm_reconnect_"):
        device_id = data.split("_")[2]
        await query.edit_message_text(
            f"🔄 تأكيد إعادة الربط للجهاز {device_id}:\n"
            f"اكتب كلمة 'دليل' في هذه المحادثة لتأكيد العملية."
        )
        context.user_data[query.from_user.id] = f"reconnect_device_{device_id}"

# ----------------------------------------------------------
# المراقبة الدورية للشبكة

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
                        try:
                            await handle_station_device(device, application)
                        except Exception as e:
                            logging.error(f"Error handling station device {device['identification']['name']}: {str(e)}")

                await asyncio.sleep(300)

            else:
                logging.error(f"Error fetching devices: {response.status_code} - {response.text}")
        except Exception as e:
            logging.error(f"Error in network monitoring loop: {str(e)}")
            await asyncio.sleep(10)  # لتجنب التكرار السريع في حال وجود خطأ مستمر

# ----------------------------------------------------------
# تشغيل البوت

async def run_bot():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler('start', lambda update, context: update.message.reply_text("البوت يعمل!")))
    application.add_handler(CallbackQueryHandler(handle_device_action))

    loop = asyncio.get_event_loop()
    try:
        loop.create_task(monitor_network(application))
        loop.create_task(application.run_polling())
        loop.run_forever()
    except Exception as e:
        logging.error(f"Error while running bot: {str(e)}")

# ----------------------------------------------------------
if __name__ == '__main__':
    keep_alive()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_bot())
