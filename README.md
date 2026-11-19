# w06jastock-sheets

日経平均225・トヨタなどの日次株価を **Google スプレッドシートへ毎日 17:00 (JST) に自動出力** するジョブ。株価データは **J-Quants API**（公式・調整後終値）から取得します。

姉妹リポジトリ [`spenda-agency/jastock`](https://github.com/spenda-agency/jastock)（東証全銘柄のゴールデンクロス検出 Web アプリ）のテクニカル指標を参考にしつつ、本リポジトリは方針が異なります:

> **Python が書き込むのは `Date` と `Close` の 2 列だけ。`C` 列以降のテクニカル指標はすべてスプレッドシートの数式で算出する。**

これにより、指標の定義変更はシート上の数式を直すだけで完結し、Python 側は「値の供給」に専念します。

## 出力先

- スプレッドシート: <https://docs.google.com/spreadsheets/d/1Zivd5Dorzc_fnwYF0gt5QSliq1MwLs6ZntNmt3AyeD4/edit>
- 1 銘柄 = 1 ワークシート（タブ）。タブ名は既存タブ「ABBV」に倣い銘柄コード。
  - `7203` … トヨタ自動車（ティッカー `7203.T` → J-Quants コード `7203`）
  - `N225` … 日経平均225（`^N225`）。**注意: 指数は J-Quants に無いためスキップされます**
    （→ 下記「データソースについて」。日経225に連動する ETF `1321.T` 等で代替可能）

## 銘柄の追加方法（GitHub 上で完結）

対象銘柄は [`tickers.csv`](tickers.csv) で管理します。**GitHub の Web UI でこのファイルに
1 行足してコミットするだけ**で銘柄を追加できます（コード変更・ワークフロー変更は不要）。

```csv
ticker,sheet_name,label
^N225,N225,日経平均225
7203.T,7203,トヨタ自動車
6758.T,,ソニーグループ     ← ticker だけでも可。sheet_name は 6758 に自動導出
```

- `ticker`（必須）… 東証個別株/ETF は `7203.T`（末尾 `.T` は自動除去し J-Quants コードへ変換）。
  指数 `^N225` は J-Quants 非対応でスキップされます
- `sheet_name`（任意）… タブ名。空欄なら ticker から自動導出（先頭 `^`・末尾 `.T` を除去）
- `label`（任意）… ログ表示名。空欄なら ticker をそのまま使用
- `#` で始まる行・空行は無視されます

追加後、**次回の 17:00 実行**（または Actions の `Run workflow` 手動実行）で新しいタブが
自動生成されます。1 銘柄が取得失敗（上場廃止・記号ミス等）しても他銘柄は止まりません。

## 列レイアウト（既存タブ「ABBV」に準拠）

C 列以降の数式は、同じスプレッドシートの既存タブ **「ABBV」** に記載済みの定義に
**厳密に一致**させています（`sheets_stock/formulas.py` は ABBV の C〜W をそのまま再現。
自動テストで全数式が ABBV と一致することを検証済み）。

ABBV の設計に合わせ、データは **新しい日付が上（降順）** に並びます。そのため各行の
「前日」は 1 つ **下** の行（`r+1`）を参照します。ヘッダは 1 行目、データは 2 行目から。

| 列 | ヘッダ | 内容（r 行目、`r+1`=前日=1つ下） |
|----|--------|------|
| A | Date | 日付（値・降順） |
| B | Close | 終値（値） |
| C | IF($C3>=0,$C3,0) | 上昇幅 = `IF($B(r)−$B(r+1)≥0, 差, 0)` |
| D | IF($C3>=0,0,-$C3) | 下落幅 = `IF($B(r)−$B(r+1)≥0, 0, −差)` |
| E | 直近差 | 方向記号 = `IF(B(r)−B(r+1)>0,"↑",…,"↓","")` |
| F–J | RSI14 / 30 / 45 / 100 / 300 | `(Σgain/N)/((Σgain/N)+(Σloss/N))×100`（下方向 N 本の単純平均） |
| K | RSI判断 | `COUNTIF` ネストで `×`／`△`／`〇`／`◎` を判定 |
| L / M | ボリジャー上限 / 下限 | `AVERAGE(5) ± 2×STDEV(5)`（5 日・標本標準偏差） |
| N / O | EMA12 / EMA26 | `N(r+1)+2/13×(B(r)−N(r+1))` など（1 つ下を参照する再帰式） |
| P | MACD | EMA12 − EMA26 |
| Q | シグナル線9日 | `Q(r+1)+2/10×(P(r)−Q(r+1))` |
| R | MACDクロス | MACD − シグナル線（ヒストグラム） |
| S | MACDクロス差 | 方向記号 = `IF(R(r)−R(r+1)>0,"↑",…)` |
| T–W | MA3 / MA5 / MA10 / MA200 | 終値の単純移動平均（下方向 window） |

> ABBV の追加列 X〜AD（Volume・RSI3・RS・ROC100・コナーズRSI）は今回のスコープ外
> （MA200 まで）としています。必要になれば `formulas.py` に追記して拡張できます。

### 指標計算の注意

- 数式は **ABBV と完全一致**（`AVERAGE`/`SUM`/`STDEV`/`COUNTIF` ベースのシート数式）。
  `jastock` バックエンドは Wilder 平滑（`ewm`）ですが、本シートは ABBV 方式に合わせています。
- データは **降順**（最新が 2 行目）。Python は J-Quants から取得した Date/Close を降順に
  並べ替えて A/B 列へ書き込み、C 列以降は上記の数式が計算します。
- 移動平均・RSI 等は下方向の window を参照するため、**最古の数行では window が
  データ下端を超えて空セル（=0）を含みます**。これは ABBV の挙動そのものです。
  十分な履歴（RSI300/MA200）を確保するため既定で 800 本取得します。

## セットアップ

### 1. Google サービスアカウントを作成し、シートに共有

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成（既存でも可）。
2. **Google Sheets API** と **Google Drive API** を有効化。
3. サービスアカウントを作成し、**JSON 鍵**をダウンロード。
4. 出力先スプレッドシートを、その**サービスアカウントのメールアドレス**（`xxxx@xxxx.iam.gserviceaccount.com`）に **編集者**として共有。

### 2. GitHub Actions で毎日自動実行（推奨）

リポジトリの **Settings → Secrets and variables → Actions** で登録:

- Secret `GOOGLE_SERVICE_ACCOUNT_JSON` … ダウンロードした鍵 JSON の**中身全体**
- Secret `JQUANTS_API_KEY` … J-Quants **V2 の API キー**（ダッシュボードで発行・無期限）
- （任意）Variable `SPREADSHEET_ID` … 出力先を変えたい場合のみ

登録後、**Actions タブ → `Update stock sheets` → `Run workflow`** で一度手動実行して
疎通確認してください。ログに `N225 → A1:W801 ...` のような行が出れば成功です。

[`.github/workflows/update-sheets.yml`](.github/workflows/update-sheets.yml) が
**月〜金 08:00 UTC（= 17:00 JST）** に自動実行します。`workflow_dispatch` で手動実行も可能。

> スケジュール実行は**デフォルトブランチ**から起動します（本リポジトリのデフォルトは
> `claude/nikkei-toyota-sheet-automation-foklzh`）。別ブランチを本番にする場合は
> そのブランチをデフォルトに設定してください。

### 3. ローカル / Colab で実行

```bash
pip install -r requirements.txt

# 認証: Google 鍵ファイルのパス + J-Quants トークン
export GOOGLE_APPLICATION_CREDENTIALS=./service_account.json
export JQUANTS_API_KEY=xxxxx          # J-Quants V2 の API キー

# 実行（対象シートへ一括書き込み）
python -m sheets_stock.update_job
```

補助コマンド:

```bash
# 取得のみ・書き込みなし（J-Quants 認証は必要）。行数・期間・最新終値を確認
python -m sheets_stock.update_job --dry-run

# 合成データで数式生成の健全性を検証（ネットワーク/認証不要）
python -m sheets_stock.update_job --self-test
```

## 構成

```
w06jastock-sheets/
├── tickers.csv          # 対象銘柄一覧（GitHub 上で編集して銘柄追加）
├── sheets_stock/
│   ├── config.py        # tickers.csv 読み込み・スプレッドシート ID・定数
│   ├── prices.py        # J-Quants で (Date, Close) を取得
│   ├── formulas.py      # C 列以降の数式を生成（本リポジトリの核）
│   ├── sheet_writer.py  # gspread 認証 + 一括書き込み
│   └── update_job.py    # エントリポイント（--dry-run / --self-test）
├── .github/workflows/update-sheets.yml   # 毎日 17:00 JST cron
├── requirements.txt
└── .env.example
```

## データソースについて

**J-Quants API**（JPX 公式）から日次株価を取得します。終値は**調整後終値**（株式分割等を反映）を使用します。

- 認証: V2 の **API キー**（`x-api-key` ヘッダー・無期限）。`prices.py` が
  環境変数 `JQUANTS_API_KEY` を使います。
- ティッカー `7203.T` は末尾 `.T` を除去し、V2 の **5桁コード `72030`** に変換して取得します。
- **指数（`^N225` 等）は J-Quants に存在しないためスキップされます。** 日経225 を出したい場合は、
  連動 ETF（例 `1321.T` = NEXT FUNDS 日経225連動型）を `tickers.csv` に追加してください
  （値は指数そのものではなく ETF 価格になります）。TOPIX 等は既に連動 ETF（`1306.T` 等）で登録済みです。
- 旧データソースの Yahoo Finance（yfinance）からの移行済みです。

## ライセンス

MIT
