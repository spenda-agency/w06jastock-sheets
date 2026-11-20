"""日次 Close 時系列の取得 (J-Quants API **V2**)。

データ源を Yahoo Finance から J-Quants API V2 に変更。V2 はダッシュボード発行の
**API キー** 方式 (``x-api-key`` ヘッダー、無期限)。本ジョブが必要とするのは
日付と終値のみなので、戻り値は従来どおり ``[(date_str, close_float), ...]``。

  - ベース URL : https://api.jquants.com/v2  (環境変数 JQUANTS_BASE_URL で上書き可)
  - 四本値     : GET /v2/equities/bars/daily  (code か date 必須、from/to 可)
  - 認証       : ヘッダ ``x-api-key: <API キー>`` (環境変数 JQUANTS_API_KEY)
  - 銘柄コード : 5桁 (7203 → 72030)。ティッカー "7203.T" は ".T" を除去して変換。
  - レスポンス : ``data`` 配列。終値は調整後 (AdjustmentClose) を優先。

指数シンボル (^N225 等) は J-Quants に無いため空リストを返す (呼び出し側でスキップ)。
TOPIX 等の連動 ETF (1306.T 等) は通常の上場銘柄なので取得できる。
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

_BASE = (os.environ.get("JQUANTS_BASE_URL") or "https://api.jquants.com/v2").rstrip("/")
_TIMEOUT = 30
_RETRY_TRIES = 5
_RETRY_BASE = 3
_RETRY_ON = {429, 500, 502, 503, 504}

_API_KEY: Optional[str] = None
_logged_cols = False


class JQuantsError(RuntimeError):
    pass


def _clean(v: Optional[str]) -> str:
    t = (v or "").strip().strip('"').strip("'")
    return "".join(t.split())


def _api_key() -> str:
    global _API_KEY
    if _API_KEY is not None:
        return _API_KEY
    key = _clean(os.environ.get("JQUANTS_API_KEY"))
    if not key:
        raise JQuantsError(
            "JQUANTS_API_KEY が未設定です。J-Quants V2 ダッシュボードで発行した "
            "API キーを設定してください。"
        )
    _API_KEY = key
    return key


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


def _to_code5(ticker: str) -> Optional[str]:
    """yfinance ティッカーを J-Quants V2 の 5桁コードに変換。指数 (^...) は None。"""
    t = ticker.strip()
    if not t or t.startswith("^"):
        return None
    if t.lower().endswith(".t"):
        t = t[:-2]
    return t + "0" if len(t) == 4 else t


def _extract_records(body: dict):
    for k in ("data", "daily_quotes", "bars", "quotes"):
        v = body.get(k)
        if isinstance(v, list):
            return v
    for v in body.values():
        if isinstance(v, list):
            return v
    return []


def _pick(row: dict, *names):
    for n in names:
        v = row.get(n)
        if v is not None:
            return v
    return None


def fetch_close_series(ticker: str, days: int = 800) -> list[tuple[str, float]]:
    """``ticker`` の直近 ``days`` 営業日分の (日付, 終値) を返す。

    - 日付は昇順、``YYYY-MM-DD``。欠損は除外。終値は調整後終値を優先。
    - 指数 (^N225 等) や取得不能時は空リスト (呼び出し側でスキップ)。
    """
    code5 = _to_code5(ticker)
    if code5 is None:
        print(f"[jquants] {ticker}: 指数は J-Quants 非対応のためスキップ。", file=sys.stderr)
        return []

    headers = {"x-api-key": _api_key()}
    end = datetime.utcnow() + timedelta(days=1)
    start = end - timedelta(days=int(days * 1.6) + 40)
    base = {"from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d")}

    def _fetch(code_param: str) -> list[dict]:
        params = dict(base, code=code_param)
        rows: list[dict] = []
        while True:
            resp = _request("GET", f"{_BASE}/equities/bars/daily",
                            headers=headers, params=params)
            body = resp.json()
            rows.extend(_extract_records(body))
            pk = body.get("pagination_key")
            if not pk:
                break
            params = dict(params, pagination_key=pk)
        return rows

    rows = _fetch(code5)
    if not rows and code5 != ticker.strip().rstrip(".Tt"):
        # 5桁で空なら元の桁でも試す (保険)
        raw = ticker.strip()
        raw = raw[:-2] if raw.lower().endswith(".t") else raw
        if raw and raw != code5:
            rows = _fetch(raw)
    if not rows:
        return []

    global _logged_cols
    if not _logged_cols:
        print(f"[jquants] V2 応答カラム: {sorted(rows[0].keys())}", file=sys.stderr)
        _logged_cols = True

    series: list[tuple[str, float]] = []
    for r in rows:
        d = _pick(r, "Date", "date", "Day")
        c = _pick(r, "AdjustmentClose", "AdjClose", "AdjC", "Close", "C")
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
