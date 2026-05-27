import os
import asyncio
import aiohttp
import anthropic
from datetime import datetime
import schedule
import time

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# ============================================================
# СБОР ДАННЫХ
# ============================================================

async def get_prices():
    """Цены BTC/ETH + 24h изменение с CoinGecko"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={
                    "vs_currency": "usd",
                    "ids": "bitcoin,ethereum",
                    "order": "market_cap_desc",
                    "sparkline": "false",
                    "price_change_percentage": "24h"
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                result = {}
                for coin in data:
                    key = "BTC" if coin["id"] == "bitcoin" else "ETH"
                    result[key] = coin["current_price"]
                    result[f"{key}_change_24h"] = round(coin.get("price_change_percentage_24h", 0), 2)
                    result[f"{key}_volume_24h"] = coin.get("total_volume", 0)
                return result
    except Exception as e:
        return {"BTC": "н/д", "ETH": "н/д", "error": str(e)}


async def get_fear_greed():
    """Fear & Greed Index"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.alternative.me/fng/?limit=2",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                today = data["data"][0]
                yesterday = data["data"][1]
                return {
                    "value": today["value"],
                    "classification": today["value_classification"],
                    "yesterday": yesterday["value"],
                    "change": int(today["value"]) - int(yesterday["value"])
                }
    except Exception as e:
        return {"value": "н/д", "classification": "н/д", "error": str(e)}


async def get_funding_rates():
    """Фандинг рейты с OKX"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://www.okx.com/api/v5/public/funding-rate",
                params={"instId": "BTC-USDT-SWAP"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                btc_data = await resp.json()
            async with session.get(
                "https://www.okx.com/api/v5/public/funding-rate",
                params={"instId": "ETH-USDT-SWAP"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                eth_data = await resp.json()
            btc_rate = float(btc_data["data"][0].get("fundingRate", 0)) * 100
            eth_rate = float(eth_data["data"][0].get("fundingRate", 0)) * 100
            return {"BTC_funding": btc_rate, "ETH_funding": eth_rate}
    except Exception as e:
        return {"BTC_funding": "н/д", "ETH_funding": "н/д", "error": str(e)}


async def get_market_structure():
    """Доминация, капитализация + топ альты для оценки рынка"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.coingecko.com/api/v3/global",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                d = data["data"]
                return {
                    "btc_dominance": round(d["market_cap_percentage"].get("btc", 0), 2),
                    "eth_dominance": round(d["market_cap_percentage"].get("eth", 0), 2),
                    "total_market_cap_b": round(d["total_market_cap"].get("usd", 0) / 1e9, 0),
                    "market_cap_change_24h": round(d.get("market_cap_change_percentage_24h_usd", 0), 2),
                    "active_cryptos": d.get("active_cryptocurrencies", 0),
                }
    except Exception as e:
        return {"btc_dominance": "н/д", "total_market_cap_b": "н/д", "error": str(e)}


async def get_open_interest():
    """Open Interest BTC с OKX — как прокси институционального позиционирования"""
    try:
        async with aiohttp.ClientSession() as session:
            # OI в BTC контрактах
            async with session.get(
                "https://www.okx.com/api/v5/public/open-interest",
                params={"instType": "SWAP", "instId": "BTC-USDT-SWAP"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                btc_oi = await resp.json()

            async with session.get(
                "https://www.okx.com/api/v5/public/open-interest",
                params={"instType": "SWAP", "instId": "ETH-USDT-SWAP"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                eth_oi = await resp.json()

            btc_oi_val = float(btc_oi["data"][0].get("oiCcy", 0))
            eth_oi_val = float(eth_oi["data"][0].get("oiCcy", 0))

            return {
                "btc_oi": round(btc_oi_val, 0),
                "eth_oi": round(eth_oi_val, 0),
            }
    except Exception as e:
        return {"btc_oi": "н/д", "eth_oi": "н/д", "error": str(e)}


async def get_liquidations():
    """Ликвидации за 24ч с OKX как индикатор экстремальных движений"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://www.okx.com/api/v5/public/liquidation-orders",
                params={"instType": "SWAP", "instId": "BTC-USDT-SWAP", "state": "filled", "limit": "100"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()

            orders = data.get("data", [{}])[0].get("details", [])
            long_liq = sum(float(o.get("sz", 0)) for o in orders if o.get("side") == "buy")
            short_liq = sum(float(o.get("sz", 0)) for o in orders if o.get("side") == "sell")

            return {
                "long_liq": round(long_liq, 2),
                "short_liq": round(short_liq, 2),
            }
    except Exception as e:
        return {"long_liq": "н/д", "short_liq": "н/д", "error": str(e)}


async def collect_all_data():
    """Собираем все данные параллельно"""
    prices, fear_greed, funding, market, oi, liq = await asyncio.gather(
        get_prices(), get_fear_greed(), get_funding_rates(),
        get_market_structure(), get_open_interest(), get_liquidations(),
        return_exceptions=True
    )
    if isinstance(prices, Exception): prices = {}
    if isinstance(fear_greed, Exception): fear_greed = {}
    if isinstance(funding, Exception): funding = {}
    if isinstance(market, Exception): market = {}
    if isinstance(oi, Exception): oi = {}
    if isinstance(liq, Exception): liq = {}

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        "prices": prices,
        "fear_greed": fear_greed,
        "funding": funding,
        "market": market,
        "oi": oi,
        "liq": liq,
    }


# ============================================================
# АНАЛИЗ ЧЕРЕЗ CLAUDE
# ============================================================

def analyze_with_claude(market_data: dict) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    p = market_data.get("prices", {})
    fg = market_data.get("fear_greed", {})
    f = market_data.get("funding", {})
    m = market_data.get("market", {})
    oi = market_data.get("oi", {})
    liq = market_data.get("liq", {})

    fg_change = fg.get('change', 0)
    fg_arrow = "↑" if isinstance(fg_change, int) and fg_change > 0 else "↓" if isinstance(fg_change, int) and fg_change < 0 else "→"

    prompt = f"""Ты профессиональный криптовалютный трейдер и аналитик. Проанализируй данные и дай чёткий торговый сигнал.

РЫНОЧНЫЕ ДАННЫЕ ({market_data['timestamp']}):

💰 ЦЕНЫ И ОБЪЁМЫ:
- BTC: ${p.get('BTC', 'н/д')} ({p.get('BTC_change_24h', 'н/д')}% за 24ч)
- ETH: ${p.get('ETH', 'н/д')} ({p.get('ETH_change_24h', 'н/д')}% за 24ч)
- BTC объём 24ч: ${p.get('BTC_volume_24h', 'н/д'):,}

😱 FEAR & GREED INDEX:
- Сегодня: {fg.get('value', 'н/д')}/100 — {fg.get('classification', 'н/д')}
- Вчера было: {fg.get('yesterday', 'н/д')}/100 (изменение: {fg_arrow}{abs(fg_change) if isinstance(fg_change, int) else 'н/д'})

📊 ФАНДИНГ РЕЙТЫ (8ч):
- BTC: {f.get('BTC_funding', 'н/д')}%
- ETH: {f.get('ETH_funding', 'н/д')}%

🌍 СТРУКТУРА РЫНКА:
- BTC Dominance: {m.get('btc_dominance', 'н/д')}%
- ETH Dominance: {m.get('eth_dominance', 'н/д')}%
- Total Market Cap: ${m.get('total_market_cap_b', 'н/д')}B ({m.get('market_cap_change_24h', 'н/д')}% за 24ч)

📐 OPEN INTEREST (OKX):
- BTC OI: {oi.get('btc_oi', 'н/д')} BTC
- ETH OI: {oi.get('eth_oi', 'н/д')} ETH

💥 ЛИКВИДАЦИИ (последние):
- Лонги ликвидированы: {liq.get('long_liq', 'н/д')} BTC
- Шорты ликвидированы: {liq.get('short_liq', 'н/д')} BTC

ТВОЙ АНАЛИЗ:

1. **ОБЩАЯ КАРТИНА** (2-3 предложения)

2. **КЛЮЧЕВЫЕ СИГНАЛЫ**:
   - Настроение: Fear&Greed динамика (растёт/падает важнее абсолютного значения)
   - Деривативы: фандинг + OI (растущий OI + растущая цена = сильный тренд)
   - Ликвидации: кого выбивали (лонги или шорты)
   - Структура: доминация BTC

3. **ТОРГОВЫЙ СИГНАЛ**: 🟢 БЫЧИЙ / 🔴 МЕДВЕЖИЙ / 🟡 НЕЙТРАЛЬНЫЙ

4. **КОНКРЕТНЫЙ ПЛАН** (входы, стоп, тейк, R/R)

5. **РИСКИ** (1-2 пункта)

Пиши чётко, используй эмодзи. 280-380 слов."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


# ============================================================
# ФОРМАТИРОВАНИЕ
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
        return str(val)

def change_emoji(val):
    try:
        v = float(val)
        if v > 2: return '🟢'
        if v > 0: return '🟡'
        if v > -2: return '🟡'
        return '🔴'
    except:
        return '❓'

def funding_emoji(val):
    try:
        v = float(val)
        if v > 0.05: return '🔴'
        if v > 0: return '🟡'
        return '🟢'
    except:
        return '❓'

def format_volume(val):
    try:
        v = float(val)
        if v >= 1e9: return f"${v/1e9:.1f}B"
        if v >= 1e6: return f"${v/1e6:.0f}M"
        return f"${v:,.0f}"
    except:
        return "н/д"

def format_message(market_data: dict, analysis: str) -> str:
    p = market_data['prices']
    fg = market_data['fear_greed']
    f = market_data['funding']
    m = market_data['market']
    oi = market_data['oi']
    liq = market_data['liq']

    btc = p.get('BTC', 'н/д')
    eth = p.get('ETH', 'н/д')
    btc_ch = p.get('BTC_change_24h', 'н/д')
    eth_ch = p.get('ETH_change_24h', 'н/д')
    btc_vol = p.get('BTC_volume_24h', 'н/д')

    fg_val = fg.get('value', 'н/д')
    fg_class = fg.get('classification', 'н/д')
    fg_change = fg.get('change', 0)
    fg_arrow = "↑" if isinstance(fg_change, int) and fg_change > 0 else ("↓" if isinstance(fg_change, int) and fg_change < 0 else "→")

    btc_fund = f.get('BTC_funding', 'н/д')
    eth_fund = f.get('ETH_funding', 'н/д')
    btc_dom = m.get('btc_dominance', 'н/д')
    mcap = m.get('total_market_cap_b', 'н/д')
    mcap_ch = m.get('market_cap_change_24h', 'н/д')

    msg = f"""━━━━━━━━━━━━━━━━━━━━
🤖 *КРИПТО СИГНАЛ*
📅 {market_data['timestamp']}
━━━━━━━━━━━━━━━━━━━━

📊 *ЦЕНЫ*
₿ BTC: *{safe_price(btc)}* {change_emoji(btc_ch)} {safe_num(btc_ch, 2)}%
Ξ ETH: *{safe_price(eth, 2)}* {change_emoji(eth_ch)} {safe_num(eth_ch, 2)}%
📦 BTC объём: *{format_volume(btc_vol)}*

😱 *FEAR & GREED*
*{fg_val}/100* — {fg_class} {fg_arrow}

📈 *ФАНДИНГ* (8ч)
BTC: {funding_emoji(btc_fund)} *{safe_pct(btc_fund)}*
ETH: {funding_emoji(eth_fund)} *{safe_pct(eth_fund)}*

📐 *OPEN INTEREST* (OKX)
BTC OI: *{safe_num(oi.get('btc_oi', 'н/д'), 0)} BTC*
ETH OI: *{safe_num(oi.get('eth_oi', 'н/д'), 0)} ETH*

🌍 *РЫНОК*
BTC Dom: *{safe_num(btc_dom)}%* | MCap: *{safe_price(mcap)}B* {change_emoji(mcap_ch)} {safe_num(mcap_ch, 1)}%

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
        print(f"BTC={market_data['prices'].get('BTC', '?')} F&G={market_data['fear_greed'].get('value', '?')} OI={market_data['oi'].get('btc_oi', '?')}")
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
    print("✅ Планировщик: 08:00, 14:00, 20:00 UTC")
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    print("🚀 Crypto Signal Bot v3")
    print(f"ANTHROPIC_API_KEY: {'✅' if ANTHROPIC_API_KEY else '❌'}")
    print(f"TELEGRAM_TOKEN: {'✅' if TELEGRAM_TOKEN else '❌'}")
    print(f"CHAT_ID: {'✅' if CHAT_ID else '❌'}")

    if not all([ANTHROPIC_API_KEY, TELEGRAM_TOKEN, CHAT_ID]):
        print("❌ Переменные окружения не заданы!")
        exit(1)

    asyncio.run(run_analysis())
    start_scheduler()
    start_scheduler()
