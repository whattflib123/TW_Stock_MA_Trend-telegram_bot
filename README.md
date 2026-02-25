# TW Stock EMA Alert (Telegram)

這是一個台股日線 EMA 與風險條件監控專案。  
它會抓取你在 `config.json` 設定的商品，判斷是否命中以下任一通知來源：
- EMA 接近條件（預設 `EMA50/200/576`、±1%）
- 風險條件（4 類條件中命中至少 3 類）
  
通知內容包含商品資訊、均線判斷與風險條件明細（含比較日 `MM/DD -> MM/DD`），並附上近一年日 K 圖與近三年周 K 圖（含可設定的 EMA 線）。

## 實際傳送內容（範例）

### 實際訊息（本次掃描無命中）

```text
本次掃描完成：沒有商品符合 EMA 接近或風險 4 選 3 條件。
```

### 命中時的訊息（實際資料範例）

```text
2881 富邦金
日期: 2026-02-24
收盤價: 94.10
接近均線: EMA50 (±1.0%)
EMA50/EMA200 多頭排列: 是
風險訊號: 3/4 類命中（門檻 3）
① 指數急殺: 命中 (1日 -4.33% 02/21->02/24 / 5日 -8.74% 02/17->02/24)
② 富邦金超跌: 命中 (比較日 02/21->02/24, 1日 -6.09% / 10日 -15.88%)
③ 技術極端: 命中 (RSI 26.41, MA120 96.37)
④ 量能爆量: 未命中 (當日 42311824, 20日均 29844122, 倍數 1.42x)
圖表: 近一年日K
```

### 實際圖片（程式輸出）

近一年日 K（含 EMA50/200/576/676，無格線）  
![sample daily](docs/sample_daily_2881.png)

近三年周 K（含 EMA50/200/576/676，無格線）  
![sample weekly](docs/sample_weekly_2881.png)

抓取台股日線資料，偵測收盤價是否接近 `EMA50 / EMA200 / EMA576`（預設 ±1%）或是否命中「風險 4 選 3」條件，若命中則透過 Telegram 傳送通知，並附上近一年日 K 圖與近三年周 K 圖。

## 可調整設定（單一檔案）

所有可調整參數都集中在 `config.json`：

- `stocks`: 監控品種（代號、中文名、yfinance 代號）
- `detection_ema_windows`: 觸發通知要比對的 EMA 週期
- `chart_ema_windows`: 圖上要畫出的 EMA 週期
- `ema_tolerance`: 接近均線的容許誤差（例如 `0.01` = ±1%）
- `market_symbol`: 大盤代號（預設 `^TWII`）
- `market_drop_1d`: 指數單日跌幅門檻（預設 `0.04` = 4%）
- `market_drop_5d`: 指數 5 日跌幅門檻（預設 `0.08` = 8%）
- `required_stress_hits`: 4 類條件至少命中幾類才算觸發（預設 `3`）
- `stress_rule_defaults`: 個股風險門檻預設值（單日/10日跌幅、RSI、MA、量能）
- `stocks[].stress_rule_override`: 個股覆寫門檻（可只填要覆寫的欄位）

範例（節錄）：

```json
{
  "ema_tolerance": 0.01,
  "detection_ema_windows": [50, 200, 576],
  "chart_ema_windows": [50, 200, 576, 676],
  "market_symbol": "^TWII",
  "market_drop_1d": 0.04,
  "market_drop_5d": 0.08,
  "required_stress_hits": 3,
  "stress_rule_defaults": {
    "stock_drop_1d": 0.06,
    "stock_drop_10d": 0.15,
    "rsi_threshold": 28,
    "ma_window": 120,
    "volume_avg_window": 20,
    "volume_spike_multiplier": 1.8
  },
  "stocks": [
    { "code": "2330", "name_zh": "台積電", "yf_symbol": "2330.TW" },
    {
      "code": "8299",
      "name_zh": "群聯",
      "yf_symbol": "8299.TWO",
      "stress_rule_override": {
        "stock_drop_1d": 0.07,
        "stock_drop_10d": 0.18
      }
    }
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
- 風險條件 4 類中命中至少 3 類時通知（門檻可調）
- 同一檔同時命中 EMA 與風險條件時，合併在同一則通知
- 訊息內容包含：
  - 商品代號 + 中文名稱
  - 最新可得日線收盤價
  - 接近哪一條（或多條）均線
  - `EMA50 > EMA200` 是否成立（多頭排列）
  - 風險 4 類條件是否命中與關鍵數值（大盤跌幅、個股跌幅、RSI/MA、量能倍數）
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
