# スピーカー納品プロジェクト スケジュール共有

関係者向けの閲覧専用ページを Streamlit Community Cloud で公開するための一式です。
在宅・社外からでもURLとパスワードがあれば閲覧でき、編集できるのは編集用パスワードを持つ人だけです。

## 仕組み

- **閲覧用パスワード**：関係者に配布。表・ガント・BOMを見られるが、編集・保存はできない。
- **編集用パスワード**：自分だけが持つ。編集・保存までできる。
- パスワードは `st.secrets` で管理し、GitHub には上げません（漏洩しません）。

> 注意：Streamlit Community Cloud はファイルの保存が揮発します（再起動で消える）。
> そのため **編集は手元のPCで行い、結果を GitHub に反映する運用** が確実です。
> クラウド上は基本「閲覧専用」として関係者に見せる用途に使ってください。

---

## このフォルダに入れるファイル

GitHub リポジトリには、以下をこのフォルダ（リポジトリのルート）に置きます。

```
schedule_app.py            ← アプリ本体（1つ上のフォルダからコピー）
schedule_config.json       ← スケジュール設定（表示データ。コピー）
bom_config.json            ← BOMデータ（表示データ。あれば）
bom_quotes.json            ← 見積PDFの索引（あれば）
schedule_images/           ← 参考画像（あれば）
schedule_bom_quotes/       ← 見積PDF本体（あれば）
requirements.txt           ← 用意済み
.gitignore                 ← 用意済み
.streamlit/secrets.toml.example ← 見本（実物は作らずクラウドに直接入力）
```

`schedule_app.py` と各データファイルは、1つ上のフォルダ（document_kiro）から
このフォルダにコピーしてください。

---

## デプロイ手順

### 1. GitHub リポジトリを作る
- GitHub で新しいリポジトリを作成（private 推奨）。
- このフォルダの中身をそのリポジトリに push する。

### 2. Streamlit Community Cloud でデプロイ
1. https://share.streamlit.io/ にGitHubアカウントでサインイン。
2. 「New app」→ 作ったリポジトリとブランチを選択。
3. 「Main file path」に `schedule_app.py` を指定。
4. Deploy を実行。

### 3. パスワードを設定（重要）
1. デプロイ後、アプリ画面の右下メニュー → **Settings → Secrets** を開く。
2. 以下を貼り付けて保存（値は自分で決める）。

   ```toml
   view_password = "閲覧用のパスワード"
   edit_password = "編集用のパスワード"
   ```

3. 保存すると自動で再起動し、ログイン画面が出るようになります。

### 4. 共有
- 公開URL（`https://xxxx.streamlit.app`）と **閲覧用パスワード** を関係者に伝える。
- 編集用パスワードは自分だけが持つ。

---

## ローカルで試す場合

このフォルダで以下を実行します（secrets を用意するとログイン画面を確認できます）。

1. `.streamlit/secrets.toml.example` を `.streamlit/secrets.toml` にコピーし、パスワードを記入。
2. 起動：

   ```
   python -m streamlit run schedule_app.py
   ```

secrets.toml を作らなければ、認証なし（フル編集）で起動します。

---

## パスワードを変えたいとき

- クラウド：Settings → Secrets の値を書き換えて保存。
- ローカル：`.streamlit/secrets.toml` を書き換え。
