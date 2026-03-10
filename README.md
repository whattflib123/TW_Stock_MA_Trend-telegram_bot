# TW Stock EMA Alert (Telegram)

這個腳本會抓你在 `config.json` 設定的台股商品，檢查是否接近指定 EMA，並在命中時透過 Telegram 發送圖文通知。

目前支援兩種觸發條件：
- EMA 接近：收盤價接近 `detection_ema_windows`（預設 `EMA50/200/576`）
- 風險條件：4 類訊號達門檻（預設 4 選 3）

## 功能摘要
- 掃描多檔股票（`config.json -> stocks`）
- 命中時發送 Telegram 日K與周K圖
- 追蹤回報（前次命中、此次固定回報一次）
- 無命中時發送總結訊息

## 訊息格式（目前版本）

### 1) 一般命中（EMA 或風險條件）
```text
{代號} {名稱}
日期: {YYYY-MM-DD}
收盤價: {close_price}
與昨日相比: 📈 +x.xx% / 📉 -x.xx% / ⚪ +0.00% ({MM/DD->MM/DD})
🎯 接近均線: EMA50, EMA200 (±{tolerance}%)
EMA50/EMA200 多頭排列: 🟢多頭 / 🔴空頭
🚨 風險訊號: {命中數}/4 類命中（門檻 {required_stress_hits}）
① 指數急殺: ✅命中 / ❌未命中 (...)
② 個股超跌: ✅命中 / ❌未命中 (...)
③ 技術極端: ✅命中 / ❌未命中 (...)
④ 量能爆量: ✅命中 / ❌未命中 (...)
🖼️ 圖表: 近一年日K
```

接著會再送一張「近三年周K」圖（追蹤回報 only 時不送周K）。

### 2) 追蹤回報（follow-up only）
```text
{代號} {名稱}
日期: {YYYY-MM-DD}
追蹤回報: 上次已觸發，本次固定回報一次
前一天漲跌幅: 📈 +x.xx% / 📉 -x.xx% / ⚪ +0.00% ({MM/DD->MM/DD})
最新收盤價: {close_price}
🖼️ 圖表: 近一年日K
```

### 3) 無命中
```text
ℹ️ 本次掃描完成：沒有商品符合 EMA 接近或風險 4 選 3 條件。
```

## 安裝
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 環境變數
建立 `.env`：
```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
CONFIG_FILE=config.json
CHART_DIR=charts
MEMORY_FILE=alert_memory.json
```

## 執行
```bash
python scanner.py
```

## 排程建議
- 本程式目前**沒有內建 13:30 前阻擋**。
- 若你同一天排程多次（例如 08:00 與 13:30），可能出現重複通知。
- 建議只排一次（例如 13:30 後）以降低重複訊息。

## 設定檔重點（config.json）
- `stocks`: 追蹤商品清單
- `ema_tolerance`: 接近均線容許誤差（如 `0.01` = ±1%）
- `detection_ema_windows`: 偵測用 EMA
- `chart_ema_windows`: 圖表顯示用 EMA
- `required_stress_hits`: 風險條件命中門檻（1~4）

## 依賴
- `yfinance`
- `pandas`
- `mplfinance`
- `requests`
- `python-dotenv`
