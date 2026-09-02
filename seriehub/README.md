# SerieHub — セリエA・セリエB 情報サイト

イタリア・セリエAとセリエBの全40クラブについて、**移籍/内情報道**と**試合結果・スタメン・ベンチ**を
一箇所に集約する静的サイトジェネレータ。イタリア主要紙・公式発表を情報源とし、
GitHub Actions で定期的に再生成して GitHub Pages へ公開する。

## このサイトの設計方針

**1. 本文は転載しない。**
掲載するのは見出し・短い要約・公開日時・出典リンクのみ。記事の全文は各媒体で読む。
著作権と各媒体の利用規約に配慮した上で、アグリゲーターとして成立させるための線引き。

**2. 原文が正、翻訳は補助。**
記事はイタリア語のまま取得・保存する。日本語訳はビルド時に生成し、原文と**両方**をHTMLに埋め込む。
閲覧者はヘッダーの `原文 / 日本語` で瞬時に切り替えられる。ページ表示時に翻訳APIを叩かないので、
遅延も回数制限も起きない。翻訳が無い記事には「Google翻訳で開く」リンクが出る。

**3. 移籍報道は確度を分ける。**
移籍情報は本質的に飛ばし記事を含む。「誰が言っているか（媒体の一次性）」と
「何と言っているか（発表・交渉・関心）」の2軸で機械的に判定し、3段階に落とす。

| 確度 | 条件 |
|---|---|
| **確定** | リーグ/クラブの公式発表、または記事が公式発表を明示している |
| **有力** | 自社の記者を持つイタリア主要紙による、交渉進展以上の報道 |
| **噂** | まとめ媒体・翻訳媒体の報道、関心/打診の段階、または断定を避けた表現 |

`sarebbe` `secondo quanto riportato` のような伝聞表現を検出したら1段階引き下げる。
判定根拠はバッジの tooltip に出して開示している。

**4. 取れなかったものは黙って隠さない。**
フィードが落ちてもビルドは止めず、`情報源` ページに死活と理由を出す。

## 使い方

```bash
cd seriehub
pip install -r requirements.txt

python3 build.py --offline    # サンプルデータでビルド（通信もAPIキーも不要）
python3 build.py              # 実データでビルド
python3 build.py --check-feeds   # 全RSSの死活だけ確認
```

生成先は `seriehub/site/`。ブラウザで `site/index.html` を開けば確認できる。

主なオプション:

| オプション | 既定 | 説明 |
|---|---|---|
| `--out DIR` | `site` | 出力ディレクトリ |
| `--offline` | – | fixtures のサンプルデータでビルド（翻訳も自動で無効化） |
| `--translate {auto,deepl,mymemory,none}` | `auto` | 翻訳エンジン |
| `--translate-limit N` | `400` | 1回のビルドで新規翻訳する上限（0で無制限） |
| `--days-back / --days-ahead` | `14` | 取得する試合の期間 |
| `--max-age-days` | `21` | 記事の鮮度上限 |
| `--lineup-budget N` | `20` | スタメンを取りに行く試合数の上限 |

## APIキーの設定

**どのキーも必須ではない。** 無くてもニュース部分は動く。設定するほど取れる情報が増える。

| 環境変数 | 発行元 | 何が増えるか |
|---|---|---|
| `API_FOOTBALL_KEY` | [api-football.com](https://www.api-football.com/) | **セリエA/B両方**の順位表・結果・**スタメン/ベンチ** |
| `FOOTBALL_DATA_TOKEN` | [football-data.org](https://www.football-data.org/) | セリエAの順位表・結果（無料プランはセリエB非対応） |
| `DEEPL_API_KEY` | [DeepL API](https://www.deepl.com/pro-api) | 伊→日の高品質な見出し翻訳 |
| `MYMEMORY_EMAIL` | 任意のメールアドレス | MyMemory（キー不要の予備翻訳）の無料枠が少し増える |

ローカルでは環境変数、GitHub Actions では **Settings → Secrets and variables → Actions** に登録する。

翻訳エンジンは `DeepL → MyMemory → なし` の順に自動フォールバックする。
訳した見出しは `data/translation_cache.json` に貯まり、同じ見出しを二度翻訳しない。

### 制限事項（把握しておくべきこと）

- **スタメン/ベンチが取れるのは API-Football だけ。** football-data.org の無料プランには含まれない。
- **API-Football の無料プランは 1日100リクエスト**、かつプランによって取得可能シーズンに制限がある。
  スタメンは1試合1リクエスト消費するので `--lineup-budget` で上限をかけている。
- **セリエBは football-data.org の無料プランで取得できない。** セリエBまで欲しいなら API-Football が必要。
- **RSS の URL は媒体側の都合で予告なく変わる。** `--check-feeds` で定期的に確認し、
  変わっていたら `config/sources.yaml` を直す。死んだフィードは `enabled: false` で止められる。

## 公開（GitHub Pages）

`.github/workflows/seriehub.yml` が3時間ごとにビルドして Pages へ公開する。
初回のみリポジトリ側の設定が必要:

1. **Settings → Pages → Source** を `GitHub Actions` にする
2. 上記の Secrets を登録する
3. schedule はデフォルトブランチでしか動かないので、このブランチを `main` にマージする
   （それまでは Actions タブの **Run workflow** から手動実行できる）

## 構成

```
seriehub/
├── build.py              収集→翻訳→描画のオーケストレーション
├── config/
│   ├── clubs.yaml        クラブのメタデータ辞書（日本語名・スタジアム・カラー）
│   ├── sources.yaml      RSSフィードと一次性ティアの定義
│   └── leagues.yaml      所属クラブのフォールバック（順位表が取れない時だけ使う）
├── lib/
│   ├── models.py         受け渡すデータ構造
│   ├── matching.py       記事本文からのクラブ同定
│   ├── transfer.py       移籍報道の分類と確度判定
│   ├── news.py           RSS収集・正規化・重複排除
│   ├── translate.py      DeepL/MyMemory + キャッシュ
│   ├── render.py         Jinja2 での書き出し
│   └── providers/        試合データの取得先（football-data / API-Football / offline）
├── templates/            ページのテンプレート
├── static/               CSS と表示切替スクリプト
├── fixtures/             検証用のサンプルデータ（架空）
└── tests/                テスト（外部通信なし）
```

### 昇降格への対応

**所属クラブの正は順位表**で、`config/clubs.yaml` は表示用メタデータの辞書にすぎない。
シーズンが変わって顔ぶれが入れ替わっても、APIから順位表が取れていれば何も直さなくてよい。
辞書に無いクラブが現れた場合はイタリア語表記のまま表示される（日本語名を足したい時だけ
`clubs.yaml` に追記する。近年A/Bを行き来したクラブは予備として既に入れてある）。

APIキーが無く順位表が取れない場合に限り `config/leagues.yaml` の構成を使う。
このときサイトのビルドログに注記が出る。

## テスト

```bash
cd seriehub
python3 -m unittest discover -s tests -v
```

外部通信は一切しない。クラブ同定の誤爆（`interesse`→Inter、`Milano`→Milan）、
イタリア語のエリジオン（`l'Inter`）、確度判定、翻訳キャッシュ、
`--offline` ビルドが全40クラブ分のページを出すことまで検証している。

必要なもの: **Python 3.10 以上**（3.10 / 3.11 / 3.12 / 3.13 でテスト済み）
