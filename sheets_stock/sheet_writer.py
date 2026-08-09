"""Google スプレッドシートへの書き込み (gspread)。

認証は以下の優先順で解決する:
1. ``GOOGLE_SERVICE_ACCOUNT_JSON``     : 鍵 JSON の中身を直接渡す (GitHub Actions 向け)
2. ``GOOGLE_APPLICATION_CREDENTIALS``  : 鍵ファイルのパス
3. Google Colab のログイン資格情報 (Colab 上で 1・2 が未設定のとき自動検出)
4. gspread の既定 (~/.config/gspread/service_account.json)

Colab では ``analytics@spenda-c.com`` などユーザ自身の Google アカウントで認証でき、
サービスアカウントを用意せずに対象シートへ書き込める (書き込み先シートに編集権限が
必要)。書き込みは **1 回の update で一括上書き** (``value_input_option='USER_ENTERED'``
で数式を評価させる)。

多数の銘柄 (タブ) を 1 実行で書き込むと Google Sheets API の
「Write requests per minute per user」(60/分) 制限に達し 429 が返る。そのため
すべての変更系呼び出しを指数バックオフで再試行 (``_with_retry``) し、さらに 1 タブ
あたりの書き込み回数を最小化する (既存タブはサイズが同じなら update 1 回のみ)。
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Optional

import gspread
from gspread.exceptions import APIError
from gspread.utils import rowcol_to_a1

# 429/503 で再試行する回数と待機 (秒)。待機は 5,10,20,40,80… と指数増加。
# per-minute クォータのため、累積 60 秒超の待機で確実に窓がリセットされる。
_RETRY_TRIES = 7
_RETRY_BASE = 5
_RETRY_ON = {429, 500, 502, 503}


def _with_retry(fn, *args, **kwargs):
    """gspread の変更系呼び出しを 429/5xx で指数バックオフ再試行する。"""
    for attempt in range(_RETRY_TRIES):
        try:
            return fn(*args, **kwargs)
        except APIError as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in _RETRY_ON and attempt < _RETRY_TRIES - 1:
                wait = _RETRY_BASE * (2 ** attempt)
                print(
                    f"[retry] Sheets API {code} — {wait}s 待機して再試行 "
                    f"({attempt + 1}/{_RETRY_TRIES})",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            raise


def _colab_client() -> Optional[gspread.Client]:
    """Google Colab 上ならログイン資格情報で gspread クライアントを返す。

    Colab 以外、または認証に失敗した場合は None (呼び出し側で従来経路へ)。
    """
    try:
        from google.colab import auth as colab_auth  # type: ignore
        from google.auth import default as google_default
    except Exception:
        return None
    try:
        colab_auth.authenticate_user()
        creds, _ = google_default()
        return gspread.authorize(creds)
    except Exception:
        return None


def _client() -> gspread.Client:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        return gspread.service_account_from_dict(json.loads(raw))
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if path:
        return gspread.service_account(filename=path)
    colab = _colab_client()
    if colab is not None:
        return colab
    return gspread.service_account()  # 既定パス


def open_spreadsheet(spreadsheet_id: str, client: Optional[gspread.Client] = None):
    gc = client or _client()
    return _with_retry(gc.open_by_key, spreadsheet_id)


def write_matrix(spreadsheet, sheet_name: str, matrix: list[list]) -> str:
    """``matrix`` (ヘッダ+数式) を ``sheet_name`` タブへ一括書き込み。

    書き込み回数を抑えるため:
    - 既存タブでサイズが一致すれば ``update`` 1 回のみ (clear は行わない。
      同サイズを丸ごと上書きするので残存セルは発生しない)。
    - サイズが違う (行数変化・列不足) 場合のみ ``resize`` を挟む。
    - 新規タブは正しいサイズで ``add_worksheet`` してから ``update``。

    すべての変更系呼び出しは 429 バックオフ付き。戻り値は書き込み範囲 (A1 表記)。
    """
    n_rows = len(matrix)
    n_cols = max((len(r) for r in matrix), default=0)

    try:
        ws = _with_retry(spreadsheet.worksheet, sheet_name)
        # 余剰行の除去と列不足の拡張。サイズが一致していれば触らない (write 節約)。
        if ws.row_count != n_rows or ws.col_count < n_cols:
            _with_retry(ws.resize, rows=n_rows, cols=max(ws.col_count, n_cols))
    except gspread.WorksheetNotFound:
        ws = _with_retry(
            spreadsheet.add_worksheet,
            title=sheet_name,
            rows=n_rows,
            cols=max(n_cols, 26),
        )

    end_a1 = rowcol_to_a1(n_rows, n_cols)
    cell_range = f"A1:{end_a1}"
    _with_retry(ws.update, cell_range, matrix, value_input_option="USER_ENTERED")
    return cell_range
