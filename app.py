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

# 投稿のデータベースモデル
class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return '<Post %r>' % self.id

# トピックのデータベースモデル
class Topic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(255), nullable=False, default="設定されていません")
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return '<Topic %r>' % self.content

# === 権限ごとのハッシュと色の定義 (ここを設定してください！) ===
# 各権限に割り当てたいユーザーのシード値から生成される7文字のハッシュを設定してください。
# 例: シード値 "myadminseed" から "your_admin_hash_here" が生成される場合
# 例: シード値 "mysummitseed" から "summithash" が生成される場合
# 例: シード値 "mymoderatorseed" から "modhash" が生成される場合
# 例: シード値 "mymanagerseed" から "managerhash" が生成される場合
# 例: シード値 "myspeakerseed" から "speakerhash" が生成される場合

OPERATOR_HASHES = ["your_admin_hash_here", "another_op_hash"] # あなたの運営アカウントのハッシュ
SUMMIT_HASHES = ["summit_hash_1", "summit_hash_2"] # サミットのハッシュ
MODERATOR_HASHES = ["mod_hash_1", "mod_hash_2"] # モデレーターのハッシュ
MANAGER_HASHES = ["manager_hash_1", "manager_hash_2"] # マネージャーのハッシュ
SPEAKER_HASHES = ["speaker_hash_1", "speaker_hash_2"] # スピーカーのハッシュ

# 権限と色のマッピング (CSSフレンドリーな色名またはHEXコード)
ROLE_COLORS = {
    "operator": "red",          # 運営：IDなし、名前赤色
    "summit": "darkcyan",       # サミット：ダークシアン
    "moderator": "darkmagenta", # モデレーター：ダークマゼンタ ← ここを変更
    "manager": "red",           # マネージャー：IDありの赤色
    "speaker": "orange",        # スピーカー：オレンジ
    "blue_id": "blue",          # 青ID：青色 (デフォルト)
    "default": "#333",          # その他の未定義のハッシュ（一般的なユーザー）
}
# ==========================================================

with app.app_context():
    db.create_all()
    if Topic.query.count() == 0:
        initial_topic = Topic(content="今の話題：設定されていません")
        db.session.add(initial_topic)
        db.session.commit()

# ヘルパー関数：ユーザーの権限レベルを判定
# 権限の優先順位に注意して並べています（上位権限を先にチェック）
def get_user_role(user_hash):
    if user_hash in OPERATOR_HASHES:
        return "operator"
    elif user_hash in SUMMIT_HASHES:
        return "summit"
    elif user_hash in MODERATOR_HASHES:
        return "moderator"
    elif user_hash in MANAGER_HASHES:
        return "manager"
    elif user_hash in SPEAKER_HASHES:
        return "speaker"
    if user_hash: # ハッシュがあれば青ID（デフォルトの色）
        return "blue_id"
    return "default" # ハッシュがない投稿（将来的な実装で考慮されるかも）

@app.route('/')
def index():
    posts = Post.query.order_by(Post.created_at.desc()).all()
    
    posts_for_display = []
    for post in posts:
        raw_name = post.username
        display_hash = ""
        if '@' in post.username:
            parts = post.username.split('@', 1)
            raw_name = parts[0]
            display_hash = parts[1]

        role = get_user_role(display_hash)
        name_color = ROLE_COLORS.get(role, ROLE_COLORS["default"])

        if role == "operator":
            display_name = raw_name
            display_id = ""
            name_color = ROLE_COLORS["operator"]
        else:
            display_name = raw_name
            display_id = display_hash

        posts_for_display.append({
            'id': post.id,
            'name': display_name,
            'display_id': display_id,
            'message': post.message,
            'created_at': post.created_at,
            'name_color': name_color,
        })

    current_topic = Topic.query.first()
    current_topic_content = current_topic.content if current_topic else "今の話題：設定されていません"

    return render_template('index.html', posts=posts_for_display,
                           current_topic=current_topic_content,
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

    seed_hash_full = hashlib.sha256(seed.encode('utf-8')).hexdigest()
    display_hash = seed_hash_full[:7]
    
    if message.startswith('/'):
        command_input = message.strip()
        command_parts = command_input.split(maxsplit=1)
        command = command_parts[0].lower()
        command_arg = command_parts[1] if len(command_parts) > 1 else ""

        allowed_to_command = False
        if command in ['/del', '/clear', '/topic']:
            if display_hash in OPERATOR_HASHES:
                allowed_to_command = True

        if not allowed_to_command:
            flash(f"コマンド '{command}' を実行する権限がありません。", 'error')
            return redirect(url_for('index'))

        if command == '/del':
            del_ids = command_arg.split()
            deleted_count = 0
            feedback_message_detail = []
            for post_id_str in del_ids:
                try:
                    post_id = int(post_id_str)
                    post_to_delete = Post.query.get(post_id)
                    if post_to_delete:
                        db.session.delete(post_to_delete)
                        deleted_count += 1
                    else:
                        feedback_message_detail.append(f"投稿番号 {post_id} が見つかりません。")
                except ValueError:
                    feedback_message_detail.append(f"無効な投稿番号: {post_id_str}")
            db.session.commit()
            if deleted_count > 0:
                flash(f"{deleted_count}件の投稿を削除しました。<br>" + "<br>".join(feedback_message_detail), 'success')
            else:
                flash("<br>".join(feedback_message_detail) or "指定された投稿は削除されませんでした。", 'info')
        elif command == '/clear':
            try:
                num_rows_deleted = db.session.query(Post).delete()
                db.session.commit()
                db.session.execute(db.text("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'post'"))
                db.session.commit()
                flash(f"{num_rows_deleted}件の全ての投稿を削除し、投稿番号をリセットしました。", 'success')
            except Exception as e:
                db.session.rollback()
                flash(f"全ての投稿の削除中にエラーが発生しました: {e}", 'error')
        elif command == '/topic':
            if command_arg:
                try:
                    current_topic_obj = Topic.query.first()
                    if current_topic_obj:
                        current_topic_obj.content = command_arg
                        db.session.commit()
                        flash(f"話題を「{command_arg}」に変更しました。", 'success')
                    else:
                        new_topic = Topic(content=command_arg)
                        db.session.add(new_topic)
                        db.session.commit()
                        flash(f"話題を「{command_arg}」に新規設定しました。", 'success')
                except Exception as e:
                    db.session.rollback()
                    flash(f"話題の変更中にエラーが発生しました: {e}", 'error')
            else:
                flash("/topic (話題にしたい内容) の形式で入力してください。", 'error')
        else:
            flash(f"不明なコマンド: {command}", 'error')

        return redirect(url_for('index'))

    final_username_to_save = f"{raw_username}@{display_hash}"
    new_post = Post(username=final_username_to_save, message=message)
    db.session.add(new_post)
    db.session.commit()
    flash('投稿が完了しました！', 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
