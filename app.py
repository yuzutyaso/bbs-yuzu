from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import hashlib

app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'board.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_super_secret_key_for_flask_flash_messages_change_this_in_prod' # 本番環境ではもっと複雑に！

db = SQLAlchemy(app)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return '<Post %r>' % self.id

# === 簡易管理者ハッシュの設定 (警告: 本番環境では非推奨) ===
# ここに管理者として扱いたいシード値から生成されるハッシュの最初の7文字を設定します。
# 例: シード値 "adminseed" から "fb2bfb4" が生成されると仮定
# 複数の管理者ハッシュを設定できます。
ADMIN_HASHES = ["fb2bfb4"]
# ==========================================================

with app.app_context():
    db.create_all()

# ヘルパー関数：ユーザーが管理者権限を持っているかチェック
def is_admin(user_hash):
    return user_hash in ADMIN_HASHES

@app.route('/')
def index():
    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template('index.html', posts=posts,
                           prev_name=request.args.get('prev_name', ''),
                           prev_seed=request.args.get('prev_seed', ''),
                           prev_message=request.args.get('prev_message', ''))

@app.route('/post', methods=['POST'])
def post():
    raw_username = request.form['name']
    message = request.form['message']
    seed = request.form['seed']

    if not raw_username or not message or not seed:
        flash('名前、メッセージ、シードはすべて必須です。', 'error')
        return redirect(url_for('index',
                                prev_name=raw_username,
                                prev_message=message,
                                prev_seed=seed))

    # シード値をSHA-256でハッシュ化し、最初の7文字を取得
    seed_hash_full = hashlib.sha256(seed.encode('utf-8')).hexdigest()
    display_hash = seed_hash_full[:7]
    final_username = f"{raw_username}@{display_hash}"

    # === コマンド処理の分岐 ===
    if message.startswith('/'):
        command_input = message.strip()
        command_parts = command_input.split()
        command = command_parts[0].lower() # コマンド名を小文字に変換

        # 権限チェック
        if not is_admin(display_hash):
            flash(f"コマンド '{command}' を実行する権限がありません。", 'error')
            return redirect(url_for('index'))

        feedback_message = ""
        if command == '/del':
            if len(command_parts) > 1:
                deleted_count = 0
                for post_id_str in command_parts[1:]:
                    try:
                        post_id = int(post_id_str)
                        post_to_delete = Post.query.get(post_id)
                        if post_to_delete:
                            db.session.delete(post_to_delete)
                            deleted_count += 1
                        else:
                            feedback_message += f"投稿番号 {post_id} が見つかりません。<br>"
                    except ValueError:
                        feedback_message += f"無効な投稿番号: {post_id_str}<br>"
                db.session.commit()
                if deleted_count > 0:
                    flash(f"{deleted_count}件の投稿を削除しました。<br>" + feedback_message.strip(), 'success')
                else:
                    flash(feedback_message.strip() or "指定された投稿は削除されませんでした。", 'info')
            else:
                flash("/del (投稿番号) の形式で入力してください。", 'error')
        elif command == '/clear':
            try:
                num_rows_deleted = db.session.query(Post).delete()
                db.session.commit()
                # SQLiteのシーケンスIDをリセット
                db.session.execute(db.text("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'post'"))
                db.session.commit()
                flash(f"{num_rows_deleted}件の全ての投稿を削除し、投稿番号をリセットしました。", 'success')
            except Exception as e:
                db.session.rollback()
                flash(f"全ての投稿の削除中にエラーが発生しました: {e}", 'error')
        else:
            flash(f"不明なコマンド: {command}", 'error')

        # コマンドが実行された場合、掲示板には表示しないためリダイレクト
        return redirect(url_for('index'))
    # === コマンド処理の分岐 終わり ===

    # コマンドではない通常の投稿の場合
    new_post = Post(username=final_username, message=message)
    db.session.add(new_post)
    db.session.commit()
    flash('投稿が完了しました！', 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
