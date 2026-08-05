"""ジョブ全体の設定と対象銘柄の定義。

対象銘柄はリポジトリ直下の ``tickers.csv`` で管理する (GitHub 上で 1 行足すだけで
追加できる)。CSV が無い/空の場合は下記の組み込み ``INSTRUMENTS`` にフォールバック。

環境変数で上書きできる箇所:
- ``SPREADSHEET_ID``            : 書き込み先スプレッドシート ID
- ``GOOGLE_SERVICE_ACCOUNT_JSON``: サービスアカウント鍵 (JSON 文字列)
- ``GOOGLE_APPLICATION_CREDENTIALS``: サービスアカウント鍵ファイルのパス
- ``HISTORY_DAYS``             : 取得する日次データの本数 (既定 800 営業日相当)
- ``TICKERS_FILE``             : 銘柄 CSV のパス (既定 リポジトリ直下 tickers.csv)
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass


# 既定の書き込み先。ユーザ提供の URL:
#   https://docs.google.com/spreadsheets/d/1Zivd5Dorzc_fnwYF0gt5QSliq1MwLs6ZntNmt3AyeD4/edit
DEFAULT_SPREADSHEET_ID = "1Zivd5Dorzc_fnwYF0gt5QSliq1MwLs6ZntNmt3AyeD4"

# ヘッダ行は 1 行目、データは 2 行目 (=FIRST_DATA_ROW) から。
# データは ABBV に合わせて降順 (新しい日付が上) で書き込む。
FIRST_DATA_ROW = 2


@dataclass(frozen=True)
class Instrument:
    """1 ワークシートに対応する銘柄定義。"""

    #: yfinance 用ティッカー (指数は ^N225、東証個別株は "7203.T" 形式)
    ticker: str
    #: 書き込み先ワークシート (タブ) 名
    sheet_name: str
    #: 表示用ラベル (ログ等)
    label: str


# 今回対象とする銘柄。まずは日経平均225 とトヨタの 2 銘柄を 1 シートずつ。
# タブ名 (sheet_name) は既存タブ「ABBV」に倣い銘柄コードに合わせる。
# 日経平均インデックスには 4 桁コードが無いため、ティッカー ^N225 に倣い "N225"。
INSTRUMENTS: list[Instrument] = [
    Instrument(ticker="^N225", sheet_name="N225", label="日経平均株価 (Nikkei 225)"),
    Instrument(ticker="7203.T", sheet_name="7203", label="トヨタ自動車 (7203)"),
]


# リポジトリ直下の tickers.csv (このファイル = sheets_stock/config.py の 1 つ上)。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TICKERS_FILE = os.path.join(_REPO_ROOT, "tickers.csv")


def _derive_sheet_name(ticker: str) -> str:
    """ティッカーからタブ名を導出 (先頭 '^' と末尾 '.T' を除去)。"""
    name = ticker.strip()
    if name.startswith("^"):
        name = name[1:]
    if name.lower().endswith(".t"):
        name = name[:-2]
    return name


def load_instruments(path: str | None = None) -> list[Instrument]:
    """``tickers.csv`` を読み対象銘柄を返す。無い/空なら組み込み既定へフォールバック。

    CSV 列: ``ticker`` (必須), ``sheet_name`` (任意), ``label`` (任意)。
    ``sheet_name`` 空欄は ticker から自動導出、``label`` 空欄は ticker を使用。
    ``#`` 始まりの行・空行は無視。
    """
    csv_path = path or os.environ.get("TICKERS_FILE") or DEFAULT_TICKERS_FILE
    if not os.path.exists(csv_path):
        return list(INSTRUMENTS)

    instruments: list[Instrument] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            first = row[0].strip()
            if not first or first.startswith("#"):
                continue
            if first.lower() == "ticker":  # ヘッダ行
                continue
            ticker = first
            sheet_name = (row[1].strip() if len(row) > 1 else "") or _derive_sheet_name(ticker)
            label = (row[2].strip() if len(row) > 2 else "") or ticker
            instruments.append(Instrument(ticker=ticker, sheet_name=sheet_name, label=label))

    return instruments or list(INSTRUMENTS)


def spreadsheet_id() -> str:
    # 空文字 (CI で未設定の vars が空で渡るケース) は既定にフォールバック。
    return os.environ.get("SPREADSHEET_ID") or DEFAULT_SPREADSHEET_ID


def history_days() -> int:
    try:
        return int(os.environ.get("HISTORY_DAYS", "800"))
    except ValueError:
        return 800
