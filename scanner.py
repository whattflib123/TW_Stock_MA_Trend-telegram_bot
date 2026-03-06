#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import mplfinance as mpf
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv


@dataclass(frozen=True)
class StockItem:
    code: str
    name_zh: str
    yf_symbol: str
    stress_rule: "StressRule"


@dataclass(frozen=True)
class StressRule:
    stock_drop_1d: float
    stock_drop_10d: float
    rsi_threshold: float
    ma_window: int
    volume_avg_window: int
    volume_spike_multiplier: float


@dataclass(frozen=True)
class AppConfig:
    ema_tolerance: float
    detection_ema_windows: List[int]
    chart_ema_windows: List[int]
    market_symbol: str
    market_drop_1d: float
    market_drop_5d: float
    required_stress_hits: int
    stocks: List[StockItem]


def parse_stress_rule(raw_rule: Dict[str, object]) -> StressRule:
    return StressRule(
        stock_drop_1d=float(raw_rule.get("stock_drop_1d", 0.06)),
        stock_drop_10d=float(raw_rule.get("stock_drop_10d", 0.15)),
        rsi_threshold=float(raw_rule.get("rsi_threshold", 28.0)),
        ma_window=int(raw_rule.get("ma_window", 120)),
        volume_avg_window=int(raw_rule.get("volume_avg_window", 20)),
        volume_spike_multiplier=float(raw_rule.get("volume_spike_multiplier", 1.8)),
    )


def load_config(config_path: Path) -> AppConfig:
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    stress_defaults = parse_stress_rule(raw.get("stress_rule_defaults", {}))

    stocks: List[StockItem] = []
    for item in raw.get("stocks", []):
        stock_override = item.get("stress_rule_override", {})
        merged_rule = {
            "stock_drop_1d": stock_override.get("stock_drop_1d", stress_defaults.stock_drop_1d),
            "stock_drop_10d": stock_override.get("stock_drop_10d", stress_defaults.stock_drop_10d),
            "rsi_threshold": stock_override.get("rsi_threshold", stress_defaults.rsi_threshold),
            "ma_window": stock_override.get("ma_window", stress_defaults.ma_window),
            "volume_avg_window": stock_override.get("volume_avg_window", stress_defaults.volume_avg_window),
            "volume_spike_multiplier": stock_override.get(
                "volume_spike_multiplier", stress_defaults.volume_spike_multiplier
            ),
        }
        stocks.append(
            StockItem(
                code=str(item["code"]),
                name_zh=str(item["name_zh"]),
                yf_symbol=str(item["yf_symbol"]),
                stress_rule=parse_stress_rule(merged_rule),
            )
        )

    detection = [int(x) for x in raw.get("detection_ema_windows", [50, 200, 576])]
    chart = [int(x) for x in raw.get("chart_ema_windows", [50, 200, 576, 676])]
    tolerance = float(raw.get("ema_tolerance", 0.01))
    market_symbol = str(raw.get("market_symbol", "^TWII"))
    market_drop_1d = float(raw.get("market_drop_1d", 0.04))
    market_drop_5d = float(raw.get("market_drop_5d", 0.08))
    required_stress_hits = int(raw.get("required_stress_hits", 3))

    if not stocks:
        raise ValueError("config stocks is empty")
    if not detection:
        raise ValueError("config detection_ema_windows is empty")
    if not chart:
        raise ValueError("config chart_ema_windows is empty")
    if tolerance <= 0:
        raise ValueError("config ema_tolerance must be positive")
    if required_stress_hits < 1 or required_stress_hits > 4:
        raise ValueError("config required_stress_hits must be in [1, 4]")

    return AppConfig(
        ema_tolerance=tolerance,
        detection_ema_windows=detection,
        chart_ema_windows=chart,
        market_symbol=market_symbol,
        market_drop_1d=market_drop_1d,
        market_drop_5d=market_drop_5d,
        required_stress_hits=required_stress_hits,
        stocks=stocks,
    )


def fetch_daily_history(yf_symbol: str) -> pd.DataFrame:
    df = yf.Ticker(yf_symbol).history(period="3y", interval="1d", auto_adjust=False)
    if df.empty:
        raise ValueError(f"no data from yfinance for {yf_symbol}")
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    return df


def add_ema_columns(df: pd.DataFrame, ema_windows: List[int]) -> pd.DataFrame:
    out = df.copy()
    for w in ema_windows:
        out[f"EMA{w}"] = out["Close"].ewm(span=w, adjust=False).mean()
    return out


def near_ema_list(latest_row: pd.Series, tolerance: float, ema_windows: List[int]) -> List[int]:
    close_price = float(latest_row["Close"])
    hit_windows: List[int] = []
    for w in ema_windows:
        ema_value = float(latest_row[f"EMA{w}"])
        if ema_value <= 0:
            continue
        diff_ratio = abs(close_price - ema_value) / ema_value
        if diff_ratio <= tolerance:
            hit_windows.append(w)
    return hit_windows


def pct_change(close_series: pd.Series, lookback_days: int) -> Optional[float]:
    if len(close_series) <= lookback_days:
        return None
    curr = float(close_series.iloc[-1])
    prev = float(close_series.iloc[-1 - lookback_days])
    if prev <= 0:
        return None
    return (curr - prev) / prev


def calc_rsi(close_series: pd.Series, period: int = 14) -> Optional[float]:
    if len(close_series) < period + 1:
        return None
    delta = close_series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    last = rsi.iloc[-1]
    if pd.isna(last):
        return None
    return float(last)


def fmt_pct(ratio: Optional[float]) -> str:
    if ratio is None:
        return "N/A"
    return f"{ratio * 100:.2f}%"


def compare_md(series: pd.Series, lookback_days: int) -> str:
    if len(series) <= lookback_days:
        return "N/A"
    start = pd.Timestamp(series.index[-1 - lookback_days]).strftime("%m/%d")
    end = pd.Timestamp(series.index[-1]).strftime("%m/%d")
    return f"{start}->{end}"


def to_weekly_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    weekly = pd.DataFrame(
        {
            "Open": df["Open"].resample("W-FRI").first(),
            "High": df["High"].resample("W-FRI").max(),
            "Low": df["Low"].resample("W-FRI").min(),
            "Close": df["Close"].resample("W-FRI").last(),
            "Volume": df["Volume"].resample("W-FRI").sum(),
        }
    ).dropna()
    return weekly


def chart_style_no_grid() -> mpf.Style:
    return mpf.make_mpf_style(base_mpf_style="yahoo", rc={"axes.grid": False, "grid.alpha": 0.0})


def ema_color(window: int) -> str:
    if window == 50:
        return "blue"
    if window == 200:
        return "orange"
    return "green"


def create_daily_chart(
    df: pd.DataFrame, stock: StockItem, output_path: Path, chart_ema_windows: List[int]
) -> None:
    recent = df.tail(260).copy()
    addplots = [mpf.make_addplot(recent[f"EMA{w}"], width=1.1, color=ema_color(w)) for w in chart_ema_windows]
    ema_text = "/".join([str(w) for w in chart_ema_windows])
    title = f"{stock.code} {stock.name_zh} - Daily K with EMA{ema_text}"
    mpf.plot(
        recent,
        type="candle",
        style=chart_style_no_grid(),
        addplot=addplots,
        title=title,
        ylabel="Price",
        volume=True,
        ylabel_lower="Volume",
        figsize=(14, 8),
        savefig=str(output_path),
    )


def create_weekly_chart(
    df: pd.DataFrame, stock: StockItem, output_path: Path, chart_ema_windows: List[int]
) -> None:
    weekly = to_weekly_ohlcv(df)
    weekly = add_ema_columns(weekly, chart_ema_windows).tail(156).copy()
    if weekly.empty:
        raise ValueError("no weekly data to chart")

    addplots = [mpf.make_addplot(weekly[f"EMA{w}"], width=1.1, color=ema_color(w)) for w in chart_ema_windows]
    ema_text = "/".join([str(w) for w in chart_ema_windows])
    title = f"{stock.code} {stock.name_zh} - Weekly K(3Y) with EMA{ema_text}"
    mpf.plot(
        weekly,
        type="candle",
        style=chart_style_no_grid(),
        addplot=addplots,
        title=title,
        ylabel="Price",
        volume=True,
        ylabel_lower="Volume",
        figsize=(14, 8),
        savefig=str(output_path),
    )


def send_photo(token: str, chat_id: str, photo_path: Path, caption: str = "") -> None:
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption
    with photo_path.open("rb") as f:
        resp = requests.post(
            url,
            data=data,
            files={"photo": f},
            timeout=30,
        )
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("ok"):
        raise RuntimeError(f"telegram error: {payload}")


def send_message(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("ok"):
        raise RuntimeError(f"telegram error: {payload}")


def cleanup_old_charts(chart_dir: Path) -> None:
    for p in chart_dir.glob("*.png"):
        if p.is_file():
            p.unlink()


def load_alert_memory(memory_file: Path) -> Dict[str, Any]:
    if not memory_file.exists():
        return {"last_run_date": "", "hit_codes": [], "pending_followup_codes": []}
    try:
        with memory_file.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        last_run_date = str(raw.get("last_run_date", ""))
        hit_codes_raw = raw.get("hit_codes", [])
        pending_followup_raw = raw.get("pending_followup_codes")
        if not isinstance(hit_codes_raw, list):
            hit_codes_raw = []
        if pending_followup_raw is None:
            pending_followup_raw = hit_codes_raw
        if not isinstance(pending_followup_raw, list):
            pending_followup_raw = []
        hit_codes = [str(code) for code in hit_codes_raw]
        pending_followup_codes = [str(code) for code in pending_followup_raw]
        return {
            "last_run_date": last_run_date,
            "hit_codes": hit_codes,
            "pending_followup_codes": pending_followup_codes,
        }
    except Exception:
        return {"last_run_date": "", "hit_codes": [], "pending_followup_codes": []}


def save_alert_memory(
    memory_file: Path, run_date: date, hit_codes: Set[str], pending_followup_codes: Set[str]
) -> None:
    payload = {
        "last_run_date": run_date.isoformat(),
        "hit_codes": sorted(hit_codes),
        "pending_followup_codes": sorted(pending_followup_codes),
    }
    with memory_file.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main() -> None:
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    config_file = Path(os.getenv("CONFIG_FILE", "config.json"))
    chart_dir = Path(os.getenv("CHART_DIR", "charts"))
    memory_file = Path(os.getenv("MEMORY_FILE", "alert_memory.json"))
    chart_dir.mkdir(parents=True, exist_ok=True)
    cleanup_old_charts(chart_dir)

    if not token or not chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

    config = load_config(config_file)
    triggered_today = 0
    followup_from_previous_run = 0
    sent_total = 0
    today_hit_codes: Set[str] = set()
    today_run_date = date.today()
    memory = load_alert_memory(memory_file)
    pending_followup_codes = {str(x) for x in memory.get("pending_followup_codes", [])}
    unresolved_followup_codes = set(pending_followup_codes)

    market_df = fetch_daily_history(config.market_symbol)
    market_close = market_df["Close"]

    for stock in config.stocks:
        try:
            raw_df = fetch_daily_history(stock.yf_symbol)
            df = add_ema_columns(raw_df, config.chart_ema_windows)
            latest = df.iloc[-1]
            latest_date = pd.Timestamp(df.index[-1]).date().isoformat()
            latest_md = pd.Timestamp(df.index[-1]).strftime("%m/%d")
            close_price = float(latest["Close"])
            close_series = df["Close"]
            volume_series = df["Volume"]

            market_upto_today = market_close[market_close.index <= df.index[-1]]
            market_drop_1d = pct_change(market_upto_today, 1)
            market_drop_5d = pct_change(market_upto_today, 5)
            market_hit = (
                (market_drop_1d is not None and market_drop_1d <= -config.market_drop_1d)
                or (market_drop_5d is not None and market_drop_5d <= -config.market_drop_5d)
            )

            stock_drop_1d = pct_change(close_series, 1)
            stock_drop_10d = pct_change(close_series, 10)
            stock_hit = (
                (stock_drop_1d is not None and stock_drop_1d <= -stock.stress_rule.stock_drop_1d)
                or (stock_drop_10d is not None and stock_drop_10d <= -stock.stress_rule.stock_drop_10d)
            )

            rsi_value = calc_rsi(close_series, period=14)
            ma_series = close_series.rolling(window=stock.stress_rule.ma_window).mean()
            ma_value = float(ma_series.iloc[-1]) if not pd.isna(ma_series.iloc[-1]) else None
            technical_hit = (
                (rsi_value is not None and rsi_value < stock.stress_rule.rsi_threshold)
                or (ma_value is not None and close_price < ma_value)
            )

            volume_avg = volume_series.rolling(window=stock.stress_rule.volume_avg_window).mean()
            volume_avg_value = float(volume_avg.iloc[-1]) if not pd.isna(volume_avg.iloc[-1]) else None
            latest_volume = float(volume_series.iloc[-1])
            volume_hit = (
                volume_avg_value is not None
                and latest_volume >= volume_avg_value * stock.stress_rule.volume_spike_multiplier
            )

            stress_hits = [market_hit, stock_hit, technical_hit, volume_hit]
            stress_hit_count = sum(1 for x in stress_hits if x)
            stress_hit = stress_hit_count >= config.required_stress_hits

            hit_windows = near_ema_list(
                latest, tolerance=config.ema_tolerance, ema_windows=config.detection_ema_windows
            )
            today_hit = bool(hit_windows) or stress_hit
            followup_due = stock.code in pending_followup_codes
            followup_only = followup_due and not today_hit

            if not today_hit and not followup_only:
                continue
            if today_hit:
                today_hit_codes.add(stock.code)

            ema50 = float(latest["EMA50"])
            ema200 = float(latest["EMA200"])
            bullish = "是" if ema50 > ema200 else "否"

            if followup_only:
                caption_lines = [
                    f"{stock.code} {stock.name_zh}",
                    f"日期: {latest_date}",
                    f"追蹤回報: 上次已觸發，本次固定回報一次",
                    f"前一天漲跌幅: {fmt_pct(stock_drop_1d)} ({compare_md(close_series, 1)})",
                    f"最新收盤價: {close_price:.2f}",
                ]
            else:
                caption_lines = [
                    f"{stock.code} {stock.name_zh}",
                    f"日期: {latest_date}",
                    f"收盤價: {close_price:.2f}",
                    f"與昨日相比: {fmt_pct(stock_drop_1d)} ({compare_md(close_series, 1)})",
                ]

            if not followup_only and hit_windows:
                near_text = ", ".join([f"EMA{w}" for w in hit_windows])
                caption_lines.append(f"接近均線: {near_text} (±{config.ema_tolerance * 100:.1f}%)")
                caption_lines.append(f"EMA50/EMA200 多頭排列: {bullish}")

            if not followup_only and stress_hit:
                stock_prev_md = pd.Timestamp(df.index[-2]).strftime("%m/%d") if len(df) >= 2 else "N/A"
                caption_lines.append(f"風險訊號: {stress_hit_count}/4 類命中（門檻 {config.required_stress_hits}）")
                caption_lines.append(
                    f"① 指數急殺: {'命中' if market_hit else '未命中'} "
                    f"(1日 {fmt_pct(market_drop_1d)} {compare_md(market_upto_today, 1)} / "
                    f"5日 {fmt_pct(market_drop_5d)} {compare_md(market_upto_today, 5)})"
                )
                caption_lines.append(
                    f"② {stock.name_zh}超跌: {'命中' if stock_hit else '未命中'} "
                    f"(比較日 {stock_prev_md}->{latest_md}, 1日 {fmt_pct(stock_drop_1d)} / 10日 {fmt_pct(stock_drop_10d)})"
                )
                ma_text = f"{ma_value:.2f}" if ma_value is not None else "N/A"
                rsi_text = f"{rsi_value:.2f}" if rsi_value is not None else "N/A"
                caption_lines.append(
                    f"③ 技術極端: {'命中' if technical_hit else '未命中'} "
                    f"(RSI {rsi_text}, MA{stock.stress_rule.ma_window} {ma_text})"
                )
                if volume_avg_value is not None and volume_avg_value > 0:
                    vol_ratio = latest_volume / volume_avg_value
                    caption_lines.append(
                        f"④ 量能爆量: {'命中' if volume_hit else '未命中'} "
                        f"(當日 {latest_volume:.0f}, {stock.stress_rule.volume_avg_window}日均 {volume_avg_value:.0f}, 倍數 {vol_ratio:.2f}x)"
                    )
                else:
                    caption_lines.append(f"④ 量能爆量: {'命中' if volume_hit else '未命中'} (資料不足)")

            caption = "\n".join(caption_lines)

            daily_chart_path = chart_dir / f"{stock.code}_{latest_date}_daily.png"
            weekly_chart_path = chart_dir / f"{stock.code}_{latest_date}_weekly.png"
            create_daily_chart(df, stock, daily_chart_path, config.chart_ema_windows)
            send_photo(token, chat_id, daily_chart_path, caption + "\n圖表: 近一年日K")
            if not followup_only:
                create_weekly_chart(df, stock, weekly_chart_path, config.chart_ema_windows)
                send_photo(token, chat_id, weekly_chart_path)

            sent_total += 1
            if today_hit:
                triggered_today += 1
            if followup_only:
                followup_from_previous_run += 1
            if followup_due:
                unresolved_followup_codes.discard(stock.code)
            signal_tags: List[str] = []
            if not followup_only and hit_windows:
                signal_tags.append(f"EMA({', '.join([str(w) for w in hit_windows])})")
            if not followup_only and stress_hit:
                signal_tags.append(f"Stress({stress_hit_count}/4)")
            if followup_only:
                signal_tags.append("FollowUp(PreviousRunHit)")
            print(f"[SENT] {stock.code} {stock.name_zh}: {' + '.join(signal_tags)}")
        except Exception as exc:
            print(f"[ERROR] {stock.code} {stock.name_zh}: {exc}")

    next_pending_followup_codes = set(today_hit_codes) | unresolved_followup_codes
    save_alert_memory(memory_file, today_run_date, today_hit_codes, next_pending_followup_codes)

    if sent_total == 0:
        send_message(token, chat_id, "本次掃描完成：沒有商品符合 EMA 接近或風險 4 選 3 條件。")
    print(
        f"Done. Sent {sent_total} stock(s). "
        f"TodayTriggered={triggered_today}, FollowUpFromPreviousRun={followup_from_previous_run}."
    )


if __name__ == "__main__":
    main()
