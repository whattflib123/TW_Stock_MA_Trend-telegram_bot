#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

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


@dataclass(frozen=True)
class AppConfig:
    ema_tolerance: float
    detection_ema_windows: List[int]
    chart_ema_windows: List[int]
    stocks: List[StockItem]


def load_config(config_path: Path) -> AppConfig:
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    stocks: List[StockItem] = []
    for item in raw.get("stocks", []):
        stocks.append(
            StockItem(
                code=str(item["code"]),
                name_zh=str(item["name_zh"]),
                yf_symbol=str(item["yf_symbol"]),
            )
        )

    detection = [int(x) for x in raw.get("detection_ema_windows", [50, 200, 576])]
    chart = [int(x) for x in raw.get("chart_ema_windows", [50, 200, 576, 676])]
    tolerance = float(raw.get("ema_tolerance", 0.01))

    if not stocks:
        raise ValueError("config stocks is empty")
    if not detection:
        raise ValueError("config detection_ema_windows is empty")
    if not chart:
        raise ValueError("config chart_ema_windows is empty")
    if tolerance <= 0:
        raise ValueError("config ema_tolerance must be positive")

    return AppConfig(
        ema_tolerance=tolerance,
        detection_ema_windows=detection,
        chart_ema_windows=chart,
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


def main() -> None:
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    config_file = Path(os.getenv("CONFIG_FILE", "config.json"))
    chart_dir = Path(os.getenv("CHART_DIR", "charts"))
    chart_dir.mkdir(parents=True, exist_ok=True)
    cleanup_old_charts(chart_dir)

    if not token or not chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

    config = load_config(config_file)
    triggered = 0

    for stock in config.stocks:
        try:
            raw_df = fetch_daily_history(stock.yf_symbol)
            df = add_ema_columns(raw_df, config.chart_ema_windows)
            latest = df.iloc[-1]
            latest_date = pd.Timestamp(df.index[-1]).date().isoformat()

            hit_windows = near_ema_list(
                latest, tolerance=config.ema_tolerance, ema_windows=config.detection_ema_windows
            )
            if not hit_windows:
                continue

            close_price = float(latest["Close"])
            ema50 = float(latest["EMA50"])
            ema200 = float(latest["EMA200"])
            bullish = "是" if ema50 > ema200 else "否"

            near_text = ", ".join([f"EMA{w}" for w in hit_windows])
            caption = (
                f"{stock.code} {stock.name_zh}\n"
                f"日期: {latest_date}\n"
                f"收盤價: {close_price:.2f}\n"
                f"接近均線: {near_text} (±{config.ema_tolerance * 100:.1f}%)\n"
                f"EMA50/EMA200 多頭排列: {bullish}"
            )

            daily_chart_path = chart_dir / f"{stock.code}_{latest_date}_daily.png"
            weekly_chart_path = chart_dir / f"{stock.code}_{latest_date}_weekly.png"
            create_daily_chart(df, stock, daily_chart_path, config.chart_ema_windows)
            create_weekly_chart(df, stock, weekly_chart_path, config.chart_ema_windows)
            send_photo(token, chat_id, daily_chart_path, caption + "\n圖表: 近一年日K")
            send_photo(token, chat_id, weekly_chart_path)
            triggered += 1
            print(f"[SENT] {stock.code} {stock.name_zh}: {near_text}")
        except Exception as exc:
            print(f"[ERROR] {stock.code} {stock.name_zh}: {exc}")

    if triggered == 0:
        send_message(token, chat_id, "本次掃描完成：沒有商品符合 EMA 接近條件。")
    print(f"Done. Triggered {triggered} stock(s).")


if __name__ == "__main__":
    main()
