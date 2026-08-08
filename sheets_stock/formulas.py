"""スプレッドシートの数式列 (C 列以降) を組み立てる。

数式は既存タブ **「ABBV」** に記載済みの定義に厳密に合わせる。ABBV の設計上の要点:

- データは **新しい日付が上 (降順)**。したがって「前日」は 1 つ **下** の行
  (r+1) を参照する。本ジョブも A/B (Date/Close) を降順で書き込む。
- ヘッダは 1 行目、データは 2 行目 (=FIRST_DATA_ROW) から。

列レイアウト (A..W)。C 列以降は各行に入れる数式:

| 列 | ヘッダ                 | ABBV の数式 (r 行目, r+1=前日=1つ下) |
|----|------------------------|--------------------------------------|
| A  | Date                   | 値 (yfinance)                        |
| B  | Close                  | 値 (yfinance)                        |
| C  | IF($C3>=0,$C3,0)       | 上昇幅 = IF($Br-$B(r+1)>=0, 差, 0)   |
| D  | IF($C3>=0,0,-$C3)      | 下落幅 = IF($Br-$B(r+1)>=0, 0, -差)  |
| E  | 直近差                 | 方向 = IF(Br-B(r+1)>0,"↑",…,"↓","")  |
| F  | RSI14                  | (Σgain14/14)/((Σgain14/14)+(Σloss14/14))*100 |
| G  | RSI30                  | 同上 30                              |
| H  | RSI45                  | 同上 45                              |
| I  | RSI100                 | 同上 100                             |
| J  | RSI300                 | 同上 300                             |
| K  | RSI判断                | COUNTIF ネストで ×/△/〇/◎            |
| L  | ボリジャー上限         | AVERAGE(5)+2*STDEV(5)                |
| M  | ボリジャー下限         | AVERAGE(5)-2*STDEV(5)                |
| N  | EMA12                  | N(r+1)+2/13*(Br-N(r+1))              |
| O  | EMA26                  | O(r+1)+2/27*(Br-O(r+1))              |
| P  | MACD                   | Nr-Or                                |
| Q  | シグナル線9日          | Q(r+1)+2/(9+1)*(Pr-Q(r+1))           |
| R  | MACDクロス             | Pr-Qr                                |
| S  | MACDクロス差           | 方向 = IF(Rr-R(r+1)>0,"↑",…)         |
| T  | MA3                    | SUM($Br:$B(r+2))/3                   |
| U  | MA5                    | SUM($Br:$B(r+4))/5                   |
| V  | MA10                   | SUM($Br:$B(r+9))/10                  |
| W  | MA200                  | SUM(Br:B(r+199))/200                 |

注: ABBV では末尾 (最古の行) 付近で参照範囲がデータ下端を超えて空セルに及ぶが
(空セル=0 として計算)、これは ABBV の挙動そのものであり忠実に再現する。
"""
from __future__ import annotations

from .config import FIRST_DATA_ROW

# ABBV のヘッダ行 (A..W)。C/D の見出しは ABBV 上の表記をそのまま踏襲。
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


def _rsi(period: int, r: int) -> str:
    """ABBV 方式の RSI (gain/loss の単純平均比)。r..r+period-1 の下方向 window。"""
    lo = r + period - 1
    sg = f"SUM($C{r}:$C{lo})/{period}"
    sl = f"SUM($D{r}:$D{lo})/{period}"
    return f"=({sg}/({sg}+{sl}))*100"


def build_row_formulas(r: int) -> list[str]:
    """データ行 ``r`` (>= FIRST_DATA_ROW) の C..W 列数式を返す (21 要素)。

    r+1 は 1 つ下の行 (= 前日・より古い日) を指す。
    """
    n = r + 1  # 前日 (1 つ下の行)

    # C 上昇幅 / D 下落幅 / E 方向
    gain = f"=IF($B{r}-$B{n}>=0,$B{r}-$B{n},0)"
    loss = f"=IF($B{r}-$B{n}>=0,0,-$B{r}+$B{n})"
    direction = f'=IF(B{r}-B{n}>0,"↑",IF(B{r}-B{n}<0,"↓",""))'

    # F..J RSI
    rsi14 = _rsi(14, r)
    rsi30 = _rsi(30, r)
    rsi45 = _rsi(45, r)
    rsi100 = _rsi(100, r)
    rsi300 = _rsi(300, r)

    # K RSI判断 (ABBV の COUNTIF ネストを忠実に再現)
    rsi_judge = (
        f'=IF(COUNTIF(F{r},">=70")=1,"×",'
        f'IF(COUNTIF(F{r}:H{r},">=50")=3,"△",'
        f'IF(COUNTIF(F{r}:H{r},">=50")=2,"△",'
        f'IF(COUNTIF(F{r}:H{r},">=50")=1,"〇",'
        f'IF(COUNTIF(F{r}:H{r},">=50")=0,'
        f'IF(COUNTIF(F{r},"<=30")=0,"〇","◎"))))))'
    )

    # L/M ボリンジャー (5 日, 標本標準偏差 STDEV)
    bb_lo = r + 4
    bb_upper = f"=AVERAGE($B{r}:$B{bb_lo})+2*STDEV($B{r}:$B{bb_lo})"
    bb_lower = f"=AVERAGE($B{r}:$B{bb_lo})-2*STDEV($B{r}:$B{bb_lo})"

    # N/O EMA, P MACD, Q シグナル, R クロス, S 方向
    ema12 = f"=N{n}+2/13*(B{r}-N{n})"
    ema26 = f"=O{n}+2/27*(B{r}-O{n})"
    macd = f"=N{r}-O{r}"
    signal = f"=Q{n}+2/(9+1)*(P{r}-Q{n})"
    macd_cross = f"=P{r}-Q{r}"
    macd_cross_dir = f'=IF(R{r}-R{n}>0,"↑",IF(R{r}-R{n}<0,"↓",""))'

    # T..W 移動平均 (下方向 window)
    ma3 = f"=SUM($B{r}:$B{r + 2})/3"
    ma5 = f"=SUM($B{r}:$B{r + 4})/5"
    ma10 = f"=SUM($B{r}:$B{r + 9})/10"
    ma200 = f"=SUM(B{r}:B{r + 199})/200"

    return [
        gain, loss, direction,
        rsi14, rsi30, rsi45, rsi100, rsi300, rsi_judge,
        bb_upper, bb_lower,
        ema12, ema26, macd, signal, macd_cross, macd_cross_dir,
        ma3, ma5, ma10, ma200,
    ]


def build_matrix(series: list[tuple[str, float]]) -> list[list]:
    """ヘッダ + 全データ行 (値 A/B + 数式 C..W) の 2 次元配列を返す。

    ``series`` は (日付, 終値) の **昇順** リスト。ABBV に合わせて **降順**
    (新しい日付が上) に並べ替えて書き込む。
    """
    rows_desc = sorted(series, key=lambda x: x[0], reverse=True)
    matrix: list[list] = [HEADER]
    for i, (date_str, close) in enumerate(rows_desc):
        r = FIRST_DATA_ROW + i
        matrix.append([date_str, close, *build_row_formulas(r)])
    return matrix
