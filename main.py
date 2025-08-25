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

# --- Конфигурация извлечения внешнего ID ---
CANDIDATE_EXT_ID_KEYS = [
    'id','ID','Id','№','No','Номер','Номер объекта','ID объекта','Id объекта','Id Объекта',
    'ID обьекта','Id обьекта','Object ID','ObjectId','External ID','External Id'
]

def format_notion_property(pv: dict) -> str:
    """Единообразно форматирует значение свойства Notion согласно типу.
    Поддержка: title, rich_text, select, multi_select, number, url, email, phone_number,
    unique_id, formula, rollup, date. Не генерирует новые значения.
    """
    if not pv or not isinstance(pv, dict):
        return ''
    ptype = pv.get('type')
    try:
        if ptype == 'title':
            return ''.join([(t.get('plain_text') or t.get('text', {}).get('content','') or '') for t in pv.get('title', [])]).strip()
        if ptype == 'rich_text':
            return ''.join([(t.get('plain_text') or t.get('text', {}).get('content','') or '') for t in pv.get('rich_text', [])]).strip()
        if ptype == 'select':
            return (pv.get('select') or {}).get('name','') or ''
        if ptype == 'multi_select':
            return ', '.join([o.get('name','') for o in pv.get('multi_select', []) if o.get('name')]).strip()
        if ptype == 'number':
            return '' if pv.get('number') is None else str(pv.get('number'))
        if ptype in ('url','email','phone_number'):
            return pv.get(ptype) or ''
        if ptype == 'unique_id':
            u = pv.get('unique_id') or {}
            num = u.get('number')
            if num is None:
                return ''
            prefix = u.get('prefix') or ''
            return f"{prefix}-{num}" if prefix else str(num)
        if ptype == 'formula':
            f = pv.get('formula') or {}
            ftype = f.get('type')
            if ftype == 'string':
                return f.get('string') or ''
            if ftype == 'number':
                return '' if f.get('number') is None else str(f.get('number'))
            if ftype == 'boolean':
                return '' if f.get('boolean') is None else ('true' if f.get('boolean') else 'false')
            if ftype == 'date':
                d = f.get('date') or {}
                return d.get('start') or ''
            return ''
        if ptype == 'rollup':
            r = pv.get('rollup') or {}
            rtype = r.get('type')
            if rtype == 'number':
                return '' if r.get('number') is None else str(r.get('number'))
            if rtype == 'date':
                d = r.get('date') or {}
                return d.get('start') or ''
            if rtype == 'array':
                parts = []
                for inner in r.get('array', []):
                    parts.append(format_notion_property(inner))
                return ', '.join([p for p in parts if p.strip()]).strip()
            return ''
        if ptype == 'date':
            d = pv.get('date') or {}
            return d.get('start') or ''
        # fallback попытка plain_text
        inner = pv.get(ptype)
        if isinstance(inner, dict):
            if isinstance(inner.get('plain_text'), str):
                return inner.get('plain_text')
            if inner.get('text') and isinstance(inner.get('text'), dict):
                return inner.get('text', {}).get('content','') or ''
        return ''
    except Exception:
        return ''

def extract_external_id(page_properties: dict) -> str:
    """Извлекает внешний extId только если он реально присутствует в одном из кандидатных полей.
    Алгоритм: прямой проход -> lowercase fallback. Возвращает '' если не найдено.
    """
    if not page_properties or not isinstance(page_properties, dict):
        return ''
    lower_map = {k.lower(): k for k in page_properties.keys()}

    # Прямой проход
    for cand in CANDIDATE_EXT_ID_KEYS:
        if cand in page_properties:
            val = format_notion_property(page_properties[cand]).strip()
            if val:
                return val
    # Fallback через lower_map
    for cand in CANDIDATE_EXT_ID_KEYS:
        key = lower_map.get(cand.lower())
        if key:
            val = format_notion_property(page_properties[key]).strip()
            if val:
                return val
    return ''

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню"""
    photo_url = "https://drive.google.com/uc?export=view&id=1pQQvZyx_th1rUK6dbyhvrS1P03S0Uk8W"
    text = (
        " Добро пожаловать в PolarProperty Asia! \n\n"
        "🏝 Мы помогаем купить или арендовать недвижимость в Паттайе и по всему Таиланду.\n\n"
        "💎 Только проверенные объекты и официальные цены от застройщиков.  \n\n"
        "💬 Консультация — бесплатно.\n\n"
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
    """Получает объекты из Notion и извлекает внешний extId. Не генерирует ID искусственно."""
    try:
        response = notion.databases.query(database_id=NOTION_DATABASE_OBJECTS_ID)
        results = response.get("results", [])
        if not results:
            print("⚠️ База данных пуста")
            return None
        properties = []
        for item in results:
            try:
                props = item.get('properties', {})
                # Основное имя проекта
                title_prop = props.get('Название проекта') or props.get('Название') or props.get('Title')
                project_name = format_notion_property(title_prop) or 'Без названия'
                status = (props.get('Статус', {}) or {}).get('select', {}).get('name', 'Не указано')
                district = (props.get('Район', {}) or {}).get('select', {}).get('name', 'Не указано')
                developer = ''.join([t.get('text', {}).get('content','') for t in (props.get('Застройщик', {}) or {}).get('rich_text', [])]) or 'Не указано'
                enddate = (props.get('Срок сдачи', {}) or {}).get('number', 'Не указано')
                status_lower = (status or '').lower()
                if any(k in status_lower for k in ("сдан","сдача","готово","completed","ready")):
                    payments = 'по запросу'
                else:
                    payments = 'рассрочка до конца строительства'
                comments = ''.join([t.get('text', {}).get('content','') for t in (props.get('Описание', {}) or {}).get('rich_text', [])]) or 'Не указано'
                prices = {
                    'studio': (props.get('Студия (THB)', {}) or {}).get('number'),
                    '1br': (props.get('1BR (THB)', {}) or {}).get('number'),
                    '2br': (props.get('2BR (THB)', {}) or {}).get('number'),
                    '3br': (props.get('3BR (THB)', {}) or {}).get('number'),
                    'penthouse': (props.get('Пентхаус (THB)', {}) or {}).get('number')
                }

                # Фото: берём только Google Drive external-ссылки, Notion-uploaded игнорируем
                photo_url = None
                photo_field = (props.get('Фото', {}) or {}).get('files', [])
                if photo_field:
                    # приоритет — external ссылки Drive
                    for f in photo_field:
                        url = (f.get('external') or {}).get('url')
                        if url and is_drive_url(url):
                            photo_url = fix_drive_url(url)
                            break
                    # если не нашли среди external, можно проверить 'file' только если это Drive (обычно нет)
                    if not photo_url:
                        for f in photo_field:
                            url = (f.get('file') or {}).get('url')
                            if url and is_drive_url(url):
                                photo_url = fix_drive_url(url)
                                break

                ext_id = extract_external_id(props)
                if ext_id:
                    print("Parsed extId", item.get('id'), project_name, ext_id)
                else:
                    print("ID not found", item.get('id'), list(props.keys()))
                properties.append({
                    'project_name': project_name,
                    'status': status,
                    'district': district,
                    'prices': prices,
                    'developer': developer,
                    'enddate': enddate,
                    'payments': payments,
                    'comments': comments,
                    'photo_url': photo_url,  # только Drive или None
                    'extId': ext_id,
                    'page_id': item.get('id'),
                    'raw': item
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
    # Ответ на callback: безопасно игнорируем устаревшие/недействительные callback'ы
    try:
        await query.answer()
    except BadRequest as e:
        err = str(e)
        if any(x in err for x in ("Query is too old","query id is invalid","response timeout")):
            print(f"⚠️ Callback expired or invalid: {e}")
        else:
            raise

    if query.data == "buy_menu":
        keyboard = [
            [InlineKeyboardButton("📂 Список объектов", callback_data="catalog")],
            [InlineKeyboardButton("📥 Скачать каталог PDF", callback_data="download_pdf")],
            [InlineKeyboardButton("📩 Получить консультацию", callback_data="selection")],
            [InlineKeyboardButton("🔙 Назад в меню", callback_data="menu")]
        ]
        await query.message.reply_text("🏠 Покупка недвижимости\n\nВыберите, что вас интересует 👇", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    elif query.data == "rent_menu":
       
        contact_text = (
            "👋 По всем вопросам по поводу аренды напишите нашим менеджерам:\n\n"
            "👩‍💼 Любовь\n"
            f"✈️  Tg: @lyubov_danilove\n"
            f"🇷🇺 <a href=\"https://wa.me/79644229573\">+7 964 422 95 73 (WhatsApp)</a>\n"
            f"🇹🇭  <a href=\"https://wa.me/66968300106\">+66 96 830 01 06 (WhatsApp)</a>\n\n"
            "👨‍💼 Павел\n"
            f"✈️  Tg: @Pash_Danilov\n"
            f"🇹🇭  <a href=\"https://wa.me/66838089908\">+66 83 808 9908 (WhatsApp)</a>\n\n"
            "👩‍💼 Надежда \n"
            f"✈️  Tg: @mandarinka_nadya\n"
            f"🇷🇺 <a href=\"https://wa.me/79241713616\">+7 924 171 36 16 (WhatsApp)</a>\n\n"    
            "👨‍💼 Иван \n"
            f"✈️  Tg: @Sleptsov_Ivan\n"
            f"🇷🇺 <a href=\"https://wa.me/79143083827\">+7 914 308 38 27 (WhatsApp)</a>\n"
            
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
            "👨‍💼 Павел\n"
            f"✈️  Tg: @Pash_Danilov\n"
            f"🇹🇭  <a href=\"https://wa.me/66838089908\">+66 83 808 9908 (WhatsApp)</a>\n\n"
            "👩‍💼 Надежда \n"
            f"✈️  Tg: @mandarinka_nadya\n"
            f"🇷🇺 <a href=\"https://wa.me/79241713616\">+7 924 171 36 16 (WhatsApp)</a>\n\n"    
            "👨‍💼 Иван \n"
            f"✈️  Tg: @Sleptsov_Ivan\n"
            f"🇷🇺 <a href=\"https://wa.me/79143083827\">+7 914 308 38 27 (WhatsApp)</a>\n"           
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
                if prop.get('extId'):
                    short_text += f"\n🔖 ID: {escape_html(prop['extId'])}"
                reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔎 Подробнее", callback_data=f"object_{idx}")]])
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
            nav_buttons = [InlineKeyboardButton("🔙 Назад в меню", callback_data="menu")]
            if end < total:
                nav_buttons.append(InlineKeyboardButton("➡️ Следующие", callback_data=f"catalog_{end}"))
            await query.message.reply_text(
                f"Показаны объекты {page+1}-{end} из {total}.",
                reply_markup=InlineKeyboardMarkup([nav_buttons])
            )
        else:
            keyboard = [
                [InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
                [InlineKeyboardButton("✅ Проверить подписку", callback_data="catalog_0")],
                [InlineKeyboardButton("🔙 Назад в меню", callback_data="menu")]
            ]
            await query.message.reply_text(
                f"❗️ Для получения каталога подпишитесь на наш канал: {CHANNEL_USERNAME}\n\n"
                "После подписки нажмите 'Проверить подписку'",
                reply_markup=InlineKeyboardMarkup(keyboard)
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
        )
        if prop.get('extId'):
            detail_text += f"🔖 ID: {escape_html(prop['extId'])}\n"
        detail_text += (
            f"💰 Цены:\n"
            f"   - Студия: от {escape_html(format_price(prices['studio']))} THB\n"
            f"   - 1BR: от {escape_html(format_price(prices['1br']))} THB\n"
            f"   - 2BR: от {escape_html(format_price(prices['2br']))} THB\n"
            f"   - 3BR: от {escape_html(format_price(prices['3br']))} THB\n"
            f"   - Пентхаус: от {escape_html(format_price(prices['penthouse']))} THB\n"
            f"💳 Условия оплаты: {escape_html(prop.get('payments','Не указано'))}\n"
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
                f"🏠 Объект: {prop.get('project_name')}\n"
                f"🔖 ID объекта: {prop.get('extId') or '(не указан)'}\n"
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
            await query.message.reply_text(
                f"❗️ Для скачивания каталога подпишитесь на наш канал: {CHANNEL_USERNAME}\n\n"
                "После подписки нажмите 'Проверить подписку'",
                reply_markup=InlineKeyboardMarkup(keyboard)
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

    if isinstance(state, dict) and state.get("type") == "selection":
        step = state.get("step", 0)
        data = state.get("data", {})
        current_key = SELECTION_STEPS[step]
        user_text = (update.message.text or '').strip()

        # Проверка номера телефона на соответствующем шаге
        if current_key == 'phone':
            normalized = validate_and_format_phone(user_text)
            if not normalized:
                await update.message.reply_text(
                    "⚠️ Похоже, номер некорректен. Введите номер в международном формате, например: +79123456789 или +66968300106",
                    reply_markup=get_back_button()
                )
                return  # остаёмся на том же шаге
            data['phone'] = normalized
        else:
            data[current_key] = user_text

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
                "📩 Запрос консультации\n\n"
                f"👤 Пользователь: {user_name} (@{username})\n"
                f"🆔 ID: {user_id}\n"
                f"1️⃣ Имя: {data.get('name')}\n"
                f"2️⃣ Телефон: {data.get('phone')}\n"
            )
            await update.message.reply_text(
                "✅ Мы получили ваш запрос на консультацию. Мы скоро с вами свяжемся.",
                reply_markup=get_back_button()
            )
            if ADMIN_IDS:
                try:
                    for admin_id in ADMIN_IDS:
                        await context.bot.send_message(chat_id=admin_id, text=msg)
                except Exception as e:
                    print(f"Не удалось отправить анкету админу: {e}")
            await add_selection_to_notion(user_name, username, user_id, data)
        return

    # Если было состояние — очищаем его
    if state:
        user_state[user_id] = None
        return

    # --- Обработка произвольного текста, когда бот не ожидает ввода ---
    # Если пользователь просто пишет текст вне логики бота, даём вежливую подсказку
    try:
        await update.message.reply_text(
            "Пожалуйста, не отправляйте произвольный текст. Используйте меню или /start.",
            reply_markup=get_back_button()
        )
    except Exception as e:
        print(f"⚠️ Не удалось отправить подсказку пользователю {user_id}: {e}")
    return

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

# Валидация телефона: принимает международный формат с "+", допускает пробелы/скобки/дефисы, нормализует к "+<digits>"
def validate_and_format_phone(raw):
    try:
        s = str(raw or '').strip()
        # Подсчитываем цифры и нормализуем
        digits = ''.join(ch for ch in s if ch.isdigit())
        has_plus = s.startswith('+')
        if has_plus:
            # + и 8..15 цифр по E.164
            if 8 <= len(digits) <= 15:
                return '+' + digits
            return None
        else:
            # Без "+" допускаем 10..15 цифр, нормализуем, добавив "+"
            if 10 <= len(digits) <= 15:
                return '+' + digits
            return None
    except Exception:
        return None

async def add_request_to_notion(user_name, username, user_id, prop):
    """Добавляет заявку в таблицу Notion. Использует видимый ID объекта (SALE-1 и т.п.) если он есть."""
    from datetime import datetime
    try:
        ext_id = prop.get('extId') or ''
        notion.pages.create(
            parent={"database_id": NOTION_DATABASE_REQUESTS_ID},
            properties={
                "Пользователь": {"title": [{"text": {"content": user_name}}]},
                "Username": {"rich_text": [{"text": {"content": username}}]},
                "UserID": {"rich_text": [{"text": {"content": str(user_id)}}]},
                "Объект": {"rich_text": [{"text": {"content": prop.get('project_name','')}}]},
                "ID объекта": {"rich_text": [{"text": {"content": ext_id}}]},
                "Источник": {"rich_text": [{"text": {"content": "телеграм бот"}}]},
                "Тип сделки": {"rich_text": [{"text": {"content": "Продажа"}}]},
                "Дата": {"date": {"start": datetime.now().isoformat()}}
            }
        )
        print(f"✅ Заявка добавлена в Notion (extId='{ext_id}')")
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

def is_drive_url(url: str) -> bool:
    """Проверяет, что ссылка ведёт на Google Drive."""
    return isinstance(url, str) and "drive.google.com" in url

# Приводит многострочный текст к одной строке для pdf.cell
def oneline(text):
    return str(text).replace('\n', ' ').replace('\r', ' ')

async def create_catalog_pdf(properties, pdf_path):
    from fpdf import FPDF
    import os

    # Класс PDF: убираем логотип из футера
    class CatalogPDF(FPDF):
        def __init__(self, *args, **kwargs):
            self.logo_path = kwargs.pop('logo_path', None)
            super().__init__(*args, **kwargs)
        def footer(self):
            # Логотип во футере отключён по требованию
            pass

    tmp_pages_path = pdf_path + ".tmp_pages.pdf"
    cover_path = "cover.pdf"
    logo_path = "logo_black.png"

    pdf = CatalogPDF(logo_path=logo_path)
    pdf.add_font('DejaVu', '', 'fonts/DejaVuSans.ttf')
    pdf.add_font('DejaVu', 'B', 'fonts/DejaVuSans-Bold.ttf')

    LABEL_WIDTH = 40  # ширина ячейки для метки

    # Дата формирования каталога для заголовка
    header_date = datetime.datetime.now().strftime("%d.%m.%Y")

    def add_field(label, value):
        pdf.set_font('DejaVu', 'B', 11)
        pdf.cell(LABEL_WIDTH, 8, f"{label}:", border=0)
        pdf.set_font('DejaVu', '', 11)
        pdf.cell(0, 8, oneline(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    for idx, prop in enumerate(properties, 1):
        pdf.add_page()
        pdf.set_auto_page_break(True, margin=15)

        # Верхний логотип по центру (кроме обложки, она отдельным файлом)
        if os.path.exists(logo_path):
            try:
                logo_w = 130  # мм: увеличенный размер по требованию
                logo_h_est = 28  # мм: ориентировочная высота для расчёта отступа под 130 мм ширину
                x = (pdf.w - logo_w) / 2
                # Поднимаем лого на 20 мм выше стандартного верхнего отступа (без ограничения по границе страницы)
                y = pdf.t_margin - 20
                pdf.image(logo_path, x=x, y=y, w=logo_w)  # высоту не задаём — сохраняем пропорции
                # Убираем прежнюю привязку позиции к высоте лого
                # (заголовок будет привязан к фиксированным 42 мм от верха страницы)
            except Exception:
                # если не удалось отрисовать, просто отступ сверху
                pdf.set_y(pdf.t_margin + 20)
        else:
            pdf.set_y(pdf.t_margin + 2)

        # Фиксируем заголовок на 42 мм от верхнего края страницы
        pdf.set_xy(pdf.l_margin, 42)

        # Заголовок каталога с датой (без бренда, он на логотипе)
        pdf.set_font("DejaVu", 'B', size=12)
        pdf.cell(200, 10, text=f"Каталог объектов — {header_date}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        pdf.ln(6)

        # Название проекта
        pdf.set_font("DejaVu", 'B', size=12)
        title_line = f"{idx}. {oneline(prop.get('project_name',''))}"
        pdf.cell(0, 10, text=title_line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if prop.get('extId'):
            pdf.set_font('DejaVu', '', 9)
            pdf.cell(0, 6, text=f"ID: {oneline(prop['extId'])}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(1)
        else:
            pdf.ln(3)

        # Фото
        if prop.get("photo_url"):
            import requests
            try:
                img_data = requests.get(prop["photo_url"], timeout=10).content
                img_path = f"temp_img_{idx}.jpg"
                with open(img_path, "wb") as handler:
                    handler.write(img_data)
                try:
                    pdf.image(img_path, w=60)
                except Exception:
                    pass
                os.remove(img_path)
                pdf.ln(5)
            except Exception as e:
                print(f"⚠️ Не удалось добавить изображение в PDF: {e}")
                pdf.ln(5)

        # Поля с жирными метками
        add_field("Район", prop.get('district','Не указано'))
        add_field("Статус", prop.get('status','Не указано'))
        add_field("Застройщик", prop.get('developer','Не указано'))
        add_field("Срок сдачи", prop.get('enddate','Не указано'))

        prices = prop.get('prices', {})
        pdf.set_font('DejaVu', 'B', 11)
        pdf.cell(0, 8, "Цены:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font('DejaVu', '', 11)
        pdf.cell(0, 8, text=f"   ●  Студия: от {format_price(prices.get('studio'))} THB", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 8, text=f"   ●  1BR: от {format_price(prices.get('1br'))} THB", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 8, text=f"   ●  2BR: от {format_price(prices.get('2br'))} THB", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 8, text=f"   ●  3BR: от {format_price(prices.get('3br'))} THB", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 8, text=f"   ●  Пентхаус: от {format_price(prices.get('penthouse'))} THB", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        add_field("Условия оплаты", prop.get('payments','Не указано'))

        pdf.ln(2)
        comments = str(prop.get('comments','')).replace('\r\n', '\n').replace('\r', '\n')
        pdf.set_font('DejaVu', 'B', 11)
        pdf.cell(0, 8, "Описание:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font('DejaVu', '', 11)
        pdf.multi_cell(0, 8, comments)

    # Сохраняем временный PDF со страницами каталога
    try:
        pdf.output(tmp_pages_path)
    except Exception as e:
        print(f"❌ Ошибка генерации PDF страниц каталога: {e}")
        return

    # Объединяем: обложка (первая страница cover.pdf) + сгенерированные страницы
    try:
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter()
        if os.path.exists(cover_path):
            try:
                cover_reader = PdfReader(cover_path)
                if len(cover_reader.pages) > 0:
                    writer.add_page(cover_reader.pages[0])
            except Exception as e:
                print(f"⚠️ Не удалось прочитать cover.pdf: {e}")
        else:
            print("⚠️ Обложка cover.pdf не найдена — формируем каталог без неё")

        try:
            gen_reader = PdfReader(tmp_pages_path)
            for p in gen_reader.pages:
                writer.add_page(p)
        except Exception as e:
            print(f"❌ Ошибка чтения временных страниц каталога: {e}")
            return

        with open(pdf_path, 'wb') as out_f:
            writer.write(out_f)
    except Exception as e:
        print(f"❌ Ошибка объединения обложки и каталога: {e}")
        # Фолбэк: копируем сгенерированные страницы как итоговый PDF
        try:
            import shutil
            if os.path.exists(tmp_pages_path):
                shutil.copyfile(tmp_pages_path, pdf_path)
        except Exception as ee:
            print(f"❌ Резервная запись каталога без обложки не удалась: {ee}")
    finally:
        try:
            if os.path.exists(tmp_pages_path):
                os.remove(tmp_pages_path)
        except Exception:
            pass
# --- Добавьте функцию для добавления анкеты в Notion ---
async def add_selection_to_notion(user_name, username, user_id, data):
    """Добавляет запрос консультации (только имя и телефон) в таблицу Notion"""
    from datetime import datetime
    try:
        notion.pages.create(
            parent={"database_id": NOTION_DATABASE_SELECTIONS_ID},
            properties={
                "Пользователь": {"title": [{"text": {"content": user_name}}]},
                "Username": {"rich_text": [{"text": {"content": username}}]},
                "UserID": {"rich_text": [{"text": {"content": str(user_id)}}]},
                "Имя": {"rich_text": [{"text": {"content": data.get('name','')}}]},
                "Телефон": {"rich_text": [{"text": {"content": data.get('phone','')}}]},
                "Дата": {"date": {"start": datetime.now().isoformat()}}
            }
        )
        print("✅ Запрос консультации добавлен в Notion")
    except Exception as e:
        print(f"❌ Ошибка добавления запроса консультации в Notion: {e}")
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
# Очистка временных файлов (вызывается при старте)
def cleanup_temp_files():
    import glob
    try:
        for pattern in ("temp_img_*.jpg", "catalog_*.pdf", "*.tmp_pages.pdf"):
            for file in glob.glob(pattern):
                try:
                    os.remove(file)
                except Exception:
                    pass
    except Exception as e:
        print(f"⚠️ Ошибка очистки временных файлов: {e}")
# --- Добавьте состояния и вопросы для анкеты ---
SELECTION_STEPS = [
    "name",
    "phone"
]
SELECTION_QUESTIONS = [
    "1️⃣ Как вас зовут?",
    "2️⃣ Ваш номер телефона (+ код страны)?"
]

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).post_init(on_startup).build()
    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    print("✅ Бот запущен")
    app.run_polling()

