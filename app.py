from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import hashlib

app = Flask(__name__)
basedir = os.os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'board.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# 本番環境ではこのSECRET_KEYをもっと複雑な値に変更してください！
app.config['SECRET_KEY'] = 'your_super_secret_key_for_flask_flash_messages_change_this_in_prod'

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
    content = db.Column(db.String(255), nullable=False, default="設定されていません") # 現在の話題
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return '<Topic %r>' % self.content

# === 権限ごとのハッシュと色の定義 (ここをあなたの環境に合わせて設定してください！) ===
# 各権限に割り当てたいユーザーのシード値から生成される7文字のハッシュを設定してください。
# 例: シード値 "myadminseed" から "your_admin_hash_here" が生成される場合
# Pythonでハッシュを確認する方法:
# import hashlib
# print(hashlib.sha256("あなたのシード値".encode('utf-8')).hexdigest()[:7])

OPERATOR_HASHES = ["fb2bfb4"] # 運営アカウントのハッシュ（例: "fb2bfb4" は運営シードから生成されるハッシュ）
SUMMIT_HASHES = [] # サミットのハッシュリスト (例: ["summit_hash_abc", "summit_hash_def"])
MODERATOR_HASHES = [] # モデレーターのハッシュリスト (例: ["mod_hash_123", "mod_hash_456"])
MANAGER_HASHES = [] # マネージャーのハッシュリスト (例: ["mgr_hash_789", "mgr_hash_012"])
SPEAKER_HASHES = [] # スピーカーのハッシュリスト (例: ["spk_hash_345", "spk_hash_678"])

# 権限と色のマッピング (CSSフレンドリーな色名またはHEXコード)
ROLE_COLORS = {
    "operator": "red",          # 運営：IDなし、名前赤色
    "summit": "darkcyan",       # サミット：ダークシアン
    "moderator": "darkmagenta", # モデレーター：ダークマゼンタ
    "manager": "red",           # マネージャー：IDありの赤色 (運営と同じ赤ですが、IDの有無で区別)
    "speaker": "orange",        # スピーカー：オレンジ
    "blue_id": "blue",          # 青ID：青色 (特定の権限に属さないがハッシュを持つユーザー)
    "default": "#333",          # その他のユーザー（ハッシュがない、または未定義のハッシュ）
}
# ==========================================================

# データベースの初期化とトピックの作成
with app.app_context():
    db.create_all()
    # アプリケーション起動時にトピックがなければ初期値を設定
    if Topic.query.count() == 0:
        initial_topic = Topic(content="今の話題：設定されていません")
        db.session.add(initial_topic)
        db.session.commit()

# ヘルパー関数：ユーザーの権限レベルを判定
# 権限の優先順位は、リストの上から順にチェックされます。
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
    if user_hash: # 上記どの権限にも属さないがハッシュを持つ場合は「青シード」
        return "blue_id"
    return "default" # ハッシュを持たない場合はデフォルト（青IDとは異なる扱い）

@app.route('/')
def index():
    posts = Post.query.order_by(Post.created_at.desc()).all()
    
    # 投稿ごとに表示用の情報を付与
    posts_for_display = []
    for post in posts:
        # ユーザー名から名前とハッシュを分離
        raw_name = post.username
        display_hash = ""
        if '@' in post.username:
            parts = post.username.split('@', 1) # 最初の@で分割
            raw_name = parts[0]
            display_hash = parts[1]

        role = get_user_role(display_hash)
        name_color = ROLE_COLORS.get(role, ROLE_COLORS["default"]) # 権限に応じた色を取得

        # 運営の場合の特別処理: ID非表示、名前は運営用赤色
        if role == "operator":
            display_name = raw_name # 運営はハッシュ非表示
            display_id = "" # ID欄も空にする
            name_color = ROLE_COLORS["operator"] # 運営の色 (赤)
        else:
            display_name = raw_name
            display_id = display_hash # 通常のID表示 (@付き)

        posts_for_display.append({
            'id': post.id,
            'name': display_name,
            'display_id': display_id, # 表示用のID（ハッシュ）
            'message': post.message,
            'created_at': post.created_at,
            'name_color': name_color, # 名前の色
        })

    current_topic = Topic.query.first() # 常に最初の（唯一の）トピックを取得
    current_topic_content = current_topic.content if current_topic else "今の話題：設定されていません"

    return render_template('index.html', posts=posts_for_display, # 加工した投稿リストを渡す
                           current_topic=current_topic_content, # トピックをテンプレートに渡す
                           prev_name=request.args.get('prev_name', ''), # エラー時の入力保持
                           prev_seed=request.args.get('prev_seed', ''),   # エラー時の入力保持
                           prev_message=request.args.get('prev_message', '')) # エラー時の入力保持

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
    
    # コマンド処理の分岐
    if message.startswith('/'):
        command_input = message.strip()
        command_parts = command_input.split(maxsplit=1) # 最初のスペースで分割
        command = command_parts[0].lower() # コマンド名を小文字に変換
        command_arg = command_parts[1] if len(command_parts) > 1 else ""

        # コマンド実行権限チェック
        # 各コマンドに必要な権限レベルを設定できます。
        allowed_to_command = False
        if command in ['/del', '/clear', '/topic']:
            # これらのコマンドは運営のみ実行可能
            if display_hash in OPERATOR_HASHES:
                allowed_to_command = True
        # ここに他のコマンドとそれに対応する権限チェックを追加できます。
        # 例: elif command == '/ban':
        #         if display_hash in MODERATOR_HASHES or display_hash in OPERATOR_HASHES:
        #             allowed_to_command = True

        if not allowed_to_command:
            flash(f"コマンド '{command}' を実行する権限がありません。", 'error')
            return redirect(url_for('index'))

        # 各コマンド処理の実行
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
                # SQLiteのシーケンスIDをリセット
                db.session.execute(db.text("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'post'"))
                db.session.commit()
                flash(f"{num_rows_deleted}件の全ての投稿を削除し、投稿番号をリセットしました。", 'success')
            except Exception as e:
                db.session.rollback()
                flash(f"全ての投稿の削除中にエラーが発生しました: {e}", 'error')
        elif command == '/topic':
            if command_arg: # トピックの内容があるかチェック
                try:
                    current_topic_obj = Topic.query.first()
                    if current_topic_obj:
                        current_topic_obj.content = command_arg
                        db.session.commit()
                        flash(f"話題を「{command_arg}」に変更しました。", 'success')
                    else: # トピックがDBに存在しない場合（通常は初期化で作成されるはずですが念のため）
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

        # コマンドが実行された場合、その投稿自体は掲示板には表示しないためリダイレクト
        return redirect(url_for('index'))

    # コマンドではない通常の投稿の場合
    # DBにはハッシュ付きのユーザー名を保存します
    final_username_to_save = f"{raw_username}@{display_hash}"
    new_post = Post(username=final_username_to_save, message=message)
    db.session.add(new_post)
    db.session.commit()
    flash('投稿が完了しました！', 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
