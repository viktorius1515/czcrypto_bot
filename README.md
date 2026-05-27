# 🤖 Crypto Signal Bot

Телеграм-бот который собирает рыночные данные и отправляет анализ через Claude 3 раза в день.

## Что собирает
- Цены BTC/ETH (Binance)
- Fear & Greed Index (Alternative.me)
- Фандинг рейты (Binance Futures)
- Open Interest BTC
- BTC Dominance + общая капитализация

## Деплой на Railway

### 1. Загрузи файлы на GitHub
Создай новый репозиторий на github.com и загрузи все три файла:
- `bot.py`
- `requirements.txt`
- `railway.toml`

### 2. Подключи Railway
- Зайди на railway.app
- New Project → Deploy from GitHub repo
- Выбери свой репозиторий

### 3. Добавь переменные окружения
В Railway: Settings → Variables → добавь:

```
ANTHROPIC_API_KEY=sk-ant-...твой ключ...
TELEGRAM_TOKEN=1234567890:ABC...твой токен...
CHAT_ID=123456789
```

### 4. Deploy
Railway автоматически запустит бота.
Первый сигнал придёт сразу при старте.
Далее каждый день в 08:00, 14:00, 20:00 UTC.

## Расписание
- 🌅 08:00 UTC = 11:00 Москва
- 🌞 14:00 UTC = 17:00 Москва  
- 🌆 20:00 UTC = 23:00 Москва

## Стоимость
- Claude API: ~$0.30/месяц
- Railway: бесплатный план
- Все данные: бесплатно
