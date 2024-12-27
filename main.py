# main.py (المحدثة مع الأزرار التفاعلية للإشعارات)

import logging
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from flask import Flask
from threading import Thread
import json
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
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# ----------------------------------------------------------
# إشعار الأجهزة المنقطعة مع أزرار

async def send_disconnected_device_alert(device, disconnection_duration, application):
    name = device['identification']['name']
    device_id = device['identification']['id']

    # إذا تجاوزت مدة الانقطاع 20 يومًا
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
                f"⚠️ الجهاز '{name}' انقطاعه تجاوز 20 يومًا ({disconnection_duration}).\n\n"
                f"يرجى اتخاذ إجراء إذا لزم الأمر:"
            )
            for chat_id in CHAT_IDS:
                await application.bot.send_message(chat_id=chat_id, text=msg, reply_markup=reply_markup)

# ----------------------------------------------------------
# التعامل مع الأزرار

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
# تأكيد العمليات عبر النصوص

async def confirm_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if user_message.lower() == "دليل":
        action = context.user_data.get(user_id)
        if action:
            device_id = action.split("_")[2]

            if action.startswith("remove_device_"):
                uisp_monitor = UispMonitor(UISP_API_URL, UISP_API_TOKEN)
                result = uisp_monitor.remove_device(device_id)
                if result:
                    await update.message.reply_text(f"🗑️ تم إزالة الجهاز {device_id} بنجاح.")
                else:
                    await update.message.reply_text(f"❌ تعذرت إزالة الجهاز {device_id}.")

            elif action.startswith("reconnect_device_"):
                uisp_monitor = UispMonitor(UISP_API_URL, UISP_API_TOKEN)
                result = uisp_monitor.reconnect_device(device_id)
                if result:
                    await update.message.reply_text(f"🔄 تم إعادة ربط الجهاز {device_id} بنجاح.")
                else:
                    await update.message.reply_text(f"❌ تعذرت إعادة ربط الجهاز {device_id}.")

            del context.user_data[user_id]  # إزالة العملية بعد التنفيذ
        else:
            await update.message.reply_text("❌ لا يوجد إجراء محدد.")
    else:
        await update.message.reply_text("⚠️ يجب كتابة كلمة 'دليل' لتأكيد الإجراء.")

# ----------------------------------------------------------
# مراقبة الترددات والمسافات بين نقاط الوصول (Access Points)

async def check_ap_frequencies(application, devices, uisp_monitor):
    DISTANCE_THRESHOLD = 200.0  # المسافة القصوى بالأمتار
    FREQUENCY_DIFF_THRESHOLD = 20.0  # الفرق المسموح بالترددات

    ap_list = []
    for device in devices:
        role = device['identification']['role'].lower()
        if role in ['ap', 'access-point', 'access_point', 'access point']:
            freq = uisp_monitor.get_frequency(device)
            device_details = uisp_monitor.get_device_details(device['identification']['id'])
            if not device_details:
                continue

            location = device_details.get('location', {})
            lat = location.get('latitude')
            lon = location.get('longitude')

            if freq is None or lat is None or lon is None:
                continue

            ap_list.append({
                'name': device['identification']['name'],
                'id': device['identification']['id'],
                'freq': freq,
                'lat': float(lat),
                'lon': float(lon)
            })

    checked_pairs = set()
    for i in range(len(ap_list)):
        for j in range(i+1, len(ap_list)):
            ap1 = ap_list[i]
            ap2 = ap_list[j]

            dist = distance_between(ap1['lat'], ap1['lon'], ap2['lat'], ap2['lon'])
            if dist is None:
                continue

            freq_diff = abs(ap1['freq'] - ap2['freq'])

            if dist < DISTANCE_THRESHOLD and freq_diff < FREQUENCY_DIFF_THRESHOLD:
                for chat_id in CHAT_IDS:
                    msg = (
                        f"⚠️ تنبيه بخصوص الترددات المتقاربة:\n\n"
                        f"الجهاز الأول: {ap1['name']} (تردده {ap1['freq']} MHz)\n"
                        f"الجهاز الثاني: {ap2['name']} (تردده {ap2['freq']} MHz)\n\n"
                        f"المسافة التقريبية بينهما: {int(dist)} متر\n"
                        f"الفرق في التردد: {int(freq_diff)} MHz\n\n"
                        f"هذه الترددات قريبة جدًا وقد تسبب تشويشًا، الرجاء إعادة تنظيم التردد."
                    )
                    await application.bot.send_message(chat_id=chat_id, text=msg)

            checked_pairs.add((ap1['id'], ap2['id']))

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
                    role = device['identification']['role']
                    status = device['overview']['status']

                    ip_address = uisp_monitor.get_device_ip(device)
                    cable_status = uisp_monitor.get_cable_status(device)
                    signal_strength = uisp_monitor.get_signal_strength(device)
                    connection_duration = uisp_monitor.get_connection_duration(device)

                    if role == 'station':
                        if status == 'connected':
                            if cable_status in ["10mp","unplugged"]:
                                msg = (
                                    f"⚠️ {device['identification']['name']} (Station) يواجه مشكلة في الكابل ({cable_status}).\n"
                                    f"عنوان IP: {ip_address}"
                                )
                                await application.bot.send_message(chat_id=STATION_GROUP_CHAT_ID, text=msg)

                            elif signal_strength != "غير متوفر" and float(signal_strength) < -75:
                                msg = (
                                    f"📡 تنبيه: إشارة ضعيفة للجهاز {device['identification']['name']}\n"
                                    f"الإشارة: {signal_strength}\n"
                                    f"عنوان IP: {ip_address}"
                                )
                                await application.bot.send_message(chat_id=STATION_GROUP_CHAT_ID, text=msg)

                    if status not in ['connected', 'active']:
                        disconnection_duration = uisp_monitor.get_disconnection_duration(device)
                        await send_disconnected_device_alert(device, disconnection_duration, application)

                await check_ap_frequencies(application, devices, uisp_monitor)

            else:
                logging.error(f"Error fetching devices: {response.status_code} - {response.text}")
        except Exception as e:
            logging.error(f"Error in network monitoring: {str(e)}")

        await asyncio.sleep(300)

# ----------------------------------------------------------
# تشغيل البوت

async def run_bot():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler('start', lambda update, context: update.message.reply_text("البوت يعمل!")))
    application.add_handler(CallbackQueryHandler(handle_device_action))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_action))

    asyncio.create_task(monitor_network(application))
    await application.run_polling()

# ----------------------------------------------------------
if __name__ == '__main__':
    keep_alive()
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    loop.run_forever()
