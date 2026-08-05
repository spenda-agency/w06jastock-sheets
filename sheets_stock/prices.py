"""日次 Close 時系列の取得 (yfinance)。

姉妹リポジトリ ``jastock`` の ``backend/prices.py`` と同じく yfinance を
既定バックエンドにする。本ジョブが必要とするのは **日付と終値のみ** なので、
戻り値は ``[(date_str, close_float), ...]`` の素直なリストに正規化する。

指数 (^N225) と個別株 (7203.T) の両方を同じ関数で扱える。
"""
from __future__ import annotations

from datetime import datetime, timedelta

try:
    import yfinance as yf
except Exception:  # pragma: no cover - 実行環境で pip install される
    yf = None  # type: ignore


def fetch_close_series(ticker: str, days: int = 800) -> list[tuple[str, float]]:
    """``ticker`` の直近 ``days`` 営業日分の (日付, 終値) を返す。

    - 日付は昇順 (古い → 新しい)、``YYYY-MM-DD`` 文字列。
    - 欠損日 (NaN) は除外する。
    - 取得失敗時は空リストを返す (呼び出し側でスキップ判定)。
    """
    if yf is None:
        raise RuntimeError(
            "yfinance がインストールされていません。`pip install -r requirements.txt` を実行してください。"
        )

    end = datetime.utcnow() + timedelta(days=1)  # 当日分も含める余裕
    # 営業日換算で days 本を確保するため、暦日ではやや多めに遡る。
    start = end - timedelta(days=int(days * 1.6) + 40)

    df = yf.download(
        ticker,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval="1d",
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    if df is None or df.empty:
        return []

    # yfinance は単一銘柄でも MultiIndex 列を返すことがある。
    close = df["Close"]
    if hasattr(close, "columns"):  # DataFrame (MultiIndex) の場合
        close = close.iloc[:, 0]

    series: list[tuple[str, float]] = []
    for idx, value in close.items():
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if v != v:  # NaN 判定
            continue
        series.append((idx.strftime("%Y-%m-%d"), round(v, 2)))

    # 念のため日付昇順に整えて末尾 days 本へ。
    series.sort(key=lambda r: r[0])
    return series[-days:]
