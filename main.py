import os
import traceback
import re
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram.error import BadRequest
from notion_client import Client 
import html

from apscheduler.schedulers.asyncio import AsyncIOScheduler #формирование пдф 1 в неделю
import asyncio
import datetime
from fpdf.enums import XPos, YPos

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NOTION_DATABASE_OBJECTS_ID = os.getenv("NOTION_DATABASE_OBJECTS_ID")
NOTION_DATABASE_REQUESTS_ID = os.getenv("NOTION_DATABASE_REQUESTS_ID")
NOTION_DATABASE_SELECTIONS_ID = os.getenv("NOTION_DATABASE_SELECTIONS_ID")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
CHANNEL_USERNAME = "@PolarProperty"  # Замените на ваш канал
ADMIN_IDS = os.getenv("ADMIN_IDS")
if ADMIN_IDS:
    ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS.split(",") if x.strip().isdigit()]
else:
    ADMIN_IDS = []
TEST_MODE = False  # Установите False для включения проверки подписки и обновления каталога при старте
notion = Client(auth=NOTION_TOKEN)

# Состояния пользователей
user_state = {}

PAGE_SIZE = 5  # Количество объектов на страницу

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню"""
    photo_url = "https://drive.google.com/uc?export=view&id=1ahC8y6rmPg4tmqIUP1dTDwWmNymn9D0w"
    text = (
        " Добро пожаловать в PolarProperty Asia! \n\n"
        "🏝 Мы помогаем купить или арендовать недвижимость в Паттайе и по всему Таиланду.\n\n"
        "💎 Только проверенные объекты и официальные цены от застройщиков.  \n\n"
        "💬 Подбор — бесплатно.\n\n"
        "Выберите, что вас интересует 👇"
    )
    keyboard = [
        [InlineKeyboardButton("🏠 Покупка", callback_data="buy_menu")],
        [InlineKeyboardButton("🏢 Аренда", callback_data="rent_menu")],
        [InlineKeyboardButton("💬 Чат с менеджером", callback_data="question")],
        [InlineKeyboardButton("ℹ️ О нас", callback_data="about")],
        [InlineKeyboardButton("📞 Контакты", callback_data="contact")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Универсально: если это callback, используем callback_query.message, иначе update.message
    message = getattr(update, "message", None)
    if message is None and hasattr(update, "callback_query"):
        message = update.callback_query.message

    try:
        await message.reply_photo(photo=photo_url, caption=text, reply_markup=reply_markup)
    except Exception:
        await message.reply_text(text, reply_markup=reply_markup)

def get_back_button():
    """Кнопка возврата в главное меню"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад в меню", callback_data="menu")]])


async def is_user_subscribed(user_id, context):
    """Проверка подписки на канал"""
    try:
        print(f"🔍 Проверяем подписку пользователя {user_id} на канал {CHANNEL_USERNAME}")
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        print(f"📋 Статус пользователя: {member.status}")
        is_subscribed = member.status in ["member", "administrator", "creator"]
        print(f"✅ Подписан: {is_subscribed}")
        return is_subscribed
    except BadRequest as e:
        print(f"❌ Ошибка проверки подписки: {e}")
        return False
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        return False

async def get_properties():
    """Получение объектов из Notion с улучшенной обработкой ошибок
    Возвращает список dict с ключами: project_name, status, district, prices, developer,
    enddate, payments, comments, photo_url, id
    """
    try:
        response = notion.databases.query(database_id=NOTION_DATABASE_OBJECTS_ID)
        results = response.get("results", [])

        if not results:
            print("⚠️ База данных пуста")
            return None

        properties = []
        for item in results:
            try:
                props = item.get("properties", {})

                # Название проекта (адаптируйте имена полей при необходимости)
                project_name = props.get("Название проекта", {}).get("title", [{}])[0].get("text", {}).get("content", "Без названия")
                # Статус и район
                status = props.get("Статус", {}).get("select", {}).get("name", "Не указано")
                district = props.get("Район", {}).get("select", {}).get("name", "Не указано")

                # Застройщик / rich_text
                developer_rich = props.get("Застройщик", {}).get("rich_text", [])
                developer = "".join([t.get("text", {}).get("content", "") for t in developer_rich]) if developer_rich else "Не указано"

                # Срок сдачи
                enddate = props.get("Срок сдачи", {}).get("number", "Не указано")

                # Условия оплаты
                payments_rich = props.get("Условия оплаты", {}).get("rich_text", [])
                payments = "".join([t.get("text", {}).get("content", "") for t in payments_rich]) if payments_rich else "Не указано"

                # Описание
                comments_rich = props.get("Описание", {}).get("rich_text", [])
                comments = "".join([t.get("text", {}).get("content", "") for t in comments_rich]) if comments_rich else "Не указано"

                # Цены
                prices = {
                    "studio": props.get("Студия (THB)", {}).get("number"),
                    "1br": props.get("1BR (THB)", {}).get("number"),
                    "2br": props.get("2BR (THB)", {}).get("number"),
                    "3br": props.get("3BR (THB)", {}).get("number"),
                    "penthouse": props.get("Пентхаус (THB)", {}).get("number")
                }

                # Фото (file / external)
                photo_url = None
                photo_field = props.get("Фото", {}).get("files", [])
                if photo_field:
                    if "file" in photo_field[0]:
                        photo_url = fix_drive_url(photo_field[0]["file"].get("url"))
                    elif "external" in photo_field[0]:
                        photo_url = fix_drive_url(photo_field[0]["external"].get("url"))

                # Уникальный ID из колонки "ID" (может быть title/rich_text/number)
                unique_id = ""
                id_field = props.get("ID") or props.get("Id") or props.get("id")
                if id_field:
                    # try different types
                    if isinstance(id_field.get("number"), (int, float)):
                        unique_id = str(id_field.get("number"))
                    elif id_field.get("type") == "title":
                        unique_id = id_field.get("title", [{}])[0].get("text", {}).get("content", "")
                    elif id_field.get("type") == "rich_text":
                        unique_id = "".join([t.get("text", {}).get("content", "") for t in id_field.get("rich_text", [])])
                    else:
                        # fallback: try common keys
                        for k in ("plain_text", "text", "content"):
                            v = id_field.get(k)
                            if v:
                                unique_id = v
                                break

                properties.append({
                    "project_name": project_name,
                    "status": status,
                    "district": district,
                    "prices": prices,
                    "developer": developer,
                    "enddate": enddate,
                    "payments": payments,
                    "comments": comments,
                    "photo_url": photo_url,
                    "id": unique_id,
                    "raw": item
                })

            except Exception as e:
                print(f"⚠️ Ошибка обработки объекта: {e}")
                continue

        return properties

    except Exception as e:
        print(f"❌ Критическая ошибка при запросе к Notion: {e}")
        return None
        
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "buy_menu":
        keyboard = [
            [InlineKeyboardButton("📂 Список объектов", callback_data="catalog")],
            [InlineKeyboardButton("📥 Скачать каталог PDF", callback_data="download_pdf")],
            [InlineKeyboardButton("📩 Подбор квартиры", callback_data="selection")],
            [InlineKeyboardButton("🔙 Назад в меню", callback_data="menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            "🏠 Покупка недвижимости\n\nВыберите, что вас интересует 👇",
            reply_markup=reply_markup
        )
        return

    elif query.data == "rent_menu":
        wa_msg = "Здравствуйте! Интересует аренда недвижимости в Таиланде."
        wa_msg_encoded = wa_msg.replace(" ", "%20")

        contact_text = (
            "👋 По всем вопросам по поводу аренды напишите нашим менеджерам:\n\n"
            "👩‍💼 Любовь\n"
            f"✈️  Tg: @lyubov_danilove\n"
            f"🇷🇺 <a href=\"https://wa.me/79644229573?text={wa_msg_encoded}\">+7 964 422 95 73 (WhatsApp)</a>\n"
            f"🇹🇭  <a href=\"https://wa.me/66968300106?text={wa_msg_encoded}\">+66 96 830 01 06 (WhatsApp)</a>\n\n"
            "👩‍💼 Надежда \n"
            f"✈️  Tg: @mandarinka_nadya\n"
            f"🇷🇺 <a href=\"https://wa.me/79241713616?text={wa_msg_encoded}\">+7 924 171 36 16 (WhatsApp)</a>\n"
            
        )
        await query.message.reply_text(
            contact_text,
            reply_markup=get_back_button(),
            disable_web_page_preview=True,
            parse_mode="HTML"
        )
        return

    elif query.data == "selection":
        user_state[query.from_user.id] = {"step": 0, "data": {}, "type": "selection"}
        await query.message.reply_text(
            SELECTION_QUESTIONS[0],
            reply_markup=get_back_button()
        )
        return

    elif query.data == "question":
        
        contact_text = (
            "👋 Задайте вопрос нашим менеджерам:\n\n"
            "👩‍💼 Любовь\n"
            f"✈️  Tg: @lyubov_danilove\n"
            f"🇷🇺 <a href=\"https://wa.me/79644229573\">+7 964 422 95 73 (WhatsApp)</a>\n"
            f"🇹🇭  <a href=\"https://wa.me/66968300106\">+66 96 830 01 06 (WhatsApp)</a>\n\n"
            "👩‍💼 Надежда \n"
            f"✈️  Tg: @mandarinka_nadya\n"
            f"🇷🇺 <a href=\"https://wa.me/79241713616\">+7 924 171 36 16 (WhatsApp)</a>\n"            
        )
        await query.message.reply_text(
            contact_text,
            reply_markup=get_back_button(),
            disable_web_page_preview=True,
            parse_mode="HTML"
        )
        return

    elif query.data == "contact":        
        contact_text = (
            " Наши контакты:\n"
            "✈️ Telegram: <a href=\"https://t.me/PolarProperty\">@PolarProperty</a>\n"
            "📷 Instagram: <a href=\"https://www.instagram.com/polar.property/\">@Polar.Property</a>\n"
            "💬 WhatsApp: <a href=\"https://wa.me/66968300106\"> Написать</a>\n"
            "📞 +66 96 830 01 06\n"
            "📍 Паттайя, Таиланд\n"
            "💙 Мы на связи 24/7"

        )
        await query.message.reply_text(
            contact_text,
            reply_markup=get_back_button(),
            disable_web_page_preview=True,
            parse_mode="HTML"
        )
        return

    elif query.data == "about":
        about_photo = "https://drive.google.com/uc?export=view&id=120dGw098edD-hVUClSX68VtTaaYODQng"
        contact_text = (
            "🏢 PolarProperty Asia — официальный представитель ведущих застройщиков Таиланда.\n"  
            "✅ Работаем без комиссии для покупателя\n"
            "✅ Сопровождаем сделку на всех этапах\n"
            "✅ Дистанционные сделки\n"
            "✅ Проверенные объекты\n"
        )
        await query.message.reply_photo(
            photo=about_photo,
            caption=contact_text,
            reply_markup=get_back_button(),
            parse_mode="HTML"
        )
        return


    elif query.data.startswith("catalog"):
        parts = query.data.split("_")
        page = int(parts[1]) if len(parts) > 1 else 0

        is_subscribed = TEST_MODE or await is_user_subscribed(query.from_user.id, context)
        if is_subscribed:
            properties = await get_properties()
            if not properties:
                await query.message.reply_text(
                    "❌ В данный момент нет доступных объектов",
                    reply_markup=get_back_button()
                )
                return

            total = len(properties)
            end = min(page + PAGE_SIZE, total)
            for idx in range(page, end):
                prop = properties[idx]
                short_text = (
                    f"<b>{escape_html(prop['project_name'])}</b>\n"
                    f"📍 Район: {escape_html(prop['district'])}\n"
                    f"🏗 Статус: {escape_html(prop['status'])}\n"
                    f"📅 Срок сдачи: {escape_html(prop['enddate'])}"
                )
                reply_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔎 Подробнее", callback_data=f"object_{idx}")],
                ])
                if prop.get("photo_url"):
                    await query.message.reply_photo(
                        photo=prop["photo_url"],
                        caption=short_text,
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )
                else:
                    await query.message.reply_text(
                        short_text,
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )

            # Кнопки пагинации
            nav_buttons = []
            nav_buttons.append(InlineKeyboardButton("🔙 Назад в меню", callback_data="menu"))
            if end < total:
                nav_buttons.append(InlineKeyboardButton("➡️ Следующие", callback_data=f"catalog_{end}"))
            reply_markup = InlineKeyboardMarkup([nav_buttons])
            await query.message.reply_text(
                f"Показаны объекты {page+1}-{end} из {total}.",
                reply_markup=reply_markup
            )
        else:
            keyboard = [
                [InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
                [InlineKeyboardButton("✅ Проверить подписку", callback_data="catalog_0")],
                [InlineKeyboardButton("🔙 Назад в меню", callback_data="menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                f"❗️ Для получения каталога подпишитесь на наш канал: {CHANNEL_USERNAME}\n\n"
                "После подписки нажмите 'Проверить подписку'",
                reply_markup=reply_markup
            )
            return
    # Добавьте обработку object_{idx} для подробной карточки
    elif query.data.startswith("object_"):
        idx = int(query.data.split("_")[1])
        properties = await get_properties()
        if not properties or idx >= len(properties):
            await query.message.reply_text("❌ Объект не найден.", reply_markup=get_back_button())
            return
        prop = properties[idx]
        prices = prop['prices']
        detail_text = (
            f"<b>{escape_html(prop['project_name'])}</b>\n"
            f"📍 Район: {escape_html(prop['district'])}\n"
            f"🏗 Статус: {escape_html(prop['status'])}\n"
            f"🏢 Застройщик: {escape_html(prop['developer'])}\n"
            f"📅 Срок сдачи: {escape_html(prop['enddate'])}\n"
            f"💰 Цены:\n"
            f"   - Студия: от {escape_html(format_price(prices['studio']))} THB\n"
            f"   - 1BR: от {escape_html(format_price(prices['1br']))} THB\n"
            f"   - 2BR: от {escape_html(format_price(prices['2br']))} THB\n"
            f"   - 3BR: от {escape_html(format_price(prices['3br']))} THB\n"
            f"   - Пентхаус: от {escape_html(format_price(prices['penthouse']))} THB\n"
            f"💳 Условия оплаты: По запросу\n" #{escape_html(prop['payments'])}
            f"📝 Описание: {escape_html(prop['comments'])}\n"
        )
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("ℹ📬 Запросить подробную информацию", callback_data=f"request_{idx+1}")],
            [InlineKeyboardButton("🔙 Назад к списку", callback_data="catalog_0")]
        ])
        if prop.get("photo_url"):
            await query.message.reply_photo(
                photo=prop["photo_url"],
                caption=detail_text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        else:
            await query.message.reply_text(
                detail_text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )

    # Добавьте обработку callback_data для заявки на объект
    elif query.data.startswith("request_"):
        try:
            idx = int(query.data.split("_")[1]) - 1
            properties = await get_properties()
            if not properties or idx >= len(properties):
                await query.message.reply_text("❌ Объект не найден.", reply_markup=get_back_button())
                return
            prop = properties[idx]
            user_id = query.from_user.id
            user_name = query.from_user.first_name or "Пользователь"
            username = query.from_user.username or "без username"
            # Сообщение админу
            admin_message = (
                "📥 ЗАЯВКА НА ОБЪЕКТ\n\n"
                f"👤 Пользователь: {user_name} (@{username})\n"
                f"🆔 ID: {user_id}\n"
                f"🏠 Объект: {prop['project_name']}\n"                
            )
            if ADMIN_IDS:
                for admin_id in ADMIN_IDS:
                    try:
                        await context.bot.send_message(chat_id=admin_id, text=admin_message)
                    except Exception as e:
                        print(f"Не удалось отправить сообщение админу {admin_id}: {e}")
            await add_request_to_notion(user_name, username, user_id, prop)
            await query.message.reply_text(
                "🧑‍💼 Спасибо! Ваш запрос принят.\n\n"
                "Мы подберём для вас детальную информацию и свяжемся в ближайшее время.",
                reply_markup=get_back_button()
            )
        except Exception as e:
            print(f"Ошибка при отправке заявки: {e}")
            await query.message.reply_text(
                "⚠️ Не удалось отправить заявку. Попробуйте позже.",
                reply_markup=get_back_button()
            )
    elif query.data == "download_pdf":
        is_subscribed = TEST_MODE or await is_user_subscribed(query.from_user.id, context)
        if not is_subscribed:
            keyboard = [
                [InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
                [InlineKeyboardButton("✅ Проверить подписку", callback_data="download_pdf")],
                [InlineKeyboardButton("🔙 Назад в меню", callback_data="menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(
                f"❗️ Для скачивания каталога подпишитесь на наш канал: {CHANNEL_USERNAME}\n\n"
                "После подписки нажмите 'Проверить подписку'",
                reply_markup=reply_markup
            )
            return

        # Сообщение о подготовке каталога
        await query.message.reply_text(
            "⏳ Каталог подготавливается, пожалуйста, подождите...",
            reply_markup=get_back_button()
        )

        try:
            # Если файла нет (например, после деплоя), создаём его
            if not os.path.exists(PDF_PATH):
                properties = await get_properties()
                if not properties:
                    await query.message.reply_text(
                        "❌ В данный момент нет доступных объектов для каталога",
                        reply_markup=get_back_button()
                    )
                    return
                await create_catalog_pdf(properties, PDF_PATH)

            # Отправляем PDF
            with open(PDF_PATH, "rb") as pdf_file:
                await query.message.reply_document(
                    document=pdf_file,
                    filename="Каталог PolarProperty.pdf",
                    caption="📋 Ваш актуальный каталог объектов. По всем вопросам обращайтесь к нам.",
                    reply_markup=get_back_button()
                )
        except Exception as e:
            print(f"❌ Ошибка отправки PDF: {e}")
            await query.message.reply_text(
                "❌ Произошла ошибка при отправке каталога. Попробуйте позже.",
                reply_markup=get_back_button()
            )
        return
    elif query.data == "menu":
        # Главное меню — всегда вызываем start
        try:
            if update.callback_query:
                await update.callback_query.message.delete()
            await start(update, context)
        except BadRequest:
            # await query.message.reply_text("🏠 Главное меню\n\nВыберите действие:")
            await query.message.reply_text("Для выхода в главное меню напишите /start:")
        return
   
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений (заявки и вопросы)"""
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name or "Пользователь"
    username = update.message.from_user.username or "без username"
    state = user_state.get(user_id)

    # --- Интерактивная анкета ---
    if isinstance(state, dict) and state.get("type") == "selection":
        step = state.get("step", 0)
        data = state.get("data", {})
        data[SELECTION_STEPS[step]] = update.message.text
        step += 1

        if step < len(SELECTION_QUESTIONS):
            user_state[user_id] = {"step": step, "data": data, "type": "selection"}
            await update.message.reply_text(
                SELECTION_QUESTIONS[step],
                reply_markup=get_back_button()
            )
        else:
            # Анкета завершена
            user_state[user_id] = None
            # Формируем текст для админа
            msg = (
                "📩 АНКЕТА НА ПОДБОР КВАРТИРЫ\n\n"
                f"👤 Пользователь: {user_name} (@{username})\n"
                f"🆔 ID: {user_id}\n"
                f"1️⃣ Имя: {data.get('name')}\n"
                f"2️⃣ Телефон: {data.get('phone')}\n"
                f"3️⃣ Тип недвижимости: {data.get('type')}\n"
                f"4️⃣ Район/город: {data.get('location')}\n"
                f"5️⃣ Бюджет: {data.get('budget')}\n"
            )
            await update.message.reply_text(
                "✅ Спасибо! Ваша анкета отправлена менеджеру. Мы свяжемся с вами в ближайшее время.",
                reply_markup=get_back_button()
            )
            if ADMIN_IDS:
                try:
                    for admin_id in ADMIN_IDS:
                        await context.bot.send_message(chat_id=admin_id, text=msg)
                except Exception as e:
                    print(f"Не удалось отправить анкету админу: {e}")
            # Добавляем в Notion (новая таблица)
            await add_selection_to_notion(user_name, username, user_id, data)
        return

    
    if state:
        user_state[user_id] = None

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка ошибок"""
    print(f"Exception while handling an update: {context.error}")
    print(f"Traceback: {traceback.format_exc()}")

def format_price(price):
    """Форматирует цену с пробелами между тысячами"""
    if price is None:
        return "—"
    return f"{int(price):,}".replace(",", " ")

def escape_html(text):
    """Экранирует спецсимволы для HTML"""
    return html.escape(str(text))

async def add_request_to_notion(user_name, username, user_id, prop):
    """Добавляет заявку в таблицу Notion"""
    from datetime import datetime
    try:
        notion.pages.create(
            parent={"database_id": NOTION_DATABASE_REQUESTS_ID},  # замените на ID вашей таблицы заявок
            properties={
                "Пользователь": {
                    "title": [{"text": {"content": user_name}}]
                },
                "Username": {
                    "rich_text": [{"text": {"content": username}}]
                },
                "UserID": {
                    "rich_text": [{"text": {"content": str(user_id)}}]
                },
                "Объект": {
                    "rich_text": [{"text": {"content": prop.get('project_name', '')}}]
                },
                "ID объекта": {
                    "rich_text": [{"text": {"content": str(prop.get('id', ''))}}]
                },
                "Источник": {
                    "rich_text": [{"text": {"content": "телеграм бот"}}]
                },
                "Тип сделки": {
                    "rich_text": [{"text": {"content": "Продажа"}}]
                },
                "Дата": {
                    "date": {"start": datetime.now().isoformat()}
                }
            }
        )
        print("✅ Заявка добавлена в Notion")
    except Exception as e:
        print(f"❌ Ошибка добавления заявки в Notion: {e}")

def fix_drive_url(url):
    """
    Преобразует ссылку Google Drive в прямую ссылку для скачивания изображения.
    """
    if not url:
        return url
    # Если ссылка уже правильная, возвращаем как есть
    if "drive.google.com/uc?export=view&id=" in url:
        return url
    # Ищем FILE_ID в ссылке
    match = re.search(r'drive\.google\.com\/file\/d\/([^\/]+)', url)
    if match:
        file_id = match.group(1)
        return f"https://drive.google.com/uc?export=view&id={file_id}"
    return url

def oneline(text):
    """Удаляет переносы строк для использования в pdf.cell"""
    return str(text).replace('\n', ' ').replace('\r', ' ')

def cleanup_temp_files():
    """Очищает временные файлы"""
    import glob
    try:
        # Удаляем временные изображения
        for file in glob.glob("temp_img_*.jpg"):
            os.remove(file)
        # Удаляем старые временные PDF
        for file in glob.glob("catalog_*.pdf"):
            os.remove(file)
    except Exception as e:
        print(f"⚠️ Ошибка очистки временных файлов: {e}")

# 3. Функция для создания PDF


async def create_catalog_pdf(properties, pdf_path):
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.add_font('DejaVu', '', 'fonts/DejaVuSans.ttf')
    pdf.add_font('DejaVu', 'B', 'fonts/DejaVuSans-Bold.ttf')
    pdf.set_font("DejaVu", size=12)
    pdf.cell(200, 10, text="Каталог объектов PolarProperty", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.ln(10)

    for idx, prop in enumerate(properties, 1):
        # Название объекта
        pdf.set_font("DejaVu", 'B', size=12)
        pdf.cell(0, 10, text=f"{idx}. {oneline(prop['project_name'])}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(3)

        # Фото объекта (сразу после названия)
        if prop.get("photo_url"):
            import requests
            try:
                img_data = requests.get(prop["photo_url"], timeout=10).content
                img_path = f"temp_img_{idx}.jpg"
                with open(img_path, "wb") as handler:
                    handler.write(img_data)
                pdf.image(img_path, w=60)
                os.remove(img_path)
                pdf.ln(5)
            except Exception as e:
                print(f"⚠️ Не удалось добавить изображение в PDF: {e}")
                pdf.ln(5)

        # Остальной текст
        pdf.set_font("DejaVu", size=11)
        pdf.cell(0, 8, text=f"Район: {oneline(prop['district'])}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 8, text=f"Статус: {oneline(prop['status'])}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 8, text=f"Застройщик: {oneline(prop['developer'])}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 8, text=f"Срок сдачи: {oneline(prop['enddate'])}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        prices = prop['prices']
        pdf.cell(0, 8, text=f"Цены:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 8, text=f"   - Студия: от {format_price(prices['studio'])} THB", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 8, text=f"   - 1BR: от {format_price(prices['1br'])} THB", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 8, text=f"   - 2BR: от {format_price(prices['2br'])} THB", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 8, text=f"   - 3BR: от {format_price(prices['3br'])} THB", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 8, text=f"   - Пентхаус: от {format_price(prices['penthouse'])} THB", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        # pdf.cell(0, 8, text=f"Условия оплаты: {oneline(prop['payments'])}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        # Используем multi_cell для описания, чтобы поддерживать переносы строк
        comments = str(prop['comments']).replace('\r\n', '\n').replace('\r', '\n')
        pdf.multi_cell(0, 8, text=f"Описание: {comments}")
        pdf.ln(3)

    pdf.output(pdf_path)
# --- Добавьте функцию для добавления анкеты в Notion ---
async def add_selection_to_notion(user_name, username, user_id, data):
    """Добавляет анкету на подбор квартиры в таблицу Notion"""
    from datetime import datetime
    try:
        notion.pages.create(
            parent={"database_id": NOTION_DATABASE_SELECTIONS_ID},  # замените на ID вашей таблицы анкет
            properties={
                "Пользователь": {
                    "title": [{"text": {"content": user_name}}]
                },
                "Username": {
                    "rich_text": [{"text": {"content": username}}]
                },
                "UserID": {
                    "rich_text": [{"text": {"content": str(user_id)}}]
                },
                "Имя": {
                    "rich_text": [{"text": {"content": data.get("name", "")}}]
                },
                "Телефон": {
                    "rich_text": [{"text": {"content": data.get("phone", "")}}]
                },
                "Тип недвижимости": {
                    "rich_text": [{"text": {"content": data.get("type", "")}}]
                },
                "Район/город": {
                    "rich_text": [{"text": {"content": data.get("location", "")}}]
                },
                "Бюджет": {
                    "rich_text": [{"text": {"content": data.get("budget", "")}}]
                },
                "Дата": {
                    "date": {"start": datetime.now().isoformat()}
                }
            }
        )
        print("✅ Анкета добавлена в Notion")
    except Exception as e:
        print(f"❌ Ошибка добавления анкеты в Notion: {e}")
PDF_PATH = "catalog.pdf"

async def scheduled_update_pdf():
    """Обновляет основной PDF каталог (для кеширования)"""
    print("⏳ Обновление PDF каталога...")
    properties = await get_properties()
    if properties:
        try:
            await create_catalog_pdf(properties, PDF_PATH)
            print("✅ PDF каталог обновлён")
        except Exception as e:
            print(f"❌ Ошибка обновления PDF: {e}")
    else:
        print("❌ Нет объектов для формирования PDF")
        
async def on_startup(app):
    print("🚀 Запуск бота...")
    
    # Очищаем старые временные файлы
    cleanup_temp_files()
    
    if not TEST_MODE:
        # Пытаемся создать начальный PDF (не критично если не получится)
        try:
            await scheduled_update_pdf()
        except Exception as e:
            print(f"⚠️ Не удалось создать начальный PDF: {e}")
            
        # Запускаем планировщик для еженедельного обновления
        try:
            scheduler = AsyncIOScheduler(timezone="UTC")
            scheduler.add_job(
                lambda: asyncio.create_task(scheduled_update_pdf()), 
                "cron", 
                day_of_week="mon", 
                hour=10, 
                minute=0
            )
            scheduler.start()
            print("✅ Планировщик запущен")
        except Exception as e:
            print(f"⚠️ Ошибка запуска планировщика: {e}")
    else:
        print("⚠️ Тестовый режим: обновление PDF и планировщик отключены")    
# --- Добавьте состояния и вопросы для анкеты ---
SELECTION_STEPS = [
    "name",
    "phone",
    "type",
    "location",
    "budget"
]
SELECTION_QUESTIONS = [
    "1️⃣ Как вас зовут?",
    "2️⃣ Ваш номер телефона (+ код страны)?",
    "3️⃣ Тип недвижимости: квартира, дом, вилла?",
    "4️⃣ Район или город в Таиланде?",
    "5️⃣ Ваш бюджет?"
]

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).post_init(on_startup).build()
    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    print("✅ Бот запущен")
    app.run_polling()

