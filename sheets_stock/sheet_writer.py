"""Google スプレッドシートへの書き込み (gspread)。

認証は以下の優先順で解決する:
1. ``GOOGLE_SERVICE_ACCOUNT_JSON``     : 鍵 JSON の中身を直接渡す (GitHub Actions 向け)
2. ``GOOGLE_APPLICATION_CREDENTIALS``  : 鍵ファイルのパス
3. Google Colab のログイン資格情報 (Colab 上で 1・2 が未設定のとき自動検出)
4. gspread の既定 (~/.config/gspread/service_account.json)

Colab では ``analytics@spenda-c.com`` などユーザ自身の Google アカウントで認証でき、
サービスアカウントを用意せずに対象シートへ書き込める (書き込み先シートに編集権限が
必要)。書き込みは Colab 事前検証の指針どおり **1 回の update で一括上書き**
(``value_input_option='USER_ENTERED'`` で数式を評価させる)。
"""
from __future__ import annotations

import json
import os
from typing import Optional

import gspread
from gspread.utils import rowcol_to_a1


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
    return gc.open_by_key(spreadsheet_id)


def _get_or_create_worksheet(spreadsheet, title: str, rows: int, cols: int):
    try:
        ws = spreadsheet.worksheet(title)
        ws.clear()  # 既存データを消してから書き直す
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=max(rows, 100), cols=max(cols, 26))
    # 既存タブは書き込む行数に足りるようグリッドを広げる (update は自動拡張しない)。
    if ws.row_count < rows or ws.col_count < cols:
        ws.resize(rows=max(ws.row_count, rows), cols=max(ws.col_count, cols))
    return ws


def write_matrix(spreadsheet, sheet_name: str, matrix: list[list]) -> str:
    """``matrix`` (ヘッダ+データ) を ``sheet_name`` タブへ一括書き込み。

    戻り値は書き込んだセル範囲 (A1 表記)。
    """
    n_rows = len(matrix)
    n_cols = max((len(r) for r in matrix), default=0)
    ws = _get_or_create_worksheet(spreadsheet, sheet_name, n_rows + 10, n_cols)

    end_a1 = rowcol_to_a1(n_rows, n_cols)
    cell_range = f"A1:{end_a1}"
    ws.update(cell_range, matrix, value_input_option="USER_ENTERED")
    return cell_range
