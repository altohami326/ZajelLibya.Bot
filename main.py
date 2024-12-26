import logging
import requests
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
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
# دالة بسيطة لحساب المسافة بالأمتار بين نقطتين (lat1, lon1) و (lat2, lon2)
def distance_between(lat1, lon1, lat2, lon2):
    # في حال عدم وجود إحداثيات، نرجع None
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None

    # تحويل الدرجات إلى راديان
    R = 6371000  # نصف قطر الأرض بالمتر
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    dist = R * c
    return dist

# ----------------------------------------------------------
async def check_ap_frequencies(application, devices, uisp_monitor):
    """
    - نجمع أجهزة الـAP فقط
    - نأتي بموقعها (lat/long) وترددها
    - نقارن كل جهازين لمعرفة ما إذا كانت المسافة < 200 متر (مثلاً)
      والفرق بالتردد < 20 MHz (مثلاً)
    - إذا تحقق الشرطان نرسل تنبيه.
    """
    # يمكنك تعديل القيم كما يناسبك
    DISTANCE_THRESHOLD = 200.0  # 200 متر
    FREQUENCY_DIFF_THRESHOLD = 20.0  # 20 ميجاهرتز

    # جمع بيانات الـAP في قائمة
    ap_list = []
    for device in devices:
        role = device['identification']['role'].lower()
        if role in ['ap', 'access-point', 'access_point', 'access point']:  # حسب القيم التي يُرجعها UISP
            # نجلب التردد
            freq = uisp_monitor.get_frequency(device)
            # نجلب الموقع
            device_details = uisp_monitor.get_device_details(device['identification']['id'])
            if not device_details:
                continue

            location = device_details.get('location', {})
            lat = location.get('latitude')
            lon = location.get('longitude')

            # إذا لم يوجد تردد أو موقع، قد نتجاهل هذا الجهاز
            if freq is None or lat is None or lon is None:
                continue

            ap_list.append({
                'name': device['identification']['name'],
                'id': device['identification']['id'],
                'freq': freq,
                'lat': float(lat),
                'lon': float(lon)
            })

    # الآن نقارن كل جهازين
    checked_pairs = set()  # للتأكد من عدم تكرار المقارنة بين نفس الزوج
    for i in range(len(ap_list)):
        for j in range(i+1, len(ap_list)):
            ap1 = ap_list[i]
            ap2 = ap_list[j]

            dist = distance_between(ap1['lat'], ap1['lon'], ap2['lat'], ap2['lon'])
            if dist is None:
                continue

            freq_diff = abs(ap1['freq'] - ap2['freq'])

            if dist < DISTANCE_THRESHOLD and freq_diff < FREQUENCY_DIFF_THRESHOLD:
                # نرسل إشعار إلى الـCHAT_IDS
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
def build_device_message(device, cable_status=None, signal_strength=None, connection_duration=None, disconnection_duration=None):
    name = device['identification']['name']
    role = device['identification']['role']
    status = device['overview']['status']
    model = device['identification'].get('model', 'غير متوفر')
    mac_address = device['identification'].get('mac', 'غير متوفر')

    message = (
        f"الجهاز: {name} ({role})\n"
        f"الحالة: {status}\n"
        f"موديل: {model}\n"
    )

    if cable_status is not None:
        message += f"حالة الكابل: {cable_status}\n"

    if signal_strength is not None:
        message += f"الإشارة: {signal_strength}\n"

    if connection_duration is not None:
        message += f"مدة الاتصال: {connection_duration}\n"

    if disconnection_duration is not None:
        message += f"مدة الانقطاع: {disconnection_duration}\n"

    message += f"MAC: {mac_address}"
    return message

# ----------------------------------------------------------
async def monitor_network(application):
    logging.info("Starting network monitoring...")
    uisp_monitor = UispMonitor(UISP_API_URL, UISP_API_TOKEN)

    while True:
        try:
            response = requests.get(f"{UISP_API_URL}/devices", headers=uisp_monitor.headers)
            if response.status_code == 200:
                devices = response.json()

                # أولاً: فحص كل الأجهزة لإرسال التنبيهات الخاصة بالStation وغيرها
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
                                    f"⚠️ {build_device_message(device, cable_status=cable_status, signal_strength=signal_strength, connection_duration=connection_duration)}\n"
                                    f"عنوان IP: {ip_address}"
                                )
                                await application.bot.send_message(chat_id=STATION_GROUP_CHAT_ID, text=msg)

                            elif signal_strength != "غير متوفر":
                                try:
                                    if float(signal_strength) < -75:
                                        msg = (
                                            f"📡 تنبيه: {build_device_message(device, signal_strength=signal_strength, connection_duration=connection_duration)}\n"
                                            f"عنوان IP: {ip_address}"
                                        )
                                        await application.bot.send_message(chat_id=STATION_GROUP_CHAT_ID, text=msg)
                                except ValueError:
                                    logging.debug("تعذّر تحويل الإشارة إلى رقم.")
                        continue

                    # أجهزة أخرى (غير الـStation)
                    if status not in ['connected', 'active']:
                        disconnection_duration = uisp_monitor.get_disconnection_duration(device)
                        for chat_id in CHAT_IDS:
                            msg = (
                                f"⚠️ {build_device_message(device, disconnection_duration=disconnection_duration)}\n"
                                f"عنوان IP: {ip_address}"
                            )
                            await application.bot.send_message(chat_id=chat_id, text=msg)

                    # تنبيه للكابل لو كان أقل من 1000mp
                    if cable_status in ["10mp", "unplugged"]:
                        for chat_id in CHAT_IDS:
                            msg = (
                                f"🔌 تنبيه: {build_device_message(device, cable_status=cable_status)}\n"
                                f"عنوان IP: {ip_address}"
                            )
                            await application.bot.send_message(chat_id=chat_id, text=msg)

                # ثانيًا: مقارنة ترددات الـAP القريبة
                # نمرر كل الأجهزة للدالة لتقوم هي بجمع الـAPs ومقارنتها
                await check_ap_frequencies(application, devices, uisp_monitor)

            else:
                logging.error(f"Error fetching devices: {response.status_code} - {response.text}")
        except Exception as e:
            logging.error(f"Error in network monitoring: {str(e)}")

        # انتظر 5 دقائق
        await asyncio.sleep(300)

# ----------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    logging.info(f"Chat ID: {chat_id}")
    await update.message.reply_text(f"معرف المجموعة أو المحادثة: {chat_id}")

# ----------------------------------------------------------
async def run_bot():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler('start', start))

    asyncio.create_task(monitor_network(application))
    await application.run_polling()

# ----------------------------------------------------------
if __name__ == '__main__':
    keep_alive()
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    loop.run_forever()
