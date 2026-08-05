# w06jastock-sheets

日経平均225・トヨタなどの日次株価を **Google スプレッドシートへ毎日 16:00 (JST) に自動出力** するジョブ。

姉妹リポジトリ [`spenda-agency/jastock`](https://github.com/spenda-agency/jastock)（東証全銘柄のゴールデンクロス検出 Web アプリ）のテクニカル指標を参考にしつつ、本リポジトリは方針が異なります:

> **Python が書き込むのは `Date` と `Close` の 2 列だけ。`C` 列以降のテクニカル指標はすべてスプレッドシートの数式で算出する。**

これにより、指標の定義変更はシート上の数式を直すだけで完結し、Python 側は「値の供給」に専念します。

## 出力先

- スプレッドシート: <https://docs.google.com/spreadsheets/d/1Zivd5Dorzc_fnwYF0gt5QSliq1MwLs6ZntNmt3AyeD4/edit>
- 1 銘柄 = 1 ワークシート（タブ）
  - `日経平均225` … yfinance ティッカー `^N225`
  - `トヨタ` … yfinance ティッカー `7203.T`

銘柄の追加は [`sheets_stock/config.py`](sheets_stock/config.py) の `INSTRUMENTS` に 1 行足すだけです。

## 列レイアウト

ヘッダは 1 行目、データは 2 行目から。`A`/`B` が値、`C` 以降が数式です。

| 列 | ヘッダ | 内容 |
|----|--------|------|
| A | Date | 日付（値） |
| B | Close | 終値（値） |
| C | IF($C3>=0,$C3,0) | 上昇幅 gain（直近差が + ならその値、他は 0） |
| D | IF($C3>=0,0,-$C3) | 下落幅 loss（直近差が + なら 0、他は −直近差） |
| E | 直近差 | 前日終値との差 = `B(r) − B(r−1)` |
| F–J | RSI14 / 30 / 45 / 100 / 300 | `100 − 100/(1 + 平均gain/平均loss)`（単純移動平均ベース） |
| K | RSI判断 | RSI14 ≥ 70:`売` / ≤ 30:`買` / それ以外:`△` |
| L / M | ボリジャー上限 / 下限 | 20 期間移動平均 ± 2σ |
| N / O | EMA12 / EMA26 | 指数平滑移動平均（`adjust=False` 相当、前行参照の再帰式） |
| P | MACD | EMA12 − EMA26 |
| Q | シグナル線9日 | MACD の EMA9 |
| R | MACDクロス | `ゴールデン` / `デッド`（クロス差 S の符号反転を検出） |
| S | MACDクロス差 | MACD − シグナル線 |
| T–W | MA3 / MA5 / MA10 / MA200 | 終値の単純移動平均 |

> **`$C3` 参照についての補足**: ご提示のヘッダでは `C`/`D` 列（上昇幅・下落幅）の数式が `$C3` を参照していましたが、上昇幅・下落幅は指標の定義上「直近差」から求めるものです。本実装では **列の並び順はご提示どおりに保ち**、参照先だけを直近差にあたる `E` 列へ整合させています（`sheets_stock/formulas.py` 冒頭のコメント参照）。並びや参照の意図が異なる場合はお知らせください。

### 指標計算の注意

- **RSI** は gain/loss の**単純移動平均**（`AVERAGE`）ベースです。事前検証いただいた Colab コードと同方式で、シート数式だけで完結します。`jastock` バックエンドは Wilder 平滑（`ewm`）を使っており、値は近いものの完全一致はしません。
- **EMA / MACD / シグナル** は前行を参照する再帰式で、pandas の `ewm(adjust=False)` と一致します。初回行は終値をシードにします。
- **ボリンジャーバンド**は標準的な **20 期間・±2σ**（母集団標準偏差 `STDEVP`）です。期間を変えたい場合は `config.BOLLINGER_PERIOD` を変更してください。
- 各指標は必要本数がそろう行から計算し、それ以前は空欄になります（RSI300 と MA200 を埋めるため既定で 800 本取得）。

## セットアップ

### 1. Google サービスアカウントを作成し、シートに共有

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成（既存でも可）。
2. **Google Sheets API** と **Google Drive API** を有効化。
3. サービスアカウントを作成し、**JSON 鍵**をダウンロード。
4. 出力先スプレッドシートを、その**サービスアカウントのメールアドレス**（`xxxx@xxxx.iam.gserviceaccount.com`）に **編集者**として共有。

### 2. GitHub Actions で毎日自動実行（推奨）

リポジトリの **Settings → Secrets and variables → Actions** で登録:

- Secret `GOOGLE_SERVICE_ACCOUNT_JSON` … ダウンロードした鍵 JSON の**中身全体**
- （任意）Variable `SPREADSHEET_ID` … 出力先を変えたい場合のみ

[`.github/workflows/update-sheets.yml`](.github/workflows/update-sheets.yml) が **月〜金 07:00 UTC（= 16:00 JST）** に実行します。`workflow_dispatch` で手動実行も可能です。

### 3. ローカル / Colab で実行

```bash
pip install -r requirements.txt

# 認証: 鍵ファイルのパスを指定
export GOOGLE_APPLICATION_CREDENTIALS=./service_account.json

# 実行（対象シートへ一括書き込み）
python -m sheets_stock.update_job
```

補助コマンド:

```bash
# 取得のみ・書き込みなし（認証不要）。行数・期間・最新終値を確認
python -m sheets_stock.update_job --dry-run

# 合成データで数式生成の健全性を検証（ネットワーク/認証不要）
python -m sheets_stock.update_job --self-test
```

## 構成

```
w06jastock-sheets/
├── sheets_stock/
│   ├── config.py        # 対象銘柄・スプレッドシート ID・定数
│   ├── prices.py        # yfinance で (Date, Close) を取得
│   ├── formulas.py      # C 列以降の数式を生成（本リポジトリの核）
│   ├── sheet_writer.py  # gspread 認証 + 一括書き込み
│   └── update_job.py    # エントリポイント（--dry-run / --self-test）
├── .github/workflows/update-sheets.yml   # 毎日 16:00 JST cron
├── requirements.txt
└── .env.example
```

## データソースについて

`jastock` と同じく **yfinance**（Yahoo Finance、認証不要）を採用しています。日経平均225 は指数ティッカー `^N225`、個別株は `<コード>.T` 形式です。より公式・無遅延なデータが必要な場合は `jastock` の `prices.py` と同様に J-Quants へ差し替え可能です。

## ライセンス

MIT
