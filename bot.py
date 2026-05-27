import os
import asyncio
import aiohttp
import anthropic
from datetime import datetime
import schedule
import time
import re

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
    """Цены BTC/ETH с CoinGecko"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "bitcoin,ethereum", "vs_currencies": "usd"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                return {"BTC": data["bitcoin"]["usd"], "ETH": data["ethereum"]["usd"]}
    except Exception as e:
        return {"BTC": "н/д", "ETH": "н/д", "error": str(e)}


async def get_fear_greed():
    """Fear & Greed Index"""
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


async def get_btc_dominance():
    """BTC доминация и общая капитализация"""
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


async def get_etf_flows():
    """
    ETF потоки BlackRock (iShares IBIT) и Fidelity (FBTC).
    Используем данные с farside.co.uk — единственный публичный агрегатор ETF потоков.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(
                "https://farside.co.uk/bitcoin-etf-flow-all-data/",
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                html = await resp.text()

        # Ищем строки таблицы с данными IBIT и FBTC
        # Паттерн: ищем последние числовые значения в колонках
        lines = html.split('\n')

        ibit_flow = None
        fbtc_flow = None
        total_flow = None

        # Ищем последнюю строку с данными (последний торговый день)
        # Таблица содержит колонки: Date | IBIT | FBTC | BITB | ARKB | BTCO | EZBC | BRRR | HODL | DEFI | GBTC | BTC | Total
        for line in reversed(lines):
            # Ищем строки таблицы с датами и числами
            if re.search(r'\d{1,2}\s+\w+\s+\d{4}', line) or re.search(r'\d{4}-\d{2}-\d{2}', line):
                # Извлекаем все числа из строки
                numbers = re.findall(r'[-]?\d+\.?\d*', line)
                if len(numbers) >= 5:
                    try:
                        # Первое число - дата-related, пропускаем
                        # IBIT обычно первая колонка после даты
                        if ibit_flow is None and len(numbers) > 1:
                            ibit_flow = float(numbers[1])
                        if fbtc_flow is None and len(numbers) > 2:
                            fbtc_flow = float(numbers[2])
                        if total_flow is None and len(numbers) > -1:
                            total_flow = float(numbers[-1])
                        break
                    except (ValueError, IndexError):
                        continue

        # Запасной вариант — ищем по ключевым словам IBIT/FBTC
        if ibit_flow is None:
            ibit_match = re.search(r'IBIT[^0-9-]*?([-]?\d+\.?\d*)', html)
            if ibit_match:
                ibit_flow = float(ibit_match.group(1))

        if fbtc_flow is None:
            fbtc_match = re.search(r'FBTC[^0-9-]*?([-]?\d+\.?\d*)', html)
            if fbtc_match:
                fbtc_flow = float(fbtc_match.group(1))

        return {
            "ibit_flow": ibit_flow,   # млн USD, + приток, - отток
            "fbtc_flow": fbtc_flow,
            "total_flow": total_flow,
            "source": "farside.co.uk"
        }

    except Exception as e:
        return {"ibit_flow": "н/д", "fbtc_flow": "н/д", "total_flow": "н/д", "error": str(e)}


async def get_cme_data():
    """
    CME BTC Futures — Open Interest как прокси для институционального позиционирования.
    Используем CoinGlass public API (бесплатно, без ключа для базовых данных).
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            # CoinGlass публичный эндпоинт для OI по биржам
            async with session.get(
                "https://open-api.coinglass.com/public/v2/open_interest",
                params={"symbol": "BTC"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()

            if data.get("code") == "0" or data.get("success"):
                exchanges = data.get("data", [])
                cme_data = next((x for x in exchanges if x.get("exchangeName", "").upper() == "CME"), None)
                total_oi = sum(float(x.get("openInterestUsd", 0)) for x in exchanges if x.get("openInterestUsd"))

                cme_oi = float(cme_data.get("openInterestUsd", 0)) / 1e9 if cme_data else None
                cme_pct = (float(cme_data.get("openInterestUsd", 0)) / total_oi * 100) if cme_data and total_oi else None

                return {
                    "cme_oi_b": round(cme_oi, 2) if cme_oi else "н/д",
                    "cme_pct": round(cme_pct, 1) if cme_pct else "н/д",
                    "total_oi_b": round(total_oi / 1e9, 2) if total_oi else "н/д"
                }
            else:
                return {"cme_oi_b": "н/д", "cme_pct": "н/д", "total_oi_b": "н/д"}

    except Exception as e:
        return {"cme_oi_b": "н/д", "cme_pct": "н/д", "total_oi_b": "н/д", "error": str(e)}


async def collect_all_data():
    """Собираем все данные параллельно"""
    prices, fear_greed, funding, dominance, etf, cme = await asyncio.gather(
        get_prices(), get_fear_greed(), get_funding_rates(),
        get_btc_dominance(), get_etf_flows(), get_cme_data(),
        return_exceptions=True
    )
    if isinstance(prices, Exception): prices = {}
    if isinstance(fear_greed, Exception): fear_greed = {}
    if isinstance(funding, Exception): funding = {}
    if isinstance(dominance, Exception): dominance = {}
    if isinstance(etf, Exception): etf = {}
    if isinstance(cme, Exception): cme = {}

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        "prices": prices,
        "fear_greed": fear_greed,
        "funding": funding,
        "dominance": dominance,
        "etf": etf,
        "cme": cme
    }


# ============================================================
# АНАЛИЗ ЧЕРЕЗ CLAUDE
# ============================================================

def analyze_with_claude(market_data: dict) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    etf = market_data.get("etf", {})
    cme = market_data.get("cme", {})

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

🏦 ETF ПОТОКИ (последний день):
- BlackRock IBIT: {etf.get('ibit_flow', 'н/д')} млн USD
- Fidelity FBTC: {etf.get('fbtc_flow', 'н/д')} млн USD
- Все BTC ETF суммарно: {etf.get('total_flow', 'н/д')} млн USD
(+ приток = институционалы покупают, - отток = продают)

📐 CME ФЬЮЧЕРСЫ (институционалы):
- CME Open Interest: ${cme.get('cme_oi_b', 'н/д')}B
- Доля CME от общего OI: {cme.get('cme_pct', 'н/д')}%
- Общий OI рынка: ${cme.get('total_oi_b', 'н/д')}B

ТВОЙ АНАЛИЗ ДОЛЖЕН СОДЕРЖАТЬ:

1. **ОБЩАЯ КАРТИНА** — что сейчас происходит (2-3 предложения)

2. **КЛЮЧЕВЫЕ СИГНАЛЫ**:
   - Розничный рынок: Fear&Greed + фандинг
   - Институционалы: ETF потоки (приток = бычий сигнал, отток = медвежий)
   - CME OI (высокая доля CME = институционалы активны)
   - Доминация BTC

3. **ТОРГОВЫЙ СИГНАЛ**: 🟢 БЫЧИЙ / 🔴 МЕДВЕЖИЙ / 🟡 НЕЙТРАЛЬНЫЙ

4. **КОНКРЕТНЫЙ ПЛАН**:
   - Действие, уровни входа, стоп-лосс, тейк-профит
   - Соотношение риск/прибыль

5. **РИСКИ** (1-2 пункта)

Пиши чётко, без воды. Используй эмодзи. Длина: 280-380 слов."""

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
        return "н/д"

def funding_emoji(val):
    try:
        v = float(val)
        if v > 0.05: return '🔴'
        if v > 0: return '🟡'
        return '🟢'
    except (TypeError, ValueError):
        return '❓'

def etf_emoji(val):
    try:
        v = float(val)
        if v > 100: return '🟢'
        if v > 0: return '🟡'
        return '🔴'
    except (TypeError, ValueError):
        return '❓'

def format_etf(val):
    try:
        v = float(val)
        sign = "+" if v > 0 else ""
        return f"{sign}{v:,.0f}M"
    except (TypeError, ValueError):
        return "н/д"

def format_message(market_data: dict, analysis: str) -> str:
    btc = market_data['prices'].get('BTC', 'н/д')
    eth = market_data['prices'].get('ETH', 'н/д')
    fg_value = market_data['fear_greed'].get('value', 'н/д')
    fg_class = market_data['fear_greed'].get('classification', 'н/д')
    btc_fund = market_data['funding'].get('BTC_funding', 'н/д')
    eth_fund = market_data['funding'].get('ETH_funding', 'н/д')
    btc_dom = market_data['dominance'].get('btc_dominance', 'н/д')
    total_mcap = market_data['dominance'].get('total_market_cap_b', 'н/д')
    etf = market_data.get('etf', {})
    cme = market_data.get('cme', {})

    ibit = etf.get('ibit_flow', 'н/д')
    fbtc = etf.get('fbtc_flow', 'н/д')
    total_etf = etf.get('total_flow', 'н/д')
    cme_oi = cme.get('cme_oi_b', 'н/д')
    cme_pct = cme.get('cme_pct', 'н/д')

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

🏦 *ETF ПОТОКИ* (вчера)
BlackRock IBIT: {etf_emoji(ibit)} *{format_etf(ibit)}*
Fidelity FBTC: {etf_emoji(fbtc)} *{format_etf(fbtc)}*
Все ETF: {etf_emoji(total_etf)} *{format_etf(total_etf)}*

📐 *CME ИНСТИТУЦИОНАЛЫ*
OI: *{safe_num(cme_oi)}B* | Доля: *{safe_num(cme_pct)}%*

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
        print(f"Данные: BTC={market_data['prices'].get('BTC', 'н/д')}, ETF={market_data['etf'].get('total_flow', 'н/д')}")
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
    print("🚀 Crypto Signal Bot v2 запускается...")
    print(f"ANTHROPIC_API_KEY: {'✅' if ANTHROPIC_API_KEY else '❌'}")
    print(f"TELEGRAM_TOKEN: {'✅' if TELEGRAM_TOKEN else '❌'}")
    print(f"CHAT_ID: {'✅' if CHAT_ID else '❌'}")

    if not all([ANTHROPIC_API_KEY, TELEGRAM_TOKEN, CHAT_ID]):
        print("❌ Не все переменные окружения установлены!")
        exit(1)

    asyncio.run(run_analysis())
    start_scheduler()
