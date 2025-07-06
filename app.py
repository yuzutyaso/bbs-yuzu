from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import hashlib
import json

app = Flask(__name__)
basedir = os.os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'board.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_super_secret_key_for_flask_flash_messages_change_this_in_prod'

db = SQLAlchemy(app)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return '<Post %r>' % self.id

class Topic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(255), nullable=False, default="設定されていません")
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return '<Topic %r>' % self.content

# === 権限ごとのハッシュと色の定義 ===
OPERATOR_HASHES = ["fb2bfb4"] # あなたの運営アカウントのハッシュを設定してください

ROLES_FILE = os.path.join(basedir, 'roles.json')

# 名前の色 (主に運営用)
ROLE_NAME_COLORS = {
    "operator": "red",          # 運営の名前は赤
    "default": "black",         # デフォルトの名前の色
}

# IDの色 (直接HTMLに渡すため、CSSフレンドリーな色名またはHEXコード)
ROLE_ID_COLORS = {
    "blue_id": "blue",
    "speaker": "orange",
    "manager": "red",
    "moderator": "darkmagenta",
    "summit": "darkcyan",
    "operator": "red", # 運営はIDなしだが、便宜上定義
    "default": "black", # IDがないか、ハッシュがない場合のデフォルトID色
}

def load_roles():
    if not os.path.exists(ROLES_FILE):
        initial_roles = {
            "SUMMIT_HASHES": [],
            "MODERATOR_HASHES": [],
            "MANAGER_HASHES": [],
            "SPEAKER_HASHES": []
        }
        with open(ROLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(initial_roles, f, indent=4)
        return initial_roles
    
    with open(ROLES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_roles(roles_data):
    with open(ROLES_FILE, 'w', encoding='utf-8') as f:
        json.dump(roles_data, f, indent=4)

global_roles_data = load_roles()

with app.app_context():
    db.create_all()
    if Topic.query.count() == 0:
        initial_topic = Topic(content="今の話題：設定されていません")
        db.session.add(initial_topic)
        db.session.commit()

def get_user_role(user_hash):
    if user_hash in OPERATOR_HASHES:
        return "operator"
    elif user_hash in global_roles_data.get("SUMMIT_HASHES", []):
        return "summit"
    elif user_hash in global_roles_data.get("MODERATOR_HASHES", []):
        return "moderator"
    elif user_hash in global_roles_data.get("MANAGER_HASHES", []):
        return "manager"
    elif user_hash in global_roles_data.get("SPEAKER_HASHES", []):
        return "speaker"
    if user_hash:
        return "blue_id"
    return "default"

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
        
        # 名前の色とID表示ロジック
        if role == "operator":
            display_name = raw_name
            display_id = "" # 運営はIDなし
            name_color_for_html = ROLE_NAME_COLORS["operator"] # 運営の名前は赤
            id_color_for_html = "" # 運営はIDなしなので色も不要
        else:
            display_name = raw_name
            display_id = display_hash
            name_color_for_html = ROLE_NAME_COLORS["default"] # 運営以外の名前はデフォルト色
            id_color_for_html = ROLE_ID_COLORS.get(role, ROLE_ID_COLORS["default"]) # IDの色

        posts_for_display.append({
            'id': post.id,
            'name': display_name,
            'display_id': display_id,
            'message': post.message,
            'created_at': post.created_at,
            'name_color': name_color_for_html, # 名前の色
            'id_color': id_color_for_html,     # IDの色 (NEW!)
            'role': role, # ロール情報も引き続き渡す
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
    global global_roles_data

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

        if command == '/addrole':
            if display_hash not in OPERATOR_HASHES:
                flash(f"コマンド '{command}' を実行する権限がありません。", 'error')
                return redirect(url_for('index'))
            
            arg_parts = command_arg.split(maxsplit=1)
            if len(arg_parts) != 2:
                flash("'/addrole <ロール名> <ハッシュ>' の形式で入力してください。", 'error')
                return redirect(url_for('index'))
            
            role_to_add = arg_parts[0].upper()
            hash_to_add = arg_parts[1]

            valid_roles_for_add = ["SUMMIT_HASHES", "MODERATOR_HASHES", "MANAGER_HASHES", "SPEAKER_HASHES"]
            if role_to_add not in valid_roles_for_add:
                flash(f"無効なロール名です: {role_to_add}", 'error')
                return redirect(url_for('index'))
            
            if not (len(hash_to_add) == 7 and all(c in '0123456789abcdef' for c in hash_to_add)):
                 flash(f"無効なハッシュ形式です: {hash_to_add} (7文字の英数字小文字で指定してください)", 'error')
                 return redirect(url_for('index'))

            if hash_to_add not in global_roles_data[role_to_add]:
                global_roles_data[role_to_add].append(hash_to_add)
                save_roles(global_roles_data)
                flash(f"ロール '{role_to_add.replace('_HASHES', '')}' にハッシュ '{hash_to_add}' を追加しました。", 'success')
            else:
                flash(f"ハッシュ '{hash_to_add}' は既にロール '{role_to_add.replace('_HASHES', '')}' に存在します。", 'info')
            
            return redirect(url_for('index'))

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
