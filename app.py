from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import hashlib # シード値のハッシュ化のために追加

app = Flask(__name__)

# データベースファイルのパスを設定
# RenderなどのPaaS環境では絶対パス指定が推奨されます。
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'board.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# 投稿のデータベースモデルを定義
class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False) # ハッシュ値を含むユーザー名を格納
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow) # 投稿日時

    def __repr__(self):
        return '<Post %r>' % self.id

# アプリケーションコンテキスト内でデータベースを初期化（テーブル作成）
# これにより、アプリケーション起動時にデータベースファイルとテーブルが作成されます。
with app.app_context():
    db.create_all()

# トップページ（掲示板の表示）のルート
@app.route('/')
def index():
    # 全ての投稿を新しい順に取得
    posts = Post.query.order_by(Post.created_at.desc()).all()
    # テンプレートに投稿リストを渡してレンダリング
    return render_template('index.html', posts=posts)

# 投稿を受け付けるルート
@app.route('/post', methods=['POST'])
def post():
    if request.method == 'POST':
        raw_username = request.form['name'] # 入力された名前
        message = request.form['message']   # 入力されたメッセージ
        seed = request.form['seed']         # 入力されたシード値

        # 必須項目が空でないかチェック
        if not raw_username or not message or not seed:
            # 不足している場合はトップページにリダイレクト（エラーメッセージ表示は省略）
            return redirect(url_for('index'))

        # シード値をSHA-256でハッシュ化し、最初の7文字を取得
        # .encode('utf-8')で文字列をバイト列に変換してからハッシュ化します。
        seed_hash = hashlib.sha256(seed.encode('utf-8')).hexdigest()
        display_hash = seed_hash[:7]

        # ユーザー名とハッシュ値を結合して最終的な表示名を作成
        final_username = f"{raw_username}@{display_hash}"

        # 新しい投稿オブジェクトを作成し、データベースに追加
        new_post = Post(username=final_username, message=message)
        db.session.add(new_post)
        db.session.commit() # データベースに変更をコミット

        # 投稿後にトップページにリダイレクト
        return redirect(url_for('index'))

# アプリケーションのエントリーポイント
if __name__ == '__main__':
    # デバッグモードは開発中にのみ有効にし、本番環境では無効にしてください。
    app.run(debug=True)
