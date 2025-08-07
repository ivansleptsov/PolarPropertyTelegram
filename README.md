# PolarProperty Telegram Bot

Бот для продажи недвижимости в Таиланде с интеграцией Notion API.

## Структура проекта

```
polarpropert bot/
├── fonts/              # Шрифты для PDF генерации
│   ├── DejaVuSans.ttf
│   ├── DejaVuSans-Bold.ttf
│   └── ...
├── main.py            # Основной файл бота
├── requirements.txt   # Зависимости Python
├── .env              # Переменные окружения
├── README.md         # Документация
└── catalog.pdf       # Генерируемый каталог
```

## Установка

1. **Установите Python 3.8+**

2. **Установите зависимости:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Настройте переменные окружения:**
   - Скопируйте `.env.example` в `.env`
   - Заполните все необходимые переменные:
     - `TELEGRAM_BOT_TOKEN` - токен бота от @BotFather
     - `NOTION_TOKEN` - токен Notion API
     - `NOTION_DATABASE_OBJECTS_ID` - ID базы объектов в Notion
     - `NOTION_DATABASE_REQUESTS_ID` - ID базы заявок в Notion
     - `NOTION_DATABASE_SELECTIONS_ID` - ID базы анкет в Notion
     - `ADMIN_IDS` - ID администраторов через запятую

4. **Структура базы данных Notion:**

   ### База объектов (NOTION_DATABASE_OBJECTS_ID):
   - Название проекта (Title)
   - Статус (Select)
   - Район (Select)
   - Застройщик (Rich Text)
   - Срок сдачи (Number)
   - Условия оплаты (Rich Text)
   - Описание (Rich Text)
   - Студия (THB) (Number)
   - 1BR (THB) (Number)
   - 2BR (THB) (Number)
   - 3BR (THB) (Number)
   - Пентхаус (THB) (Number)
   - Фото (Files)

   ### База заявок (NOTION_DATABASE_REQUESTS_ID):
   - Пользователь (Title)
   - Username (Rich Text)
   - UserID (Rich Text)
   - Объект (Rich Text)
   - Дата (Date)

   ### База анкет (NOTION_DATABASE_SELECTIONS_ID):
   - Пользователь (Title)
   - Username (Rich Text)
   - UserID (Rich Text)
   - Имя (Rich Text)
   - Телефон (Rich Text)
   - Тип недвижимости (Rich Text)
   - Район/город (Rich Text)
   - Бюджет (Rich Text)
   - Дата (Date)

## Запуск

```bash
python main.py
```

## Функциональность

- 🏠 Каталог объектов недвижимости
- 📥 Генерация PDF каталога
- 📩 Анкета подбора квартир
- 💬 Контакты менеджеров
- 🔐 Проверка подписки на канал
- 📊 Автоматическое сохранение заявок в Notion

## Настройки

- `TEST_MODE = True` - отключает проверку подписки и автоматическое обновление PDF
- `PAGE_SIZE = 5` - количество объектов на страницу в каталоге
- `CHANNEL_USERNAME = "@PolarProperty"` - канал для проверки подписки

## Деплой на Railway

### Особенности работы в облаке:

1. **PDF генерация:** Каталоги генерируются динамически при каждом запросе пользователя
2. **Файловая система:** Временные файлы автоматически очищаются при запуске
3. **Планировщик:** Еженедельное обновление кеша PDF (понедельник, 10:00 UTC)

### Настройка переменных окружения в Railway:

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
NOTION_TOKEN=your_notion_token
NOTION_DATABASE_OBJECTS_ID=your_objects_db_id
NOTION_DATABASE_REQUESTS_ID=your_requests_db_id
NOTION_DATABASE_SELECTIONS_ID=your_selections_db_id
ADMIN_IDS=123456789,987654321
```

### Для продакшена установите:
```python
TEST_MODE = False  # в main.py
```

## Режим разработки

Для тестирования установите `TEST_MODE = True` в main.py. Это отключит:
- Проверку подписки на канал
- Автоматическое обновление PDF каталога при запуске
