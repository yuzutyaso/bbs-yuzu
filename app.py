from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import hashlib
import json

app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'board.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_super_secret_key_for_flask_flash_messages_change_this_in_prod'

db = SQLAlchemy(app)

# 投稿のデータベースモデル (変更なし)
class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return '<Post %r>' % self.id

# トピックのデータベースモデル (変更なし)
class Topic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(255), nullable=False, default="設定されていません")
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return '<Topic %r>' % self.content

# === ユーザー情報（IDサフィックス用）のデータベースモデル追加 ===
class User(db.Model):
    # IDハッシュが主キー
    id_hash = db.Column(db.String(7), primary_key=True) 
    # 後ろにつける文字列
    suffix_text = db.Column(db.String(20), nullable=True)
    # サフィックスの色の指定
    suffix_color = db.Column(db.String(20), nullable=True, default="magenta") # デフォルトはマゼンタ

    def __repr__(self):
        return f'<User {self.id_hash}>'


# === 権限管理用のJSONファイル設定 ===
ROLES_FILE = os.path.join(basedir, 'roles.json')

# 運営アカウントのハッシュはコードに直接記述（最高権限のため）
OPERATOR_HASHES = ["fb2bfb4", "your_operator_hash_2"] # あなたの運営アカウントのハッシュを複数記入可能

# 名前の色 (主に運営用) (変更なし)
ROLE_NAME_COLORS = {
    "operator": "red",
    "default": "black",
}

# IDの色 (直接HTMLに渡すため、CSSフレンドリーな色名またはHEXコード) (変更なし)
ROLE_ID_COLORS = {
    "blue_id": "blue",
    "speaker": "darkorange",
    "manager": "red",
    "moderator": "darkmagenta",
    "summit": "darkcyan",
    "operator": "red",
    "default": "black",
}

# roles.jsonから権限データを読み込む関数 (変更なし)
def load_roles():
    if not os.path.exists(ROLES_FILE):
        initial_data = {
            "SUMMIT_HASHES": [],
            "MODERATOR_HASHES": [],
            "MANAGER_HASHES": [],
            "SPEAKER_HASHES": []
        }
        with open(ROLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(initial_data, f, indent=4)
        return initial_data
    
    try:
        with open(ROLES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"Error: {ROLES_FILE} is not a valid JSON file. Reinitializing.")
        initial_data = {
            "SUMMIT_HASHES": [],
            "MODERATOR_HASHES": [],
            "MANAGER_HASHES": [],
            "SPEAKER_HASHES": []
        }
        with open(ROLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(initial_data, f, indent=4)
        return initial_data
    except Exception as e:
        print(f"Error loading {ROLES_FILE}: {e}")
        return {
            "SUMMIT_HASHES": [],
            "MODERATOR_HASHES": [],
            "MANAGER_HASHES": [],
            "SPEAKER_HASHES": []
        }

# 権限データをroles.jsonに保存する関数 (変更なし)
def save_roles(roles_data):
    try:
        with open(ROLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(roles_data, f, indent=4)
    except Exception as e:
        print(f"Error saving {ROLES_FILE}: {e}")

# アプリケーション起動時に権限データを読み込む (変更なし)
global_roles_data = load_roles()

with app.app_context():
    db.create_all() # 新しいUserモデルのテーブルも作成されます
    if Topic.query.count() == 0:
        initial_topic = Topic(content="今の話題：設定されていません")
        db.session.add(initial_topic)
        db.session.commit()

# ヘルパー関数：ユーザーの権限レベルを判定 (変更なし)
def get_user_role(user_hash):
    if user_hash in OPERATOR_HASHES:
        return "operator"
    if user_hash in global_roles_data.get("SUMMIT_HASHES", []):
        return "summit"
    if user_hash in global_roles_data.get("MODERATOR_HASHES", []):
        return "moderator"
    if user_hash in global_roles_data.get("MANAGER_HASHES", []):
        return "manager"
    if user_hash in global_roles_data.get("SPEAKER_HASHES", []):
        return "speaker"
    if user_hash:
        return "blue_id"
    return "default"

# ヘルパー関数：指定された権限を持つかチェック (変更なし)
def has_permission(user_role, required_role):
    roles_hierarchy = {
        "default": 0,
        "blue_id": 1,
        "speaker": 2,
        "manager": 3,
        "moderator": 4,
        "summit": 5,
        "operator": 6
    }
    return roles_hierarchy.get(user_role, 0) >= roles_hierarchy.get(required_role, 0)

@app.route('/')
def index():
    posts = Post.query.order_by(Post.created_at.desc()).all()
    
    posts_for_display = []
    for post in posts:
        raw_name = post.username
        display_hash = ""
        # ユーザー名からハッシュと元の名前を分離
        if '@' in post.username:
            parts = post.username.split('@', 1)
            raw_name = parts[0]
            display_hash = parts[1]

        role = get_user_role(display_hash) # ユーザーのロール（権限名）を取得
        
        # 名前の色とID表示ロジック
        name_color_for_html = ROLE_NAME_COLORS["default"]
        id_color_for_html = ROLE_ID_COLORS.get(role, ROLE_ID_COLORS["default"])
        suffix_text_for_html = "" # 追加するサフィックス文字
        suffix_color_for_html = "" # サフィックス文字の色

        if role == "operator":
            display_name = raw_name
            display_id = "" # 運営はIDなし
            name_color_for_html = ROLE_NAME_COLORS["operator"]
            id_color_for_html = "" # 運営はIDなしなので色も不要
        else:
            display_name = raw_name
            display_id = display_hash
            # === ここから追加: ユーザーサフィックスの取得と適用 ===
            user_settings = User.query.get(display_hash)
            if user_settings and user_settings.suffix_text:
                suffix_text_for_html = user_settings.suffix_text
                suffix_color_for_html = user_settings.suffix_color or "magenta" # デフォルトはマゼンタ
            # ====================================================

        posts_for_display.append({
            'id': post.id,
            'name': display_name,
            'display_id': display_id,
            'message': post.message,
            'created_at': post.created_at,
            'name_color': name_color_for_html,
            'id_color': id_color_for_html,
            'suffix_text': suffix_text_for_html, # 新しく追加
            'suffix_color': suffix_color_for_html, # 新しく追加
            'role': role,
        })

    current_topic = Topic.query.first()
    current_topic_content = current_topic.content if current_topic else "今の話題：設定されていません"

    return render_template('index.html', posts=posts_for_display,
                           current_topic=current_topic_content,
                           prev_name=request.args.get('prev_name', ''),
                           prev_message=request.args.get('prev_message', ''),
                           prev_seed=request.args.get('prev_seed', ''))

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
    user_hash = display_hash = seed_hash_full[:7] # コマンド実行者のハッシュ

    # コマンド処理
    if message.startswith('/'):
        command_input = message.strip()
        command_parts = command_input.split(maxsplit=1)
        command = command_parts[0].lower()
        command_arg = command_parts[1] if len(command_parts) > 1 else ""

        executor_role = get_user_role(user_hash) # コマンド実行者の権限

        # === 権限付与・降格コマンドの処理 (変更なし) ===
        target_id = ""
        if len(command_arg) > 0:
            target_id = command_arg.split()[0]

        if command in ['/speaker', '/manager', '/moderator', '/summit', '/operator']:
            target_role_name = command[1:]
            
            if target_role_name == 'speaker' and not has_permission(executor_role, 'manager'):
                flash(f"スピーカー権限を付与するにはマネージャー以上の権限が必要です。", 'error')
                return redirect(url_for('index'))
            elif target_role_name in ['manager', 'moderator'] and not has_permission(executor_role, 'summit'):
                flash(f"{target_role_name}権限を付与するにはサミット以上の権限が必要です。", 'error')
                return redirect(url_for('index'))
            elif target_role_name == 'summit' and not has_permission(executor_role, 'operator'):
                flash(f"サミット権限を付与するには運営権限が必要です。", 'error')
                return redirect(url_for('index'))
            elif target_role_name == 'operator' and not has_permission(executor_role, 'operator'):
                flash(f"運営権限を付与するには運営権限が必要です。", 'error')
                return redirect(url_for('index'))
            
            if not target_id:
                flash(f"{command} コマンドには対象のIDを指定してください。", 'error')
                return redirect(url_for('index'))

            target_list_name = target_role_name.upper() + "_HASHES"
            if target_id not in global_roles_data.get(target_list_name, []):
                for role_key in global_roles_data.keys():
                    if target_id in global_roles_data[role_key]:
                        global_roles_data[role_key].remove(target_id)
                        break

                global_roles_data.setdefault(target_list_name, []).append(target_id)
                save_roles(global_roles_data)
                flash(f"ID '{target_id}' に {target_role_name} 権限を付与しました。", 'success')
            else:
                flash(f"ID '{target_id}' は既に {target_role_name} 権限を持っています。", 'info')
            return redirect(url_for('index'))

        elif command.startswith('/dis') and command not in ['/disself']:
            target_role_name = command[4:]
            
            if target_role_name == 'speaker' and not has_permission(executor_role, 'manager'):
                flash(f"スピーカー権限を降格するにはマネージャー以上の権限が必要です。", 'error')
                return redirect(url_for('index'))
            elif target_role_name == 'manager' and not has_permission(executor_role, 'moderator'):
                flash(f"マネージャー権限を降格するにはモデレーター以上の権限が必要です。", 'error')
                return redirect(url_for('index'))
            elif target_role_name == 'moderator' and not has_permission(executor_role, 'summit'):
                flash(f"モデレーター権限を降格するにはサミット以上の権限が必要です。", 'error')
                return redirect(url_for('index'))
            elif target_role_name == 'summit' and not has_permission(executor_role, 'operator'):
                flash(f"サミット権限を降格するには運営権限が必要です。", 'error')
                return redirect(url_for('index'))
            elif target_role_name == 'operator' and not has_permission(executor_role, 'operator'):
                flash(f"運営権限を降格するには運営権限が必要です。", 'error')
                return redirect(url_for('index'))

            if not target_id:
                flash(f"{command} コマンドには対象のIDを指定してください。", 'error')
                return redirect(url_for('index'))

            target_list_name = target_role_name.upper() + "_HASHES"
            if target_id in global_roles_data.get(target_list_name, []):
                global_roles_data[target_list_name].remove(target_id)
                save_roles(global_roles_data)
                flash(f"ID '{target_id}' から {target_role_name} 権限を降格しました。", 'success')
            else:
                flash(f"ID '{target_id}' は {target_role_name} 権限を持っていません。", 'info')
            return redirect(url_for('index'))

        elif command == '/disself':
            removed_from_any_role = False
            for role_key in global_roles_data.keys():
                if user_hash in global_roles_data[role_key]:
                    global_roles_data[role_key].remove(user_hash)
                    removed_from_any_role = True
            
            if user_hash in OPERATOR_HASHES:
                flash("運営アカウントは /disself コマンドの対象外です。", 'error')
                return redirect(url_for('index'))

            if removed_from_any_role:
                save_roles(global_roles_data)
                flash("あなたの権限を青IDにリセットしました。", 'success')
            else:
                flash("あなたは既に青IDまたはデフォルト権限です。", 'info')
            return redirect(url_for('index'))

        # === /add コマンドの処理を追加 ===
        elif command == '/add':
            # スピーカー以上の権限が必要と仮定
            if not has_permission(executor_role, 'speaker'): 
                flash(f"コマンド '{command}' を実行する権限がありません。（スピーカー以上が必要です）", 'error')
                return redirect(url_for('index'))
            
            suffix_text = command_arg.strip()
            if not suffix_text:
                flash("/add コマンドには追加したい文字を指定してください。", 'error')
                return redirect(url_for('index'))

            # UserテーブルにIDハッシュで検索または新規作成
            user_setting = User.query.get(user_hash)
            if not user_setting:
                user_setting = User(id_hash=user_hash)
                db.session.add(user_setting)
            
            user_setting.suffix_text = suffix_text
            user_setting.suffix_color = "magenta" # デフォルトでマゼンタに設定

            db.session.commit()
            flash(f"ID '{user_hash}' の後ろに '{suffix_text}' (マゼンタ) を設定しました。", 'success')
            return redirect(url_for('index'))
        # ==================================

        # 既存のコマンド処理（変更なし）
        elif command == '/del':
            if not has_permission(executor_role, 'manager'):
                flash(f"コマンド '{command}' を実行する権限がありません。", 'error')
                return redirect(url_for('index'))
            
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
            if not has_permission(executor_role, 'moderator'):
                flash(f"コマンド '{command}' を実行する権限がありません。", 'error')
                return redirect(url_for('index'))
            
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
            if not has_permission(executor_role, 'manager'):
                flash(f"コマンド '{command}' を実行する権限がありません。", 'error')
                return redirect(url_for('index'))
            
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

    # コマンドではない通常の投稿の場合 (変更なし)
    final_username_to_save = f"{raw_username}@{display_hash}"
    new_post = Post(username=final_username_to_save, message=message)
    db.session.add(new_post)
    db.session.commit()
    flash('投稿が完了しました！', 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
