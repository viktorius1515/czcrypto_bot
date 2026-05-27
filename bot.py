import os
import asyncio
import aiohttp
import anthropic
from datetime import datetime
import schedule
import time
import xml.etree.ElementTree as ET

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
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={
                    "vs_currency": "usd",
                    "ids": "bitcoin,ethereum",
                    "order": "market_cap_desc",
                    "sparkline": "false",
                    "price_change_percentage": "24h,7d"
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                result = {}
                for coin in data:
                    key = "BTC" if coin["id"] == "bitcoin" else "ETH"
                    result[key] = coin["current_price"]
                    result[f"{key}_change_24h"] = round(coin.get("price_change_percentage_24h", 0) or 0, 2)
                    result[f"{key}_change_7d"] = round(coin.get("price_change_percentage_7d_in_currency", 0) or 0, 2)
                    result[f"{key}_volume_24h"] = coin.get("total_volume", 0)
                    result[f"{key}_ath"] = coin.get("ath", 0)
                    result[f"{key}_ath_pct"] = round(coin.get("ath_change_percentage", 0) or 0, 1)
                return result
    except Exception as e:
        return {"BTC": "н/д", "ETH": "н/д", "error": str(e)}


async def get_fear_greed():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.alternative.me/fng/?limit=7",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                items = data["data"]
                today = items[0]
                yesterday = items[1]
                week_ago = items[6]
                return {
                    "value": today["value"],
                    "classification": today["value_classification"],
                    "yesterday": yesterday["value"],
                    "week_ago": week_ago["value"],
                    "change_day": int(today["value"]) - int(yesterday["value"]),
                    "change_week": int(today["value"]) - int(week_ago["value"]),
                }
    except Exception as e:
        return {"value": "н/д", "classification": "н/д", "error": str(e)}


async def get_funding_rates():
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
                }
    except Exception as e:
        return {"btc_dominance": "н/д", "total_market_cap_b": "н/д", "error": str(e)}


async def get_open_interest():
    try:
        async with aiohttp.ClientSession() as session:
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
            return {
                "btc_oi": round(float(btc_oi["data"][0].get("oiCcy", 0)), 0),
                "eth_oi": round(float(eth_oi["data"][0].get("oiCcy", 0)), 0),
            }
    except Exception as e:
        return {"btc_oi": "н/д", "eth_oi": "н/д", "error": str(e)}


async def get_news():
    """
    Новости с CryptoPanic (бесплатный публичный токен) и Reddit RSS.
    Если недоступны — возвращаем пустой список, Claude анализирует без новостей.
    """
    headlines = []

    # Источник 1: CryptoPanic
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://cryptopanic.com/api/free/v1/posts/",
                params={"auth_token": "free", "currencies": "BTC,ETH", "public": "true", "kind": "news"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for item in data.get("results", [])[:8]:
                        title = item.get("title", "")
                        votes = item.get("votes", {})
                        positive = votes.get("positive", 0)
                        negative = votes.get("negative", 0)
                        if title:
                            sentiment = "📈" if positive > negative else ("📉" if negative > positive else "➡️")
                            headlines.append(f"{sentiment} {title}")
    except Exception:
        pass

    # Источник 2: Reddit r/Bitcoin RSS
    if len(headlines) < 3:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://www.reddit.com/r/Bitcoin/new.json",
                    params={"limit": "10"},
                    headers={"User-Agent": "CryptoBot/1.0"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        posts = data.get("data", {}).get("children", [])
                        for post in posts[:6]:
                            title = post.get("data", {}).get("title", "")
                            score = post.get("data", {}).get("score", 0)
                            if title and score > 10:
                                headlines.append(f"🔶 {title[:100]}")
        except Exception:
            pass

    # Источник 3: OKX объявления (листинги новых монет = бычий сигнал)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://www.okx.com/api/v5/support/announcements",
                params={"annType": "2", "page": "1"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("data", {}).get("details", [])[:3]
                    for item in items:
                        title = item.get("annTitle", "")
                        if title:
                            headlines.append(f"🏦 OKX: {title[:80]}")
    except Exception:
        pass

    return {
        "headlines": headlines[:10],
        "count": len(headlines),
        "available": len(headlines) > 0
    }


async def collect_all_data():
    prices, fear_greed, funding, market, oi, news = await asyncio.gather(
        get_prices(), get_fear_greed(), get_funding_rates(),
        get_market_structure(), get_open_interest(), get_news(),
        return_exceptions=True
    )
    if isinstance(prices, Exception): prices = {}
    if isinstance(fear_greed, Exception): fear_greed = {}
    if isinstance(funding, Exception): funding = {}
    if isinstance(market, Exception): market = {}
    if isinstance(oi, Exception): oi = {}
    if isinstance(news, Exception): news = {"headlines": [], "count": 0, "available": False}

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        "prices": prices,
        "fear_greed": fear_greed,
        "funding": funding,
        "market": market,
        "oi": oi,
        "news": news,
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
    news = market_data.get("news", {})

    headlines_text = ""
    if news.get("available") and news.get("headlines"):
        headlines_text = "\n📰 НОВОСТНОЙ ФОН:\n" + "\n".join(f"- {h}" for h in news["headlines"])
    else:
        headlines_text = "\n📰 НОВОСТНОЙ ФОН: данные недоступны"

    fg_change_day = fg.get('change_day', 0)
    fg_change_week = fg.get('change_week', 0)

    prompt = f"""Ты профессиональный криптовалютный трейдер и аналитик. Проанализируй все данные и дай чёткий торговый сигнал.

РЫНОЧНЫЕ ДАННЫЕ ({market_data['timestamp']}):

💰 ЦЕНЫ:
- BTC: ${p.get('BTC', 'н/д')} | 24ч: {p.get('BTC_change_24h', 'н/д')}% | 7д: {p.get('BTC_change_7d', 'н/д')}%
- ETH: ${p.get('ETH', 'н/д')} | 24ч: {p.get('ETH_change_24h', 'н/д')}% | 7д: {p.get('ETH_change_7d', 'н/д')}%
- BTC от ATH: {p.get('BTC_ath_pct', 'н/д')}%
- BTC объём 24ч: ${p.get('BTC_volume_24h', 0):,}

😱 FEAR & GREED:
- Сегодня: {fg.get('value', 'н/д')}/100 ({fg.get('classification', 'н/д')})
- Вчера: {fg.get('yesterday', 'н/д')} | Неделю назад: {fg.get('week_ago', 'н/д')}
- Изменение за день: {'+' if isinstance(fg_change_day, int) and fg_change_day > 0 else ''}{fg_change_day}
- Изменение за неделю: {'+' if isinstance(fg_change_week, int) and fg_change_week > 0 else ''}{fg_change_week}

📊 ФАНДИНГ (8ч):
- BTC: {f.get('BTC_funding', 'н/д')}% | ETH: {f.get('ETH_funding', 'н/д')}%

📐 OPEN INTEREST (OKX):
- BTC OI: {oi.get('btc_oi', 'н/д')} BTC
- ETH OI: {oi.get('eth_oi', 'н/д')} ETH

🌍 РЫНОК:
- BTC Dom: {m.get('btc_dominance', 'н/д')}% | ETH Dom: {m.get('eth_dominance', 'н/д')}%
- Total MCap: ${m.get('total_market_cap_b', 'н/д')}B | 24ч: {m.get('market_cap_change_24h', 'н/д')}%
{headlines_text}

СТРУКТУРА АНАЛИЗА:

1. **ОБЩАЯ КАРТИНА** (2-3 предложения — синтез всех данных)

2. **КЛЮЧЕВЫЕ СИГНАЛЫ**:
   - Тренд (цена 24ч + 7д + расстояние от ATH)
   - Настроение (F&G динамика за день и неделю)  
   - Деривативы (фандинг + OI)
   - Новостной фон (если есть — позитив/негатив/нейтрально)

3. **ТОРГОВЫЙ СИГНАЛ**: 🟢 БЫЧИЙ / 🔴 МЕДВЕЖИЙ / 🟡 НЕЙТРАЛЬНЫЙ

4. **КОНКРЕТНЫЙ ПЛАН**:
   - Действие + уровни входа / стоп-лосс / тейк-профит
   - Risk/Reward соотношение

5. **РИСКИ** (1-2 пункта)

Пиши чётко, без воды. Используй эмодзи. 300-400 слов."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1400,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


# ============================================================
# ФОРМАТИРОВАНИЕ
# ============================================================

def safe_price(val, decimals=0):
    try:
        return f"${float(val):,.{decimals}f}"
    except:
        return "н/д"

def safe_pct(val, decimals=4):
    try:
        return f"{float(val):.{decimals}f}%"
    except:
        return "н/д"

def safe_num(val, decimals=2):
    try:
        return f"{float(val):.{decimals}f}"
    except:
        return str(val)

def change_emoji(val):
    try:
        v = float(val)
        if v > 3: return '🟢'
        if v > 0: return '🟡'
        if v > -3: return '🟡'
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
    news = market_data.get('news', {})

    btc = p.get('BTC', 'н/д')
    eth = p.get('ETH', 'н/д')
    btc_ch = p.get('BTC_change_24h', 'н/д')
    eth_ch = p.get('ETH_change_24h', 'н/д')
    btc_7d = p.get('BTC_change_7d', 'н/д')
    btc_vol = p.get('BTC_volume_24h', 'н/д')
    btc_ath_pct = p.get('BTC_ath_pct', 'н/д')

    fg_val = fg.get('value', 'н/д')
    fg_class = fg.get('classification', 'н/д')
    fg_ch_day = fg.get('change_day', 0)
    fg_ch_week = fg.get('change_week', 0)
    day_arrow = "↑" if isinstance(fg_ch_day, int) and fg_ch_day > 0 else ("↓" if isinstance(fg_ch_day, int) and fg_ch_day < 0 else "→")
    week_arrow = "↑" if isinstance(fg_ch_week, int) and fg_ch_week > 0 else ("↓" if isinstance(fg_ch_week, int) and fg_ch_week < 0 else "→")

    # Новости — берём топ 4 заголовка
    news_section = ""
    if news.get("available") and news.get("headlines"):
        headlines = news["headlines"][:4]
        news_lines = "\n".join(headlines)
        news_section = f"""
📰 *НОВОСТИ*
{news_lines}
"""

    msg = f"""━━━━━━━━━━━━━━━━━━━━
🤖 *КРИПТО СИГНАЛ*
📅 {market_data['timestamp']}
━━━━━━━━━━━━━━━━━━━━

📊 *ЦЕНЫ*
₿ BTC: *{safe_price(btc)}* {change_emoji(btc_ch)} {safe_num(btc_ch, 2)}% / 7д {change_emoji(btc_7d)} {safe_num(btc_7d, 1)}%
Ξ ETH: *{safe_price(eth, 2)}* {change_emoji(eth_ch)} {safe_num(eth_ch, 2)}%
📦 Объём BTC: *{format_volume(btc_vol)}*
📉 BTC от ATH: *{safe_num(btc_ath_pct, 1)}%*

😱 *FEAR & GREED*
*{fg_val}/100* — {fg_class}
День: {day_arrow}{abs(fg_ch_day) if isinstance(fg_ch_day, int) else '?'} | Неделя: {week_arrow}{abs(fg_ch_week) if isinstance(fg_ch_week, int) else '?'}

📈 *ФАНДИНГ* (8ч)
BTC: {funding_emoji(f.get('BTC_funding'))} *{safe_pct(f.get('BTC_funding'))}*
ETH: {funding_emoji(f.get('ETH_funding'))} *{safe_pct(f.get('ETH_funding'))}*

📐 *OPEN INTEREST* (OKX)
BTC: *{safe_num(oi.get('btc_oi', 'н/д'), 0)} BTC*

🌍 *РЫНОК*
Dom: *{safe_num(m.get('btc_dominance'))}%* | MCap: *{safe_price(m.get('total_market_cap_b'))}B* {change_emoji(m.get('market_cap_change_24h'))} {safe_num(m.get('market_cap_change_24h'), 1)}%
{news_section}
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
        news_count = market_data['news'].get('count', 0)
        print(f"BTC={market_data['prices'].get('BTC', '?')} F&G={market_data['fear_greed'].get('value', '?')} Новостей={news_count}")
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
    print("🚀 Crypto Signal Bot v4 — с новостями")
    print(f"ANTHROPIC_API_KEY: {'✅' if ANTHROPIC_API_KEY else '❌'}")
    print(f"TELEGRAM_TOKEN: {'✅' if TELEGRAM_TOKEN else '❌'}")
    print(f"CHAT_ID: {'✅' if CHAT_ID else '❌'}")

    if not all([ANTHROPIC_API_KEY, TELEGRAM_TOKEN, CHAT_ID]):
        print("❌ Переменные окружения не заданы!")
        exit(1)

    asyncio.run(run_analysis())
    start_scheduler()
    start_scheduler()
    start_scheduler()
