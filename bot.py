import os
import asyncio
import aiohttp
import anthropic
from datetime import datetime
import schedule
import time
import threading

# ============================================================
# КОНФИГУРАЦИЯ — все значения берутся из переменных окружения
# ============================================================
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# ============================================================
# СБОР ДАННЫХ
# ============================================================

async def get_prices():
    """Цены BTC и ETH с Binance"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbols": '["BTCUSDT","ETHUSDT"]'},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                prices = {item["symbol"]: float(item["price"]) for item in data}
                return {
                    "BTC": prices.get("BTCUSDT", 0),
                    "ETH": prices.get("ETHUSDT", 0)
                }
    except Exception as e:
        return {"BTC": "недоступно", "ETH": "недоступно", "error": str(e)}


async def get_fear_greed():
    """Fear & Greed Index с Alternative.me"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.alternative.me/fng/?limit=1",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                item = data["data"][0]
                return {
                    "value": item["value"],
                    "classification": item["value_classification"]
                }
    except Exception as e:
        return {"value": "недоступно", "classification": "недоступно", "error": str(e)}


async def get_funding_rates():
    """Фандинг рейты с Binance Futures"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://fapi.binance.com/fapi/v1/premiumIndex",
                params={"symbol": "BTCUSDT"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                btc_data = await resp.json()

            async with session.get(
                "https://fapi.binance.com/fapi/v1/premiumIndex",
                params={"symbol": "ETHUSDT"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                eth_data = await resp.json()

            return {
                "BTC_funding": float(btc_data.get("lastFundingRate", 0)) * 100,
                "ETH_funding": float(eth_data.get("lastFundingRate", 0)) * 100,
                "BTC_mark_price": float(btc_data.get("markPrice", 0)),
                "BTC_index_price": float(btc_data.get("indexPrice", 0)),
            }
    except Exception as e:
        return {"BTC_funding": "недоступно", "ETH_funding": "недоступно", "error": str(e)}


async def get_open_interest():
    """Open Interest BTC с Binance Futures"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://fapi.binance.com/fapi/v1/openInterest",
                params={"symbol": "BTCUSDT"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                oi = float(data.get("openInterest", 0))
                price = float(data.get("time", 0))
                return {"BTC_OI": oi}
    except Exception as e:
        return {"BTC_OI": "недоступно", "error": str(e)}


async def get_btc_dominance():
    """BTC доминация с CoinGecko"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.coingecko.com/api/v3/global",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                dominance = data["data"]["market_cap_percentage"].get("btc", 0)
                total_mcap = data["data"]["total_market_cap"].get("usd", 0)
                return {
                    "btc_dominance": round(dominance, 2),
                    "total_market_cap_b": round(total_mcap / 1e9, 0)
                }
    except Exception as e:
        return {"btc_dominance": "недоступно", "error": str(e)}


async def collect_all_data():
    """Собираем все данные параллельно"""
    prices, fear_greed, funding, oi, dominance = await asyncio.gather(
        get_prices(),
        get_fear_greed(),
        get_funding_rates(),
        get_open_interest(),
        get_btc_dominance(),
        return_exceptions=True
    )

    # Если asyncio вернул исключение — заменяем пустым dict
    if isinstance(prices, Exception): prices = {}
    if isinstance(fear_greed, Exception): fear_greed = {}
    if isinstance(funding, Exception): funding = {}
    if isinstance(oi, Exception): oi = {}
    if isinstance(dominance, Exception): dominance = {}

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        "prices": prices,
        "fear_greed": fear_greed,
        "funding": funding,
        "open_interest": oi,
        "dominance": dominance
    }


# ============================================================
# АНАЛИЗ ЧЕРЕЗ CLAUDE
# ============================================================

def analyze_with_claude(market_data: dict) -> str:
    """Отправляем данные в Claude и получаем анализ"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Ты профессиональный криптовалютный трейдер и аналитик. Проанализируй текущие рыночные данные и дай чёткий торговый сигнал.

РЫНОЧНЫЕ ДАННЫЕ ({market_data['timestamp']}):

💰 ЦЕНЫ:
- BTC: ${market_data['prices'].get('BTC', 'н/д'):,.0f}
- ETH: ${market_data['prices'].get('ETH', 'н/д'):,.2f}

😱 FEAR & GREED INDEX:
- Значение: {market_data['fear_greed'].get('value', 'н/д')}/100
- Классификация: {market_data['fear_greed'].get('classification', 'н/д')}

📊 ФАНДИНГ РЕЙТЫ (8ч):
- BTC: {market_data['funding'].get('BTC_funding', 'н/д'):.4f}%
- ETH: {market_data['funding'].get('ETH_funding', 'н/д'):.4f}%

📈 OPEN INTEREST BTC:
- {market_data['open_interest'].get('BTC_OI', 'н/д'):,.0f} BTC

🌍 ДОМИНАЦИЯ:
- BTC Dominance: {market_data['dominance'].get('btc_dominance', 'н/д')}%
- Общая капитализация: ${market_data['dominance'].get('total_market_cap_b', 'н/д'):,.0f}B

ТВОЙ АНАЛИЗ ДОЛЖЕН СОДЕРЖАТЬ:

1. **ОБЩАЯ КАРТИНА** — что сейчас происходит на рынке (2-3 предложения)

2. **КЛЮЧЕВЫЕ СИГНАЛЫ** — что важного говорят данные:
   - Фандинг (положительный = лонги платят = перегрев, отрицательный = шорты платят = страх)
   - Fear & Greed (экстремальная жадность = опасность, экстремальный страх = возможность)
   - Доминация BTC (растёт = рискофф, падает = альтсезон)

3. **ТОРГОВЫЙ СИГНАЛ**: 
   🟢 БЫЧИЙ / 🔴 МЕДВЕЖИЙ / 🟡 НЕЙТРАЛЬНЫЙ
   
4. **КОНКРЕТНЫЙ ПЛАН**:
   - Действие: (держать/покупать/продавать/ждать)
   - Если вход: уровень входа, стоп-лосс, тейк-профит
   - Соотношение риск/прибыль
   
5. **РИСКИ** — что может пойти не так (1-2 пункта)

Пиши чётко, без воды. Используй эмодзи для наглядности. Длина: 250-350 слов."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text


# ============================================================
# ФОРМАТИРОВАНИЕ И ОТПРАВКА В TELEGRAM
# ============================================================

def format_message(market_data: dict, analysis: str) -> str:
    """Форматируем итоговое сообщение для Telegram"""
    btc = market_data['prices'].get('BTC', 0)
    eth = market_data['prices'].get('ETH', 0)
    fg_value = market_data['fear_greed'].get('value', 'н/д')
    fg_class = market_data['fear_greed'].get('classification', 'н/д')
    btc_fund = market_data['funding'].get('BTC_funding', 0)
    eth_fund = market_data['funding'].get('ETH_funding', 0)
    btc_dom = market_data['dominance'].get('btc_dominance', 'н/д')
    total_mcap = market_data['dominance'].get('total_market_cap_b', 'н/д')

    # Эмодзи для фандинга
    def funding_emoji(val):
        if val == 'н/д': return '❓'
        if float(val) > 0.05: return '🔴'
        if float(val) > 0: return '🟡'
        return '🟢'

    msg = f"""━━━━━━━━━━━━━━━━━━━━
🤖 *КРИПТО СИГНАЛ*
📅 {market_data['timestamp']}
━━━━━━━━━━━━━━━━━━━━

📊 *РЫНОЧНЫЕ ДАННЫЕ*
₿ BTC: *${btc:,.0f}*
Ξ ETH: *${eth:,.2f}*
🌍 BTC Dominance: *{btc_dom}%*
💰 Total Market Cap: *${total_mcap:,.0f}B*

😱 *FEAR & GREED INDEX*
Значение: *{fg_value}/100* — {fg_class}

📈 *ФАНДИНГ РЕЙТЫ* (8ч)
BTC: {funding_emoji(btc_fund)} *{btc_fund:.4f}%*
ETH: {funding_emoji(eth_fund)} *{eth_fund:.4f}%*

━━━━━━━━━━━━━━━━━━━━
🧠 *АНАЛИЗ CLAUDE*
━━━━━━━━━━━━━━━━━━━━

{analysis}

━━━━━━━━━━━━━━━━━━━━
⚠️ _Не является финансовым советом. DYOR._"""

    return msg


async def send_telegram_message(text: str):
    """Отправка сообщения в Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            result = await resp.json()
            if not result.get("ok"):
                print(f"Ошибка Telegram: {result}")
            return result


# ============================================================
# ОСНОВНАЯ ФУНКЦИЯ — запуск одного цикла
# ============================================================

async def run_analysis():
    """Собрать данные → проанализировать → отправить"""
    print(f"\n[{datetime.now()}] Запускаю анализ...")

    try:
        # 1. Сбор данных
        print("Собираю рыночные данные...")
        market_data = await collect_all_data()
        print(f"Данные получены: BTC={market_data['prices'].get('BTC', 'н/д')}")

        # 2. Анализ Claude
        print("Отправляю в Claude...")
        analysis = analyze_with_claude(market_data)
        print("Анализ получен")

        # 3. Форматирование
        message = format_message(market_data, analysis)

        # 4. Отправка в Telegram
        print("Отправляю в Telegram...")
        await send_telegram_message(message)
        print("✅ Сообщение отправлено!")

    except Exception as e:
        error_msg = f"❌ Ошибка бота: {str(e)}"
        print(error_msg)
        try:
            await send_telegram_message(f"⚠️ *Ошибка бота*\n`{str(e)}`")
        except:
            pass


def run_async_analysis():
    """Обёртка для запуска async из schedule"""
    asyncio.run(run_analysis())


# ============================================================
# ПЛАНИРОВЩИК — 3 раза в день
# ============================================================

def start_scheduler():
    # Анализ в 08:00, 14:00 и 20:00 UTC
    schedule.every().day.at("08:00").do(run_async_analysis)
    schedule.every().day.at("14:00").do(run_async_analysis)
    schedule.every().day.at("20:00").do(run_async_analysis)

    print("✅ Планировщик запущен. Сигналы в 08:00, 14:00, 20:00 UTC")
    print("Следующий запуск:", schedule.next_run())

    while True:
        schedule.run_pending()
        time.sleep(30)


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":
    print("🚀 Crypto Signal Bot запускается...")
    print(f"ANTHROPIC_API_KEY: {'✅' if ANTHROPIC_API_KEY else '❌ НЕТ'}")
    print(f"TELEGRAM_TOKEN: {'✅' if TELEGRAM_TOKEN else '❌ НЕТ'}")
    print(f"CHAT_ID: {'✅' if CHAT_ID else '❌ НЕТ'}")

    if not all([ANTHROPIC_API_KEY, TELEGRAM_TOKEN, CHAT_ID]):
        print("\n❌ Не все переменные окружения установлены!")
        print("Нужно: ANTHROPIC_API_KEY, TELEGRAM_TOKEN, CHAT_ID")
        exit(1)

    # Первый запуск сразу при старте
    print("\n📊 Запускаю первый анализ немедленно...")
    asyncio.run(run_analysis())

    # Затем по расписанию
    start_scheduler()
