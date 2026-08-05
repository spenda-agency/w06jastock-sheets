"""spenda-agency / w06jastock-sheets.

日経平均225・トヨタ等の日次株価を Google スプレッドシートへ毎日 16:00 (JST)
に書き出すジョブ。姉妹リポジトリ ``spenda-agency/jastock`` のテクニカル指標を
参考にしつつ、本リポジトリでは **Date / Close だけを Python で書き込み、
C 列以降の指標はスプレッドシートの数式で算出** する構成をとる。
"""
