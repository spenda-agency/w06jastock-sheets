"""スプレッドシートの数式列 (C 列以降) を組み立てる。

要件:「Date・Close の次の C 列より右はスプレッドシートの数式で出せる」。
本モジュールは各データ行に入れる数式文字列を生成し、Python 側は Date/Close
だけを値として書き込む。

列レイアウト (ヘッダは 1 行目、データは 2 行目から):

| 列 | ヘッダ                 | 内容                                             |
|----|------------------------|--------------------------------------------------|
| A  | Date                   | 日付 (値)                                        |
| B  | Close                  | 終値 (値)                                        |
| C  | IF($C3>=0,$C3,0)       | 上昇幅 gain = 直近差(E)が+なら直近差, 他は0      |
| D  | IF($C3>=0,0,-$C3)      | 下落幅 loss = 直近差(E)が+なら0, 他は-直近差     |
| E  | 直近差                 | 前日終値との差 = B(r) - B(r-1)                    |
| F  | RSI14                  | 100-100/(1+平均gain14/平均loss14)                |
| G  | RSI30                  | 同上 30 期間                                     |
| H  | RSI45                  | 同上 45 期間                                     |
| I  | RSI100                 | 同上 100 期間                                    |
| J  | RSI300                 | 同上 300 期間                                    |
| K  | RSI判断                | RSI14>=70:売 / <=30:買 / それ以外:△              |
| L  | ボリジャー上限         | 20SMA + 2σ                                       |
| M  | ボリジャー下限         | 20SMA - 2σ                                       |
| N  | EMA12                  | 指数平滑 (adjust=False 相当, 前行参照)           |
| O  | EMA26                  | 同上 26                                          |
| P  | MACD                   | EMA12 - EMA26                                     |
| Q  | シグナル線9日          | MACD の EMA9 (前行参照)                          |
| R  | MACDクロス             | ゴールデン/デッド (差 S の符号反転を検出)        |
| S  | MACDクロス差           | MACD - シグナル線                                |
| T  | MA3                    | 終値 3 期間単純移動平均                          |
| U  | MA5                    | 5 期間                                           |
| V  | MA10                   | 10 期間                                          |
| W  | MA200                  | 200 期間                                         |

備考: ユーザ提示のヘッダでは C/D 列の数式が ``$C3`` を参照しているが、
上昇幅/下落幅は「直近差」を基に算出するのが指標の定義であり、直近差は
本レイアウトでは E 列にあたる。列の並び順はユーザ提示どおりに保ちつつ、
参照先だけを直近差 (E 列) に合わせて整合させている。
"""
from __future__ import annotations

from .config import BOLLINGER_PERIOD, FIRST_DATA_ROW

# ユーザ提示のヘッダ行をそのまま採用 (A..W)。
HEADER: list[str] = [
    "Date",
    "Close",
    "IF($C3>=0,$C3,0)",
    "IF($C3>=0,0,-$C3)",
    "直近差",
    "RSI14",
    "RSI30",
    "RSI45",
    "RSI100",
    "RSI300",
    "RSI判断",
    "ボリジャー上限",
    "ボリジャー下限",
    "EMA12",
    "EMA26",
    "MACD",
    "シグナル線9日",
    "MACDクロス",
    "MACDクロス差",
    "MA3",
    "MA5",
    "MA10",
    "MA200",
]

# EMA 平滑係数 (adjust=False: 前行 EMA と当日 Close の加重平均)。
_EMA12_K = 2 / (12 + 1)
_EMA26_K = 2 / (26 + 1)
_SIGNAL_K = 2 / (9 + 1)


def _rsi(gain_col: str, loss_col: str, period: int, r: int) -> str:
    """r 行目の RSI 数式。直近 ``period`` 本の gain/loss 平均から算出。

    十分な本数がそろう行 (最初の直近差は 3 行目) からのみ計算し、
    それ以前は空欄。損失平均が 0 の場合は RSI=100。
    """
    # 直近差は FIRST_DATA_ROW+1 行目 (=3) から。period 本そろう最初の行:
    first_valid = FIRST_DATA_ROW + 1 + (period - 1)
    # 先頭付近の行では top が 1 未満になり得る。IF ガードで値は使われないが、
    # 数式文字列自体は正しい A1 参照でなければ #REF! になるため 1 行目 (ヘッダ=
    # 文字列で AVERAGE 対象外) にクランプする。
    top = max(r - period + 1, 1)
    avg_gain = f"AVERAGE(${gain_col}{top}:${gain_col}{r})"
    avg_loss = f"AVERAGE(${loss_col}{top}:${loss_col}{r})"
    return (
        f'=IF(ROW()<{first_valid},"",'
        f"IF({avg_loss}=0,100,"
        f"100-100/(1+{avg_gain}/{avg_loss})))"
    )


def _sma(col: str, period: int, r: int) -> str:
    first_valid = FIRST_DATA_ROW + (period - 1)
    top = max(r - period + 1, 1)  # ヘッダ行へクランプ (A1 参照を有効に保つ)
    return f'=IF(ROW()<{first_valid},"",AVERAGE(${col}{top}:${col}{r}))'


def _ema(col: str, price_col: str, k: float, r: int) -> str:
    """adjust=False の EMA。初回行は Close をシードにし、以降は前行参照。"""
    if r == FIRST_DATA_ROW:
        return f"=${price_col}{r}"
    return (
        f"=${price_col}{r}*{k:.10f}+${col}{r - 1}*{1 - k:.10f}"
    )


def build_row_formulas(r: int) -> list[str]:
    """データ行 ``r`` (>= FIRST_DATA_ROW) の C..W 列数式を返す (21 要素)。"""
    prev = r - 1
    diff_first = FIRST_DATA_ROW + 1  # 直近差が計算できる最初の行 (=3)

    # C 上昇幅 / D 下落幅 (直近差 E を参照)
    gain = f'=IF($E{r}="","",IF($E{r}>=0,$E{r},0))'
    loss = f'=IF($E{r}="","",IF($E{r}>=0,0,-$E{r}))'
    # E 直近差
    diff = f'=IF(ROW()<{diff_first},"",$B{r}-$B{prev})'

    # F..J RSI (gain=C, loss=D)
    rsi14 = _rsi("C", "D", 14, r)
    rsi30 = _rsi("C", "D", 30, r)
    rsi45 = _rsi("C", "D", 45, r)
    rsi100 = _rsi("C", "D", 100, r)
    rsi300 = _rsi("C", "D", 300, r)

    # K RSI判断 (RSI14 = F 列)
    rsi_judge = (
        f'=IF($F{r}="","",IF($F{r}>=70,"売",IF($F{r}<=30,"買","△")))'
    )

    # L/M ボリンジャーバンド (20SMA ± 2σ, 母集団標準偏差)
    bb_first = FIRST_DATA_ROW + (BOLLINGER_PERIOD - 1)
    bb_top = max(r - BOLLINGER_PERIOD + 1, 1)  # ヘッダ行へクランプ
    bb_mid = f"AVERAGE($B{bb_top}:$B{r})"
    bb_sd = f"STDEVP($B{bb_top}:$B{r})"
    bb_upper = f'=IF(ROW()<{bb_first},"",{bb_mid}+2*{bb_sd})'
    bb_lower = f'=IF(ROW()<{bb_first},"",{bb_mid}-2*{bb_sd})'

    # N/O EMA, P MACD, Q シグナル, R クロス, S クロス差
    ema12 = _ema("N", "B", _EMA12_K, r)
    ema26 = _ema("O", "B", _EMA26_K, r)
    macd = f"=$N{r}-$O{r}"
    signal = (
        f"=$P{r}" if r == FIRST_DATA_ROW
        else f"=$P{r}*{_SIGNAL_K:.10f}+$Q{prev}*{1 - _SIGNAL_K:.10f}"
    )
    macd_diff = f"=$P{r}-$Q{r}"  # S 列
    if r <= FIRST_DATA_ROW:
        macd_cross = '=""'
    else:
        macd_cross = (
            f'=IF(AND($S{prev}<=0,$S{r}>0),"ゴールデン",'
            f'IF(AND($S{prev}>=0,$S{r}<0),"デッド",""))'
        )

    # T..W 移動平均
    ma3 = _sma("B", 3, r)
    ma5 = _sma("B", 5, r)
    ma10 = _sma("B", 10, r)
    ma200 = _sma("B", 200, r)

    return [
        gain, loss, diff,
        rsi14, rsi30, rsi45, rsi100, rsi300, rsi_judge,
        bb_upper, bb_lower,
        ema12, ema26, macd, signal, macd_cross, macd_diff,
        ma3, ma5, ma10, ma200,
    ]


def build_matrix(series: list[tuple[str, float]]) -> list[list]:
    """ヘッダ + 全データ行 (値 A/B + 数式 C..W) の 2 次元配列を返す。

    ``series`` は (日付, 終値) の昇順リスト。
    """
    matrix: list[list] = [HEADER]
    for i, (date_str, close) in enumerate(series):
        r = FIRST_DATA_ROW + i
        matrix.append([date_str, close, *build_row_formulas(r)])
    return matrix
