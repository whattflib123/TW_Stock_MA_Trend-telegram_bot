# TW Stock EMA Alert (Telegram)

這是一個台股日線 EMA 監控專案。  
它會抓取你在 `config.json` 設定的商品，判斷最新可得日線收盤價是否接近指定均線（預設 `EMA50/200/576`、±1%），並在命中時透過 Telegram 發送通知。  
通知內容包含商品資訊與均線判斷，並附上近一年日 K 圖與近三年周 K 圖（含可設定的 EMA 線）。

## 實際傳送內容（範例）

### 實際訊息（本次掃描無命中）

```text
本次掃描完成：沒有商品符合 EMA 接近條件。
```

### 命中時的訊息（實際資料範例）

```text
2881 富邦金
日期: 2026-02-24
收盤價: 94.10
接近均線: EMA50 (±1.0%)
EMA50/EMA200 多頭排列: 是
圖表: 近一年日K
```

### 實際圖片（程式輸出）

近一年日 K（含 EMA50/200/576/676，無格線）  
![sample daily](docs/sample_daily_2881.png)

近三年周 K（含 EMA50/200/576/676，無格線）  
![sample weekly](docs/sample_weekly_2881.png)

抓取台股日線資料，偵測收盤價是否接近 `EMA50 / EMA200 / EMA576`（預設 ±1%），若命中則透過 Telegram 傳送通知，並附上近一年日 K 圖與近三年周 K 圖。

## 可調整設定（單一檔案）

所有可調整參數都集中在 `config.json`：

- `stocks`: 監控品種（代號、中文名、yfinance 代號）
- `detection_ema_windows`: 觸發通知要比對的 EMA 週期
- `chart_ema_windows`: 圖上要畫出的 EMA 週期
- `ema_tolerance`: 接近均線的容許誤差（例如 `0.01` = ±1%）

範例（節錄）：

```json
{
  "ema_tolerance": 0.01,
  "detection_ema_windows": [50, 200, 576],
  "chart_ema_windows": [50, 200, 576, 676],
  "stocks": [
    { "code": "2330", "name_zh": "台積電", "yf_symbol": "2330.TW" },
    { "code": "8299", "name_zh": "群聯", "yf_symbol": "8299.TWO" }
  ]
}
```

### 如何查 `name_zh` 與 `yf_symbol`

- `code`（代號）與 `name_zh`（中文名）：
  - 可直接用台股常用報價網站查（輸入代號即可看到中文名稱），例如 `2881 -> 富邦金`。
- `yf_symbol`（yfinance 代號）：
  - 上市股票/ETF 通常是 `代號.TW`（例：`2330.TW`、`0050.TW`）
  - 上櫃股票通常是 `代號.TWO`（例：`8299.TWO`）
  - 不確定時可用下列測試：

```bash
python3 - <<'PY'
import yfinance as yf
for s in ["2881.TW", "2881.TWO"]:
    df = yf.Ticker(s).history(period="5d", interval="1d")
    print(s, "OK" if not df.empty else "NO_DATA")
PY
```

- 回傳 `OK` 的通常就是可用的 `yf_symbol`。

## 功能

- 日線收盤價接近 EMA50/EMA200/EMA576（±1%）時通知
- 訊息內容包含：
  - 商品代號 + 中文名稱
  - 最新可得日線收盤價
  - 接近哪一條（或多條）均線
  - `EMA50 > EMA200` 是否成立（多頭排列）
- 附上最近一年日 K 線圖（含 EMA50/200/576/676，無格線）
- 額外附上最近三年周 K 線圖（含 EMA50/200/576/676，無格線）
- 每次執行前會先清除 `CHART_DIR` 內既有 `.png` 圖檔，避免累積

## 安裝

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 設定

1. 複製設定檔：

```bash
cp .env.example .env
```

2. 編輯 `.env`：

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
CONFIG_FILE=config.json
CHART_DIR=charts
```

3. 編輯 `config.json` 調整監控商品、EMA 與容許誤差。

## 執行
建議在每日台股收盤後執行，我在每天18:00執行一次
```bash
python3 scanner.py
```

執行完成後，若有命中條件會發送 Telegram 圖文通知。

## 備註

- 資料來源：`yfinance`
