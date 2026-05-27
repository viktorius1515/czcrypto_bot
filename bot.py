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
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbols": '["BTCUSDT","ETHUSDT"]'},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                prices = {item["symbol"]: float(item["price"]) for item in data}
                return {"BTC": prices.get("BTCUSDT", 0), "ETH": prices.get("ETHUSDT", 0)}
    except Exception as e:
        return {"BTC": "н/д", "ETH": "н/д", "error": str(e)}


async def get_fear_greed():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.alternative.me/fng/?limit=1",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                item = data["data"][0]
                return {"value": item["value"], "classification": item["value_classification"]}
    except Exception as e:
        return {"value": "н/д", "classification": "н/д", "error": str(e)}


async def get_funding_rates():
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
            }
    except Exception as e:
        return {"BTC_funding": "н/д", "ETH_funding": "н/д", "error": str(e)}


async def get_btc_dominance():
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
        return {"btc_dominance": "н/д", "total_market_cap_b": "н/д", "error": str(e)}


async def collect_all_data():
    prices, fear_greed, funding, dominance = await asyncio.gather(
        get_prices(), get_fear_greed(), get_funding_rates(), get_btc_dominance(),
        return_exceptions=True
    )
    if isinstance(prices, Exception): prices = {}
    if isinstance(fear_greed, Exception): fear_greed = {}
    if isinstance(funding, Exception): funding = {}
    if isinstance(dominance, Exception): dominance = {}
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        "prices": prices,
        "fear_greed": fear_greed,
        "funding": funding,
        "dominance": dominance
    }


# ============================================================
# АНАЛИЗ ЧЕРЕЗ CLAUDE
# ============================================================

def analyze_with_claude(market_data: dict) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""Ты профессиональный криптовалютный трейдер и аналитик. Проанализируй текущие рыночные данные и дай чёткий торговый сигнал.

РЫНОЧНЫЕ ДАННЫЕ ({market_data['timestamp']}):

💰 ЦЕНЫ:
- BTC: ${market_data['prices'].get('BTC', 'н/д')}
- ETH: ${market_data['prices'].get('ETH', 'н/д')}

😱 FEAR & GREED INDEX:
- Значение: {market_data['fear_greed'].get('value', 'н/д')}/100
- Классификация: {market_data['fear_greed'].get('classification', 'н/д')}

📊 ФАНДИНГ РЕЙТЫ (8ч):
- BTC: {market_data['funding'].get('BTC_funding', 'н/д')}%
- ETH: {market_data['funding'].get('ETH_funding', 'н/д')}%

🌍 ДОМИНАЦИЯ:
- BTC Dominance: {market_data['dominance'].get('btc_dominance', 'н/д')}%
- Общая капитализация: ${market_data['dominance'].get('total_market_cap_b', 'н/д')}B

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
# ФОРМАТИРОВАНИЕ — безопасное
# ============================================================

def safe_price(val, decimals=0):
    try:
        return f"${float(val):,.{decimals}f}"
    except (TypeError, ValueError):
        return "н/д"

def safe_pct(val, decimals=4):
    try:
        return f"{float(val):.{decimals}f}%"
    except (TypeError, ValueError):
        return "н/д"

def safe_num(val, decimals=2):
    try:
        return f"{float(val):.{decimals}f}"
    except (TypeError, ValueError):
        return "н/д"

def funding_emoji(val):
    try:
        v = float(val)
        if v > 0.05: return '🔴'
        if v > 0: return '🟡'
        return '🟢'
    except (TypeError, ValueError):
        return '❓'

def format_message(market_data: dict, analysis: str) -> str:
    btc = market_data['prices'].get('BTC', 'н/д')
    eth = market_data['prices'].get('ETH', 'н/д')
    fg_value = market_data['fear_greed'].get('value', 'н/д')
    fg_class = market_data['fear_greed'].get('classification', 'н/д')
    btc_fund = market_data['funding'].get('BTC_funding', 'н/д')
    eth_fund = market_data['funding'].get('ETH_funding', 'н/д')
    btc_dom = market_data['dominance'].get('btc_dominance', 'н/д')
    total_mcap = market_data['dominance'].get('total_market_cap_b', 'н/д')

    msg = f"""━━━━━━━━━━━━━━━━━━━━
🤖 *КРИПТО СИГНАЛ*
📅 {market_data['timestamp']}
━━━━━━━━━━━━━━━━━━━━

📊 *РЫНОЧНЫЕ ДАННЫЕ*
₿ BTC: *{safe_price(btc)}*
Ξ ETH: *{safe_price(eth, 2)}*
🌍 BTC Dominance: *{safe_num(btc_dom)}%*
💰 Total Market Cap: *{safe_price(total_mcap)}B*

😱 *FEAR & GREED INDEX*
Значение: *{fg_value}/100* — {fg_class}

📈 *ФАНДИНГ РЕЙТЫ* (8ч)
BTC: {funding_emoji(btc_fund)} *{safe_pct(btc_fund)}*
ETH: {funding_emoji(eth_fund)} *{safe_pct(eth_fund)}*

━━━━━━━━━━━━━━━━━━━━
🧠 *АНАЛИЗ CLAUDE*
━━━━━━━━━━━━━━━━━━━━

{analysis}

━━━━━━━━━━━━━━━━━━━━
⚠️ _Не является финансовым советом. DYOR._"""
    return msg


# ============================================================
# ОТПРАВКА В TELEGRAM
# ============================================================

async def send_telegram_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            result = await resp.json()
            if not result.get("ok"):
                print(f"Ошибка Telegram: {result}")
            return result


# ============================================================
# ОСНОВНОЙ ЦИКЛ
# ============================================================

async def run_analysis():
    print(f"\n[{datetime.now()}] Запускаю анализ...")
    try:
        market_data = await collect_all_data()
        print(f"Данные: BTC={market_data['prices'].get('BTC', 'н/д')}")
        analysis = analyze_with_claude(market_data)
        message = format_message(market_data, analysis)
        await send_telegram_message(message)
        print("✅ Отправлено!")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        try:
            await send_telegram_message(f"⚠️ *Ошибка бота*\n`{str(e)}`")
        except:
            pass

def run_async_analysis():
    asyncio.run(run_analysis())

def start_scheduler():
    schedule.every().day.at("08:00").do(run_async_analysis)
    schedule.every().day.at("14:00").do(run_async_analysis)
    schedule.every().day.at("20:00").do(run_async_analysis)
    print("✅ Планировщик запущен: 08:00, 14:00, 20:00 UTC")
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    print("🚀 Crypto Signal Bot запускается...")
    print(f"ANTHROPIC_API_KEY: {'✅' if ANTHROPIC_API_KEY else '❌'}")
    print(f"TELEGRAM_TOKEN: {'✅' if TELEGRAM_TOKEN else '❌'}")
    print(f"CHAT_ID: {'✅' if CHAT_ID else '❌'}")

    if not all([ANTHROPIC_API_KEY, TELEGRAM_TOKEN, CHAT_ID]):
        print("❌ Не все переменные окружения установлены!")
        exit(1)

    asyncio.run(run_analysis())
    start_scheduler()
