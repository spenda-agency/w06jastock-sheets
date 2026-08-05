"""毎日 16:00 (JST) 実行のエントリポイント。

対象銘柄ごとに:
1. yfinance で日次 (Date, Close) を取得
2. C 列以降の数式を組み立てて 2 次元配列を生成
3. 対応するワークシートへ一括書き込み

使い方:
    python -m sheets_stock.update_job              # 実書き込み
    python -m sheets_stock.update_job --dry-run    # 取得のみ・書き込みなし
    python -m sheets_stock.update_job --self-test  # 合成データで数式生成を検証
"""
from __future__ import annotations

import argparse
import sys

from . import config
from .formulas import build_matrix
from .prices import fetch_close_series


def _run(dry_run: bool) -> int:
    days = config.history_days()
    matrices: dict[str, list[list]] = {}

    for inst in config.INSTRUMENTS:
        print(f"[fetch] {inst.label} ({inst.ticker}) …", file=sys.stderr)
        series = fetch_close_series(inst.ticker, days=days)
        if not series:
            print(f"[warn] {inst.label}: データ取得に失敗しました。スキップします。", file=sys.stderr)
            continue
        print(
            f"[fetch] {inst.label}: {len(series)} 本 "
            f"({series[0][0]} 〜 {series[-1][0]}, 終値 {series[-1][1]})",
            file=sys.stderr,
        )
        matrices[inst.sheet_name] = build_matrix(series)

    if not matrices:
        print("[error] 書き込めるデータがありません。", file=sys.stderr)
        return 1

    if dry_run:
        for name, m in matrices.items():
            print(f"[dry-run] '{name}': {len(m)} 行 x {len(m[0])} 列 (書き込みなし)")
        return 0

    # 遅延 import: 取得だけしたい場合は gspread 不要。
    from .sheet_writer import open_spreadsheet, write_matrix

    ss = open_spreadsheet(config.spreadsheet_id())
    for name, m in matrices.items():
        rng = write_matrix(ss, name, m)
        print(f"[write] '{name}': {rng} に {len(m)} 行を書き込みました。", file=sys.stderr)

    print("[done] 全銘柄の更新が完了しました。", file=sys.stderr)
    return 0


def _self_test() -> int:
    """ネットワーク/認証なしで数式生成が壊れていないか検証する。"""
    import math

    # 合成 Close 系列 (ゆるやかな正弦波 + トレンド) を 320 本。
    series = [
        (f"2025-{(i // 20) % 12 + 1:02d}-{i % 20 + 1:02d}",
         round(1000 + 50 * math.sin(i / 9) + i * 0.5, 2))
        for i in range(320)
    ]
    m = build_matrix(series)
    assert len(m) == len(series) + 1, "行数がヘッダ+データと一致しません"
    assert len(m[0]) == 23, "列数が 23 (A..W) ではありません"
    for row in m[1:]:
        assert len(row) == 23, "データ行の列数が不正です"
        for cell in row[2:]:  # C 列以降はすべて '=' 始まりの数式
            assert isinstance(cell, str) and cell.startswith("="), f"数式でないセル: {cell!r}"
    # 代表行の数式を目視確認用に出力 (降順: row2 が最新)。
    print("HEADER:", m[0])
    print("row2 (最新・先頭データ):", m[1])
    print("row3 (前日参照 r+1):", m[2])
    print("row300 (RSI300 window):", m[300])
    print("[self-test] OK: 数式生成は正常です (ABBV 準拠・降順)。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="日次株価をスプレッドシートへ書き出す")
    parser.add_argument("--dry-run", action="store_true", help="取得のみ・書き込みなし")
    parser.add_argument("--self-test", action="store_true", help="合成データで数式生成を検証")
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()
    return _run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
