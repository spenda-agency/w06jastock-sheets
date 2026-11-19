"""日次 Close 時系列の取得 (J-Quants API)。

データ源を Yahoo Finance (yfinance) から **J-Quants API** に変更。
本ジョブが必要とするのは **日付と終値のみ** なので、戻り値は従来どおり
``[(date_str, close_float), ...]`` に正規化する (呼び出し側は無変更)。

J-Quants の認証は リフレッシュトークン → IDトークン → ``Authorization: Bearer``。
IDトークンは全銘柄で使い回すためモジュール内にキャッシュする。

認証情報 (環境変数・いずれか):
  - JQUANTS_ID_TOKEN      … IDトークンを直接指定 (24時間有効)
  - JQUANTS_REFRESH_TOKEN … リフレッシュトークン (1週間有効・推奨)
  - JQUANTS_MAILADDRESS + JQUANTS_PASSWORD … メール/パスワード (Google連携は不可)

指数シンボル (^N225 等) は J-Quants には存在しないため空リストを返す
(呼び出し側でスキップ)。TOPIX 等の連動 ETF (1306.T 等) は通常の上場銘柄
なので取得できる。
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

_BASE = (os.environ.get("JQUANTS_BASE_URL") or "https://api.jquants.com/v1").rstrip("/")
_TIMEOUT = 30
_RETRY_TRIES = 5
_RETRY_BASE = 3
_RETRY_ON = {429, 500, 502, 503, 504}

# 全銘柄で使い回す IDトークン (と取得失敗) のキャッシュ。
_ID_TOKEN: Optional[str] = None
_AUTH_ERROR: Optional[Exception] = None
_logged_cols = False


def _clean(v: Optional[str]) -> str:
    t = (v or "").strip().strip('"').strip("'").strip()
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    return "".join(t.split())


class JQuantsError(RuntimeError):
    pass


def _body_snippet(resp: requests.Response) -> str:
    try:
        return resp.text[:300].replace("\n", " ")
    except Exception:  # noqa: BLE001
        return "<本文取得不可>"


def _request(method: str, url: str, **kwargs) -> requests.Response:
    last: Optional[requests.Response] = None
    for attempt in range(_RETRY_TRIES):
        resp = requests.request(method, url, timeout=_TIMEOUT, **kwargs)
        last = resp
        if resp.status_code < 400:
            return resp
        if resp.status_code in _RETRY_ON and attempt < _RETRY_TRIES - 1:
            wait = _RETRY_BASE * (2 ** attempt)
            print(f"[jquants] {resp.status_code} — {wait}s 待機して再試行 "
                  f"({attempt + 1}/{_RETRY_TRIES})", file=sys.stderr)
            time.sleep(wait)
            continue
        break
    raise JQuantsError(
        f"{last.status_code} {last.reason} — {method} {url.split('?')[0]} "
        f":: {_body_snippet(last)}"
    )


def _acquire_id_token() -> str:
    direct = _clean(os.environ.get("JQUANTS_ID_TOKEN"))
    if direct:
        print("[jquants] JQUANTS_ID_TOKEN を直接使用。", file=sys.stderr)
        return direct

    refresh = _clean(os.environ.get("JQUANTS_REFRESH_TOKEN"))
    mail = (os.environ.get("JQUANTS_MAILADDRESS") or "").strip()
    pw = os.environ.get("JQUANTS_PASSWORD") or ""
    errors: list[str] = []

    if mail and pw:
        try:
            r = _request("POST", f"{_BASE}/token/auth_user",
                         json={"mailaddress": mail, "password": pw})
            rt = _clean(r.json().get("refreshToken"))
            if rt:
                refresh = rt
                print("[jquants] auth_user でリフレッシュトークン取得。", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            errors.append(f"auth_user: {e}")

    if refresh:
        try:
            r = _request("POST", f"{_BASE}/token/auth_refresh",
                         params={"refreshtoken": refresh})
            idt = _clean(r.json().get("idToken"))
            if idt:
                print("[jquants] auth_refresh で IDトークン取得。", file=sys.stderr)
                return idt
            errors.append("auth_refresh: 応答に idToken なし")
        except Exception as e:  # noqa: BLE001
            errors.append(f"auth_refresh: {e}")

    raise JQuantsError(
        "IDトークンを取得できませんでした。Web マイページで新しいリフレッシュトークン"
        "(1週間有効) を取得し JQUANTS_REFRESH_TOKEN に設定してください。詳細: "
        + " | ".join(errors or ["認証情報が未設定"])
    )


def _id_token() -> str:
    """IDトークンを取得 (初回のみ認証、以降キャッシュ)。失敗もキャッシュして即再送出。"""
    global _ID_TOKEN, _AUTH_ERROR
    if _ID_TOKEN is not None:
        return _ID_TOKEN
    if _AUTH_ERROR is not None:
        raise _AUTH_ERROR
    try:
        _ID_TOKEN = _acquire_id_token()
        return _ID_TOKEN
    except Exception as e:  # noqa: BLE001
        _AUTH_ERROR = e
        raise


def _to_code(ticker: str) -> Optional[str]:
    """yfinance ティッカーを J-Quants コードに変換。指数 (^...) は None。"""
    t = ticker.strip()
    if not t or t.startswith("^"):
        return None  # 指数は J-Quants に無い
    if t.lower().endswith(".t"):
        t = t[:-2]
    return t


def _pick(row: dict, *names):
    for n in names:
        v = row.get(n)
        if v is not None:
            return v
    return None


def fetch_close_series(ticker: str, days: int = 800) -> list[tuple[str, float]]:
    """``ticker`` の直近 ``days`` 営業日分の (日付, 終値) を返す。

    - 日付は昇順、``YYYY-MM-DD``。欠損は除外。
    - 指数 (^N225 等) や取得不能時は空リスト (呼び出し側でスキップ)。
    - 終値は調整後終値 (AdjustmentClose) を優先。
    """
    code = _to_code(ticker)
    if code is None:
        print(f"[jquants] {ticker}: 指数は J-Quants 非対応のためスキップ。", file=sys.stderr)
        return []

    token = _id_token()
    headers = {"Authorization": f"Bearer {token}"}

    end = datetime.utcnow() + timedelta(days=1)
    start = end - timedelta(days=int(days * 1.6) + 40)
    params_base = {
        "from": start.strftime("%Y-%m-%d"),
        "to": end.strftime("%Y-%m-%d"),
    }

    def _fetch(code_param: str) -> list[dict]:
        params = dict(params_base, code=code_param)
        rows: list[dict] = []
        while True:
            resp = _request("GET", f"{_BASE}/prices/daily_quotes",
                            headers=headers, params=params)
            body = resp.json()
            recs = body.get("daily_quotes")
            if isinstance(recs, list):
                rows.extend(recs)
            pk = body.get("pagination_key")
            if not pk:
                break
            params = dict(params, pagination_key=pk)
        return rows

    rows = _fetch(code)
    if not rows and code.isdigit() and len(code) == 4:
        rows = _fetch(code + "0")  # 4桁→5桁フォールバック
    if not rows:
        return []

    global _logged_cols
    if not _logged_cols:
        print(f"[jquants] 応答カラム: {sorted(rows[0].keys())}", file=sys.stderr)
        _logged_cols = True

    series: list[tuple[str, float]] = []
    for r in rows:
        d = _pick(r, "Date", "date")
        c = _pick(r, "AdjustmentClose", "Close", "C")
        if d is None or c is None:
            continue
        try:
            v = float(c)
        except (TypeError, ValueError):
            continue
        if v != v:  # NaN
            continue
        series.append((str(d)[:10], round(v, 2)))

    series.sort(key=lambda x: x[0])
    return series[-days:]
