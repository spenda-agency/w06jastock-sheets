"""ジョブ全体の設定と対象銘柄の定義。

環境変数で上書きできる箇所:
- ``SPREADSHEET_ID``            : 書き込み先スプレッドシート ID
- ``GOOGLE_SERVICE_ACCOUNT_JSON``: サービスアカウント鍵 (JSON 文字列)
- ``GOOGLE_APPLICATION_CREDENTIALS``: サービスアカウント鍵ファイルのパス
- ``HISTORY_DAYS``             : 取得する日次データの本数 (既定 800 営業日相当)
"""
from __future__ import annotations

import os
from dataclasses import dataclass


# 既定の書き込み先。ユーザ提供の URL:
#   https://docs.google.com/spreadsheets/d/1Zivd5Dorzc_fnwYF0gt5QSliq1MwLs6ZntNmt3AyeD4/edit
DEFAULT_SPREADSHEET_ID = "1Zivd5Dorzc_fnwYF0gt5QSliq1MwLs6ZntNmt3AyeD4"

# ボリンジャーバンドの期間 (標準的な 20 期間・±2σ)。
BOLLINGER_PERIOD = 20

# ヘッダ行は 1 行目、データは 2 行目 (=FIRST_DATA_ROW) から。
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
INSTRUMENTS: list[Instrument] = [
    Instrument(ticker="^N225", sheet_name="日経平均225", label="日経平均株価 (Nikkei 225)"),
    Instrument(ticker="7203.T", sheet_name="トヨタ", label="トヨタ自動車 (7203)"),
]


def spreadsheet_id() -> str:
    # 空文字 (CI で未設定の vars が空で渡るケース) は既定にフォールバック。
    return os.environ.get("SPREADSHEET_ID") or DEFAULT_SPREADSHEET_ID


def history_days() -> int:
    try:
        return int(os.environ.get("HISTORY_DAYS", "800"))
    except ValueError:
        return 800
