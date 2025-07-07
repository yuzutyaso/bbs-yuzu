import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_socketio import SocketIO, emit
import re
import hashlib
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key' # 実際の運用ではより複雑なキーに設定してください
socketio = SocketIO(app)

# 仮のデータベース（本番では永続化されたDBを使用してください）
posts = []
next_post_id = 1
current_topic = "岡山アンチの投稿を永遠に規制中" # 初期話題

# ユーザーの権限とIDに付与するテキスト
# 'role_name': {'color': 'CSS color', 'suffix': 'Suffix Text'}
ROLES = {
    'normal': {'color': 'black', 'suffix': ''},
    'speaker': {'color': 'darkorange', 'suffix': 'スピーカー'},
    'manager': {'color': 'blue', 'suffix': 'マネージャー'},
    'moderator': {'color': 'green', 'suffix': 'モデレーター'},
    'summit': {'color': '#00fa9a', 'suffix': 'サミット'}, # 水色
    'operator': {'color': 'red', 'suffix': '運営'} # 赤色
}

# ユーザーごとのカスタム接尾辞 (suffix_text)
user_suffixes = {} # {display_id: {'text': 'suffix', 'color': 'magenta'}}

# ユーザーの色設定
user_colors = {} # {display_id: 'color_code'}

# NGワードリスト
ng_words = []

# 投稿禁止設定
prevent_blue_id_post = False
restrict_blue_id_post = False
stop_blue_id_until = 0 # タイムスタンプ

# 投稿最大数
max_posts = 100

def get_display_id(name, seed):
    """名前とシード値から一意の表示用IDを生成する"""
    combined_string = f"{name}-{seed}"
    # SHA256ハッシュの最初の7文字を使用
    hash_object = hashlib.sha256(combined_string.encode())
    return hash_object.hexdigest()[:7].upper()

def get_user_role(display_id):
    """ユーザーの権限を取得する（セッションから）"""
    return session.get(f'role_{display_id}', 'normal')

def set_user_role(display_id, role):
    """ユーザーの権限を設定する（セッションに保存）"""
    if role in ROLES:
        session[f'role_{display_id}'] = role
        return True
    return False

def get_post_data(post):
    display_id = get_display_id(post['name'], post['seed'])
    role = get_user_role(display_id)
    role_info = ROLES.get(role, ROLES['normal'])

    # ユーザー名の色を決定 (カスタム設定があれば優先)
    name_color = user_colors.get(display_id, role_info['color'])

    # ID表示とその色、接尾辞を決定
    # デフォルトのID表示色を定義
    default_id_color = 'darkcyan' 
    id_color = default_id_color # デフォルトは青緑
    suffix_text = role_info['suffix']
    suffix_color = 'magenta' # 接尾辞のデフォルト色

    # /add コマンドで設定された接尾辞があればそれを使用
    if display_id in user_suffixes:
        suffix_data = user_suffixes[display_id]
        suffix_text = suffix_data['text']
        suffix_color = suffix_data['color'] # /addで設定された色を使用

    return {
        'id': post['id'],
        'name': post['name'],
        'message': post['message'],
        'name_color': name_color,
        'display_id': display_id,
        'id_color': id_color, # 現在は常に青緑
        'suffix_text': suffix_text,
        'suffix_color': suffix_color
    }

def check_ng_words(message):
    for word in ng_words:
        if word in message:
            return True
    return False

@app.route('/')
def index():
    # 投稿を逆順にして表示（最新のものが上に来るように）
    display_posts = [get_post_data(post) for post in posts]
    
    # セッションから前回の入力内容をロード
    prev_message = session.pop('prev_message', '')
    prev_name = session.pop('prev_name', '')
    prev_seed = session.pop('prev_seed', '')

    return render_template('index.html', 
                           posts=display_posts[::-1], 
                           current_topic=current_topic,
                           prev_message=prev_message,
                           prev_name=prev_name,
                           prev_seed=prev_seed)

@app.route('/post', methods=['POST'])
def post_message():
    global next_post_id, current_topic, prevent_blue_id_post, restrict_blue_id_post, stop_blue_id_until, ng_words

    message = request.form['message']
    name = request.form['name']
    seed = request.form['seed']

    # 入力値をセッションに保存（リダイレクト後にフォームに再入力するため）
    session['prev_message'] = message
    session['prev_name'] = name
    session['prev_seed'] = seed

    display_id = get_display_id(name, seed)
    user_role = get_user_role(display_id)

    # NGワードチェック
    if check_ng_words(message):
        flash('メッセージにNGワードが含まれています。', 'error')
        return redirect(url_for('index'))

    # 青ID投稿禁止/制限のチェック
    if display_id.startswith('7') or display_id.startswith('8') or display_id.startswith('9'): # 青IDの判定
        if prevent_blue_id_post:
            flash('現在、青IDユーザーの投稿は禁止されています。', 'error')
            return redirect(url_for('index'))
        if restrict_blue_id_post and user_role == 'normal': # normalロールの青IDのみ制限
            flash('現在、青ID（一般ユーザー）の投稿は制限されています。', 'error')
            return redirect(url_for('index'))
        if stop_blue_id_until > time.time():
            remaining_time = int(stop_blue_id_until - time.time())
            flash(f'現在、青IDユーザーの投稿は一時的に禁止されています。残り{remaining_time}秒。', 'error')
            return redirect(url_for('index'))

    # コマンド処理
    if message.startswith('/'):
        parts = message.split(' ', 1)
        command = parts[0]
        arg = parts[1] if len(parts) > 1 else ''

        # 権限チェック関数
        def check_permission(required_role_level):
            role_levels = {'normal': 0, 'speaker': 1, 'manager': 2, 'moderator': 3, 'summit': 4, 'operator': 5}
            user_level = role_levels.get(user_role, 0)
            required_level = role_levels.get(required_role_level, 0)
            return user_level >= required_level

        if command == '/del':
            if not check_permission('speaker'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            try:
                ids_to_delete = [int(i.strip()) for i in arg.split(',')]
                original_posts_len = len(posts)
                global posts
                posts = [p for p in posts if p['id'] not in ids_to_delete]
                if len(posts) < original_posts_len:
                    flash(f'{original_posts_len - len(posts)}件の投稿を削除しました。', 'success')
                    socketio.emit('post_deleted', {'deleted_ids': ids_to_delete}, broadcast=True)
                else:
                    flash('指定された投稿IDは見つかりませんでした。', 'info')
            except ValueError:
                flash('削除する投稿のIDを正しく指定してください。(例: /del 1,2,3)', 'error')
        elif command == '/clear':
            if not check_permission('manager'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            posts.clear()
            next_post_id = 1
            flash('全ての投稿が削除され、IDがリセットされました。', 'success')
            socketio.emit('posts_cleared', broadcast=True)
        elif command == '/topic':
            if not check_permission('moderator'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            current_topic = arg
            flash(f'話題を「{current_topic}」に変更しました。', 'success')
            socketio.emit('topic_updated', {'topic': current_topic}, broadcast=True)
        elif command == '/speaker':
            if not check_permission('manager'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            target_id = arg.strip()
            if set_user_role(target_id, 'speaker'):
                flash(f'ユーザーID {target_id} にスピーカー権限を付与しました。', 'success')
                socketio.emit('roles_updated', {'display_id': target_id, 'role': 'speaker'}, broadcast=True)
            else:
                flash(f'ユーザーID {target_id} にスピーカー権限を付与できませんでした。', 'error')
        elif command == '/manager':
            if not check_permission('moderator'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            target_id = arg.strip()
            if set_user_role(target_id, 'manager'):
                flash(f'ユーザーID {target_id} にマネージャー権限を付与しました。', 'success')
                socketio.emit('roles_updated', {'display_id': target_id, 'role': 'manager'}, broadcast=True)
            else:
                flash(f'ユーザーID {target_id} にマネージャー権限を付与できませんでした。', 'error')
        elif command == '/moderator':
            if not check_permission('summit'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            target_id = arg.strip()
            if set_user_role(target_id, 'moderator'):
                flash(f'ユーザーID {target_id} にモデレーター権限を付与しました。', 'success')
                socketio.emit('roles_updated', {'display_id': target_id, 'role': 'moderator'}, broadcast=True)
            else:
                flash(f'ユーザーID {target_id} にモデレーター権限を付与できませんでした。', 'error')
        elif command == '/summit':
            if not check_permission('operator'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            target_id = arg.strip()
            if set_user_role(target_id, 'summit'):
                flash(f'ユーザーID {target_id} にサミット権限を付与しました。', 'success')
                socketio.emit('roles_updated', {'display_id': target_id, 'role': 'summit'}, broadcast=True)
            else:
                flash(f'ユーザーID {target_id} にサミット権限を付与できませんでした。', 'error')
        elif command == '/operator':
            # operator権限は現状、コード内でしか付与できない（最上位権限のため）
            flash('このコマンドでは運営権限を付与できません。', 'error')
        elif command == '/disspeaker':
            if not check_permission('manager'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            target_id = arg.strip()
            if set_user_role(target_id, 'normal'): # スピーカー権限を剥奪しnormalに
                flash(f'ユーザーID {target_id} のスピーカー権限を解除しました。', 'success')
                socketio.emit('roles_updated', {'display_id': target_id, 'role': 'normal'}, broadcast=True)
            else:
                flash(f'ユーザーID {target_id} のスピーカー権限を解除できませんでした。', 'error')
        elif command == '/dismanager':
            if not check_permission('moderator'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            target_id = arg.strip()
            if set_user_role(target_id, 'speaker'): # マネージャー権限を剥奪しスピーカーに
                flash(f'ユーザーID {target_id} のマネージャー権限を解除しました。', 'success')
                socketio.emit('roles_updated', {'display_id': target_id, 'role': 'speaker'}, broadcast=True)
            else:
                flash(f'ユーザーID {target_id} のマネージャー権限を解除できませんでした。', 'error')
        elif command == '/dismoderator':
            if not check_permission('summit'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            target_id = arg.strip()
            if set_user_role(target_id, 'manager'): # モデレーター権限を剥奪しマネージャーに
                flash(f'ユーザーID {target_id} のモデレーター権限を解除しました。', 'success')
                socketio.emit('roles_updated', {'display_id': target_id, 'role': 'manager'}, broadcast=True)
            else:
                flash(f'ユーザーID {target_id} のモデレーター権限を解除できませんでした。', 'error')
        elif command == '/dissummit':
            if not check_permission('operator'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            target_id = arg.strip()
            if set_user_role(target_id, 'moderator'): # サミット権限を剥奪しモデレーターに
                flash(f'ユーザーID {target_id} のサミット権限を解除しました。', 'success')
                socketio.emit('roles_updated', {'display_id': target_id, 'role': 'moderator'}, broadcast=True)
            else:
                flash(f'ユーザーID {target_id} のサミット権限を解除できませんでした。', 'error')
        elif command == '/disoperator':
            flash('このコマンドでは運営権限を解除できません。', 'error')
        elif command == '/disself':
            if user_role != 'normal':
                set_user_role(display_id, 'normal')
                flash('自身の権限を青IDにリセットしました。', 'success')
                socketio.emit('roles_updated', {'display_id': display_id, 'role': 'normal'}, broadcast=True)
            else:
                flash('既に青IDです。', 'info')
        elif command == '/add':
            if not check_permission('speaker'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            if arg:
                user_suffixes[display_id] = {'text': arg, 'color': 'magenta'} # デフォルトでマゼンタ色
                flash(f'IDに「{arg}」を追加しました。', 'success')
                socketio.emit('user_suffix_updated', {'display_id': display_id, 'suffix_text': arg}, broadcast=True)
            else:
                flash('IDに追加する文字を指定してください。(例: /add 文字)', 'error')
        elif command == '/destroy':
            if not check_permission('manager'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            if arg:
                original_posts_len = len(posts)
                global posts
                posts = [p for p in posts if arg not in p['message']]
                if len(posts) < original_posts_len:
                    flash(f'「{arg}」を含む投稿を全て削除しました。', 'success')
                    socketio.emit('request_posts_update', broadcast=True) # 全体を更新
                else:
                    flash(f'「{arg}」を含む投稿は見つかりませんでした。', 'info')
            else:
                flash('削除する文字を指定してください。(例: /destroy 不快な内容)', 'error')
        elif command == '/NG':
            if not check_permission('moderator'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            word_to_add = arg.strip()
            if word_to_add and word_to_add not in ng_words:
                ng_words.append(word_to_add)
                flash(f'NGワード「{word_to_add}」を追加しました。', 'success')
            else:
                flash('有効なNGワードを指定してください。', 'error')
        elif command == '/OK':
            if not check_permission('moderator'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            word_to_remove = arg.strip()
            if word_to_remove in ng_words:
                ng_words.remove(word_to_remove)
                flash(f'NGワード「{word_to_remove}」を解除しました。', 'success')
            else:
                flash('指定されたNGワードは見つかりませんでした。', 'info')
        elif command == '/prevent':
            if not check_permission('manager'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            prevent_blue_id_post = True
            flash('青IDユーザーの投稿を禁止しました。', 'success')
        elif command == '/permit':
            if not check_permission('manager'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            prevent_blue_id_post = False
            flash('/prevent を解除しました。', 'success')
        elif command == '/restrict':
            if not check_permission('manager'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            restrict_blue_id_post = True
            flash('青IDユーザーの投稿を制限しました。', 'success')
        elif command == '/stop':
            if not check_permission('moderator'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            stop_blue_id_until = time.time() + 180 # 3分間
            flash('3分間、青IDユーザーの投稿を禁止しました。', 'success')
        elif command == '/prohibit':
            if not check_permission('moderator'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            try:
                duration_minutes = int(arg)
                stop_blue_id_until = time.time() + (duration_minutes * 60)
                flash(f'{duration_minutes}分間、青IDユーザーの投稿を禁止しました。', 'success')
            except ValueError:
                flash('禁止する時間を分単位で指定してください。(例: /prohibit 10)', 'error')
        elif command == '/release':
            if not check_permission('manager'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            prevent_blue_id_post = False
            restrict_blue_id_post = False
            stop_blue_id_until = 0
            flash('全ての投稿規制を解除しました。', 'success')
        elif command == '/kill':
            if not check_permission('operator'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            target_id = arg.strip()
            # ここでは簡単のため、特定のIDの投稿を不可視にするなどの処理は省略
            flash(f'ユーザーID {target_id} のアカウントを使用不能にしました（仮）。', 'success')
        elif command == '/ban':
            if not check_permission('operator'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            # IPBANや投稿番号BANの具体的なロジックは実装が必要
            flash(f'IPまたは投稿番号 {arg} でBANしました（仮）。', 'success')
        elif command == '/revive':
            if not check_permission('operator'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            flash(f'/kill, /ban を解除しました（仮）。', 'success')
        elif command == '/reduce':
            if not check_permission('operator'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            flash('権限全体の2%を削除しました（仮）。', 'success')
        elif command == '/color':
            if not check_permission('speaker'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            color_parts = arg.split(' ', 1)
            color_code = color_parts[0].strip()
            target_id_for_color = color_parts[1].strip() if len(color_parts) > 1 else display_id # ID指定がなければ自分
            
            # 色コードの簡単なバリデーション (例: #RRGGBB形式)
            if re.match(r'^#[0-9a-fA-F]{6}$', color_code) or color_code in ['red', 'blue', 'green', 'purple', 'black', 'white']: # その他の色も追加可能
                user_colors[target_id_for_color] = color_code
                flash(f'ユーザーID {target_id_for_color} の名前の色を {color_code} に変更しました。', 'success')
                socketio.emit('request_posts_update', broadcast=True)
            else:
                flash('有効な色コード（例: #FF00FF または red）を指定してください。', 'error')
        elif command == '/instances':
            if not check_permission('speaker'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            flash('インスタンスを登録/閲覧します（仮）。', 'info')
        elif command == '/max':
            if not check_permission('manager'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            try:
                new_max = int(arg)
                if new_max > 0:
                    global max_posts
                    max_posts = new_max
                    # 古い投稿を削除して上限に合わせる
                    if len(posts) > max_posts:
                        del posts[0:len(posts) - max_posts]
                    flash(f'投稿数の上限を{max_posts}件に設定しました。', 'success')
                    socketio.emit('request_posts_update', broadcast=True)
                else:
                    flash('投稿上限は正の数を指定してください。', 'error')
            except ValueError:
                flash('投稿数の上限を数値で指定してください。(例: /max 50)', 'error')
        elif command == '/range':
            if not check_permission('manager'):
                flash('このコマンドを実行する権限がありません。', 'error')
                return redirect(url_for('index'))
            flash('表示投稿数を変更します（仮）。', 'info') # 表示数の変更はフロントエンド側の実装が必要
        else:
            flash(f'不明なコマンド: {command}', 'error')
        
        return redirect(url_for('index')) # コマンド処理後はリダイレクト

    # 通常の投稿処理
    new_post = {
        'id': next_post_id,
        'name': name,
        'message': message,
        'seed': seed,
    }
    posts.append(new_post)
    next_post_id += 1

    # 投稿が最大数を超えた場合、古いものから削除
    if len(posts) > max_posts:
        del posts[0]

    socketio.emit('update_posts', {'posts': [get_post_data(p) for p in posts[::-1]], 'current_topic': current_topic}, broadcast=True)
    
    #
