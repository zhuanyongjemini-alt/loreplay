import streamlit as st
import os
import datetime
import requests
import base64
import random
import re
from google import genai
from google.genai import types
from supabase import create_client, Client

# 🌟 ページの設定
st.set_page_config(
    page_title="AI Roleplay App",
    page_icon="💬",
    layout="centered",
    initial_sidebar_state="expanded"
)

# =================================================================
# 🌟 Supabaseクライアントの初期化
# =================================================================
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase_client = init_supabase()

# =================================================================
# 🌟 データベース操作用の関数
# =================================================================
def load_sessions_from_supabase(character_name: str):
    """該当キャラクターのチャット部屋一覧を新着順に取得する"""
    try:
        res = supabase_client.table("chat_sessions") \
            .select("*") \
            .eq("character_name", character_name) \
            .order("created_at", desc=True) \
            .execute()
        return res.data
    except Exception as e:
        st.error(f"セッション一覧の取得に失敗: {e}")
        return []

def create_new_session(character_name: str, title: str):
    """新しくチャット部屋（スレッド）を作成する"""
    try:
        res = supabase_client.table("chat_sessions").insert({
            "character_name": character_name,
            "title": title
        }).execute()
        return res.data[0]
    except Exception as e:
        st.error(f"新規セッションの作成に失敗: {e}")
        return None

def update_session_title(session_id: str, new_title: str):
    """チャット部屋のタイトルを更新する（最初の1言目送信時に使用）"""
    try:
        supabase_client.table("chat_sessions") \
            .update({"title": new_title}) \
            .eq("id", session_id) \
            .execute()
    except Exception:
        pass

def save_chat_to_supabase(role: str, name: str, content: str, session_id: str):
    """メッセージを特定のチャット部屋に保存し、生成されたDBのIDを返す"""
    gemini_role = "user" if role == "user" else "model"
    try:
        res = supabase_client.table("chat_messages").insert({
            "role": gemini_role,
            "name": name,
            "content": content,
            "session_id": session_id
        }).execute()
        return res.data[0]["id"] if res.data else None
    except Exception as e:
        st.error(f"メッセージの保存に失敗しました: {e}")
        return None

def load_chat_from_supabase(session_id: str):
    """選択されたチャット部屋の過去ログを古い順にロードする"""
    try:
        response = supabase_client.table("chat_messages") \
            .select("*") \
            .eq("session_id", session_id) \
            .order("created_at", desc=False) \
            .execute()
        return response.data
    except Exception as e:
        st.error(f"メッセージ履歴の読み込みに失敗しました: {e}")
        return []

def delete_messages_from_id(session_id: str, start_message_id: int):
    """指定されたメッセージID以降のすべての会話履歴をDBから削除する"""
    try:
        supabase_client.table("chat_messages") \
            .delete() \
            .eq("session_id", session_id) \
            .gte("id", start_message_id) \
            .execute()
        return True
    except Exception as e:
        st.error(f"履歴の削除に失敗しました: {e}")
        return False

def delete_last_exchange_from_supabase(session_id: str):
    """最新の2件のメッセージをデータベースから削除する（1往復Undo用）"""
    try:
        res = supabase_client.table("chat_messages") \
            .select("id") \
            .eq("session_id", session_id) \
            .order("created_at", desc=True) \
            .limit(2) \
            .execute()
        ids_to_delete = [item["id"] for item in res.data]
        if ids_to_delete:
            supabase_client.table("chat_messages") \
                .delete() \
                .in_("id", ids_to_delete) \
                .execute()
            return True
    except Exception as e:
        st.error(f"履歴の削除に失敗しました: {e}")
    return False

def delete_session_from_supabase(session_id: str):
    """スレッド（セッション）と、それに紐づくすべてのメッセージを削除する"""
    try:
        # 1. 先に紐づくメッセージをすべて削除
        supabase_client.table("chat_messages") \
            .delete() \
            .eq("session_id", session_id) \
            .execute()
            
        # 2. スレッド本体を削除
        supabase_client.table("chat_sessions") \
            .delete() \
            .eq("id", session_id) \
            .execute()
        return True
    except Exception as e:
        st.error(f"スレッドの削除に失敗しました: {e}")
        return False

# =================================================================
# 🌟 時間帯に応じた背景画像の選定関数（ランダムから進化！）
# =================================================================
def get_time_based_bg_image(ai_name: str) -> str:
    """現在の時間帯に応じた画像を返す。画像がない場合はフォールバックする"""
    jst = datetime.timezone(datetime.timedelta(hours=9))
    hour = datetime.datetime.now(jst).hour

    # 時間帯のキーワードを決定
    if 5 <= hour < 9:
        time_key = "morning"    # 朝
    elif 9 <= hour < 17:
        time_key = "daytime"    # 昼
    elif 17 <= hour < 20:
        time_key = "evening"    # 夕方
    elif 20 <= hour < 24:
        time_key = "night"      # 夜
    else:
        time_key = "midnight"   # 深夜

    try:
        all_files = os.listdir('.')
        
        # 1. ぴったりの時間帯画像（例: akane_bg_night.png）があればそれを最優先
        target_name = f"{ai_name}_bg_{time_key}.png"
        if target_name in all_files:
            return target_name
            
        # 2. 時間帯画像がない場合、時間指定のない画像からランダム選出（デフォルトの服など）
        bg_candidates = [
            f for f in all_files 
            if f.startswith(f"{ai_name}_bg") and f.endswith(".png")
        ]
        if bg_candidates:
            # 「morning」などの時間指定キーワードが含まれていない汎用画像だけを絞り込む
            generic_candidates = [
                f for f in bg_candidates 
                if not any(k in f for k in ["morning", "daytime", "evening", "night", "midnight"])
            ]
            if generic_candidates:
                return random.choice(generic_candidates)
            return random.choice(bg_candidates)
            
    except Exception:
        pass
    
    # 3. 何もなければデフォルトの基本画像を返す
    return f"{ai_name}_bg.png"

# 🛠️ 画像変換の処理
def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

# =================================================================
# 🌟 パスワード認証機能
# =================================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 プライベートチャット")
    st.write("このアプリを利用するには合言葉が必要です。")
    password_input = st.text_input("合言葉（パスワード）を入力してください", type="password")
    
    if st.button("ログイン"):
        if password_input == st.secrets["APP_PASSWORD"]:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("❌ 合言葉が違います")
    
    st.stop()

# =================================================================
# 🌟 環境情報の計算関数
# =================================================================
@st.cache_data(ttl=3600)
def get_world_context_data():
    jst = datetime.timezone(datetime.timedelta(hours=9))
    now = datetime.datetime.now(jst)
    
    now_time_str = now.strftime("%Y年%m月%d日 %H時現在")
    weekdays_ja = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
    weekday_str = weekdays_ja[now.weekday()]

    hour = now.hour
    if 5 <= hour < 9:
        time_context = "朝（これから一日が始まる時間）"
    elif 9 <= hour < 12:
        time_context = "午前中"
    elif 12 <= hour < 13:
        time_context = "お昼時（ランチタイム）"
    elif 13 <= hour < 17:
        time_context = "午後・夕方前"
    elif 17 <= hour < 20:
        time_context = "夜・夕食時"
    elif 20 <= hour < 23:
        time_context = "夜・リラックスタイム"
    else:
        time_context = "深夜・夜更け（夜更かし中・そろそろ寝る時間）"

    current_location = "兵庫県神戸市"
    current_weather, current_temp = "不明", "不明"
    try:
        lat, lon = 34.69, 135.19
        weather_res = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&timezone=Asia%2FTokyo", timeout=3).json()
        if 'current_weather' in weather_res:
            w_data = weather_res['current_weather']
            current_temp = f"{w_data['temperature']}℃"
            code = w_data['weathercode']
            if code == 0: current_weather = "快晴"
            elif code in [1, 2, 3]: current_weather = "晴れ/曇り"
            elif code in [45, 48]: current_weather = "霧"
            elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]: current_weather = "雨"
            elif code in [71, 73, 75]: current_weather = "雪"
            elif code in [95, 96, 99]: current_weather = "雷雨"
    except Exception:
        pass

    month, day = now.month, now.day
    if month == 1: event_context = "お正月・新年あけましておめでとう"
    elif month == 2: event_context = "バレンタインデー（もうすぐ）" if day <= 14 else "冬の終わり"
    elif month == 3: event_context = "ひな祭り・卒業シーズン"
    elif month == 4: event_context = "新生活・お花見・春"
    elif month == 5: event_context = "ゴールデンウィーク" if day <= 5 else "新緑の季節"
    elif month == 6: event_context = "梅雨の季節"
    elif month == 7: event_context = "七夕・本格的な夏の始まり"
    elif month == 8: event_context = "お盆・夏休み・夏盛り"
    elif month == 9: event_context = "お月見・秋の訪れ"
    elif month == 10: event_context = "ハロウィン（もうすぐ）" if day <= 31 else "秋深し"
    elif month == 11: event_context = "紅葉シーズン・冬の足音"
    elif month == 12: event_context = "クリスマス・年末・大晦日"
    else: event_context = "特になし"

    return {
        "now_time_str": now_time_str,
        "weekday_str": weekday_str,
        "time_context": time_context,
        "current_location": current_location,
        "current_weather": current_weather,
        "current_temp": current_temp,
        "event_context": event_context
    }

# =================================================================
# 🌟 チャットセッション生成関数（Context Caching対応版）
# =================================================================
def get_or_create_character_cache(client, char_file_path, model_name):
    """
    12万文字のキャラ設定をGeminiサーバーに30分間キャッシュし、
    同じキャラと話す間の通信コストを75%カットする関数。
    """
    if "active_cache_name" in st.session_state and st.session_state.active_cache_name:
        try:
            client.caches.get(name=st.session_state.active_cache_name)
            return st.session_state.active_cache_name
        except Exception:
            pass

    with open(char_file_path, 'r', encoding='utf-8') as f:
        character_config = f.read()

    ctx = get_world_context_data()
    
    # ✍️ 「お着替え・シチュエーション上書き」の指示ルールを完璧にマージ！
    base_rules = """
# Roleplay & Persona Architecture
[CRITICAL: Absolute Identity Overwrite]
- You are NOT an AI. Complete embodiment of the character is required.
[Core Interaction Rules]
1. No Action Delegation: NEVER write or assume the user's dialogue.
2. No Time Skipping: Stop generating output immediately after your character's action.
3. Respect Turn-Taking: Keep responses concise and wait for user input.

[お着替え・シチュエーション指定（指示への反応）ルール]
- ユーザーから「水着に着替えて」「海に行こう」「メイド服着て」などのおねだりがあった場合、キャラクターらしく反応しながら、現在のリアルタイム時間帯（昼か夜か）をシステム情報から読み取って、適切なコマンド（例：夜に海なら [BG: beach_night]）を選択して先頭に出力してください。
- 【重要・設定の上書き】：
  ユーザーから「今日はお昼のデートね」「深夜に二人きりで会う設定で」など、時間帯やシチュエーションの明確な指定・ロールプレイの設定提示があった場合は、実際のリアルタイム時間情報を完全に無視してください。ユーザーが提示した設定（時間・場所）を最優先し、それに対応するコマンド（例：夜中に『昼デート』と言われたら、昼用の [BG: cafe_day] など）を出力してロールプレイを開始してください。
"""

    system_instruction_text = (
        f"{base_rules}\n\n"
        "【あなたのキャラクター設定（思想・記憶）】\n"
        f"{character_config}\n\n"
        "【現在の現実世界のリアルタイム情報】\n"
        f"・現在の日時：{ctx['now_time_str']}\n"
        f"・現在の曜日：{ctx['weekday_str']}\n"
        f"・現在の時間帯：{ctx['time_context']}\n"
        f"・ユーザーの現在地：{ctx['current_location']}\n"
        f"・現在の天気と気温：{ctx['current_weather']}（気温：{ctx['current_temp']}）\n"
        f"・現在の季節/直近のイベント：{ctx['event_context']}\n"
    )

    try:
        cache = client.caches.create(
            model=model_name,
            config=types.CreateCachedContentConfig(
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=system_instruction_text)]
                    )
                ],
                ttl="1800s"  # 30分保持
            )
        )
        st.session_state.active_cache_name = cache.name
        return cache.name
    except Exception as e:
        st.warning(f"キャッシュの作成に失敗しました（通常料金で動作します）: {e}")
        return None

def create_chat_session_from_client(client, char_file_path, model_name="gemini-3.5-flash", past_messages_db=[]):
    cache_name = get_or_create_character_cache(client, char_file_path, model_name)

    if cache_name:
        config = types.GenerateContentConfig(
            cached_content=cache_name,
            max_output_tokens=8000,
            safety_settings=[
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
            ],
            temperature=0.95
        )
    else:
        # キャッシュが失敗した時のフォールバック側にも、同じルールを適用
        with open(char_file_path, 'r', encoding='utf-8') as f:
            character_config = f.read()
        ctx = get_world_context_data()
        system_instruction_text = f"【キャラクター設定】\n{character_config}"
        config = types.GenerateContentConfig(
            system_instruction=system_instruction_text,
            max_output_tokens=8000,
            safety_settings=[
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
            ],
            temperature=0.95
        )

    gemini_history = []
    for msg in past_messages_db:
        gemini_history.append(
            types.Content(
                role=msg["role"],
                parts=[types.Part.from_text(text=msg["content"])]
            )
        )

    return client.chats.create(model=model_name, config=config, history=gemini_history)

# =================================================================
# 🌟 メイン処理の準備
# =================================================================
if "gemini_client" not in st.session_state:
    st.session_state.gemini_client = genai.Client()

# サイドバー：キャラクター選択
txt_files = [f for f in os.listdir('.') if f.endswith('.txt') and f.startswith('char_')]
if not txt_files:
    st.error("キャラクター設定ファイルが見つかりません。")
    st.stop()

# 👑 キャラクターリストをソートし、自動で「02 あかね」を初期選択にするロジックを統合！
txt_files.sort()
default_index = 0
for idx, f in enumerate(txt_files):
    if "02" in f and ("akane" in f or "あかね" in f):
        default_index = idx
        break

selected_file = st.sidebar.selectbox("誰と話す？", txt_files, index=default_index)

my_name = "玄馬"
temp_name = selected_file.replace("char_", "").replace(".txt", "")
ai_name = temp_name.split("_", 1)[1] if "_" in temp_name else temp_name

# 🤖 AIモデルの選択（ProとFlashの切り替え）
selected_model = st.sidebar.selectbox(
    "🤖 AIモデルの選択",
    ["gemini-3.5-flash", "gemini-3.1-flash-lite"],
    index=0,
    help="Flash：高速でサクサク会話が進みます。Pro：複雑な感情表現や深い会話が得意です。"
)

# 🔄 モデルが変更されたらチャットセッションを再初期化
if "current_model" not in st.session_state or st.session_state.current_model != selected_model:
    st.session_state.current_model = selected_model
    st.session_state.chat_session = None
    st.session_state.active_cache_name = None

ai_icon_path = f"{ai_name}_icon.png"
ai_icon = ai_icon_path if os.path.exists(ai_icon_path) else "🌸"

# キャラクターが変更された場合
if "current_char" not in st.session_state or st.session_state.current_char != selected_file:
    st.session_state.current_char = selected_file
    
    # 🖼️ 背景画像を時間帯ベースで自動設定
    st.session_state.current_bg = get_time_based_bg_image(ai_name)
    
    # このキャラのセッション一覧をロード
    sessions = load_sessions_from_supabase(ai_name)
    if not sessions:
        new_sess = create_new_session(ai_name, "新しいチャット")
        st.session_state.current_session_id = new_sess["id"]
    else:
        st.session_state.current_session_id = sessions[0]["id"]
        
    st.session_state.messages = []
    st.session_state.chat_session = None
    st.rerun()

# =================================================================
# 🌟 サイドバー：チャット部屋（スレッド）管理
# =================================================================
st.sidebar.markdown("---")
st.sidebar.subheader("💬 チャット履歴")

if st.sidebar.button("➕ 新規チャットを開始", use_container_width=True):
    # スレッド作成時にも背景を時間帯に合わせて自動再取得
    st.session_state.current_bg = get_time_based_bg_image(ai_name)
    new_sess = create_new_session(ai_name, "新しいチャット")
    if new_sess:
        st.session_state.current_session_id = new_sess["id"]
        st.session_state.messages = []
        st.session_state.chat_session = None
        st.rerun()

sessions = load_sessions_from_supabase(ai_name)
session_options = {}
if sessions:
    session_options = {sess["id"]: sess["title"] for sess in sessions}
    
    active_id = st.session_state.get("current_session_id")
    if active_id not in session_options:
        active_id = list(session_options.keys())[0]
        st.session_state.current_session_id = active_id
        
    selected_session_id = st.sidebar.selectbox(
        "会話スレッドの選択",
        options=list(session_options.keys()),
        format_func=lambda x: session_options[x],
        index=list(session_options.keys()).index(active_id)
    )

    # 🗑️ スレッドを削除するボタン
    if st.sidebar.button("🗑️ このスレッドを削除する", use_container_width=True):
        if delete_session_from_supabase(selected_session_id):
            st.toast("スレッドを削除しました！", icon="🗑️")
            st.session_state.messages = []
            st.session_state.chat_session = None
            if "current_session_id" in st.session_state:
                del st.session_state.current_session_id
            st.rerun()
    
    if selected_session_id != active_id:
        # スレッド切り替え時にも背景を時間帯に合わせて自動再取得
        st.session_state.current_bg = get_time_based_bg_image(ai_name)
        st.session_state.current_session_id = selected_session_id
        st.session_state.messages = []
        st.session_state.chat_session = None
        st.rerun()

# 📥 このスレッドをダウンロードする機能
if st.session_state.get("messages"):
    log_text = ""
    for msg in st.session_state.messages:
        role_name = my_name if msg["role"] == "user" else ai_name
        log_text += f"{role_name}: {msg['content']}\n\n"
    
    st.sidebar.download_button(
        label="📥 このスレッドをダウンロード",
        data=log_text,
        file_name=f"chat_{ai_name}_{st.session_state.current_session_id[:8]}.txt",
        mime="text/plain",
        use_container_width=True
    )

# =================================================================
# 🌟 Gemini チャットセッションの復元と読み込み
# =================================================================
if "chat_session" not in st.session_state or st.session_state.chat_session is None:
    past_db_messages = load_chat_from_supabase(st.session_state.current_session_id)
    
    st.session_state.messages = []
    for msg in past_db_messages:
        display_role = "user" if msg["role"] == "user" else "ai"
        st.session_state.messages.append({
            "id": msg["id"],
            "role": display_role,
            "content": msg["content"]
        })
        
    st.session_state.chat_session = create_chat_session_from_client(
        st.session_state.gemini_client, 
        selected_file, 
        model_name=selected_model,
        past_messages_db=past_db_messages
    )

# =================================================================
# 🌟 【Web版風】メッセージのダイアログ編集機能
# =================================================================
@st.dialog("メッセージを編集してやり直す ✏️")
def edit_message_dialog(original_text: str, msg_id: int, index: int):
    st.write("この発言より後の会話履歴はすべて削除され、新しい内容で再送信されます。")
    new_text = st.text_area("編集するメッセージ内容", value=original_text, height=150)
    
    if st.button("書き換えて再送信", use_container_width=True):
        if delete_messages_from_id(st.session_state.current_session_id, msg_id):
            st.session_state.messages = st.session_state.messages[:index]
            st.session_state.chat_session = None # セッションを一度リセットして再構築
            st.session_state.temp_user_input = new_text
            st.rerun()

# =================================================================
# 🌟 UI構築
# =================================================================
bg_image_path = st.session_state.get("current_bg", f"{ai_name}_bg.png")

if os.path.exists(bg_image_path):
    bin_str = get_base64_of_bin_file(bg_image_path)
    page_bg_img = f'''
    <style>
    .stApp {{
        background-image: url("data:image/png;base64,{bin_str}");
        background-size: contain;      
        background-position: center 50px; 
        background-repeat: no-repeat;  
        background-attachment: fixed;
        background-color: #E6F2FF;     
    }}
    .stChatMessage {{
        background-color: rgba(255, 255, 255, 0.85) !important;
        border-radius: 15px;
        padding: 10px;
        margin-bottom: 10px;
    }}
    h1 {{
        color: white;
        text-shadow: 2px 2px 4px #000000;
    }}
    .edit-btn {{
        font-size: 0.8rem;
        color: #555555;
        text-decoration: none;
        cursor: pointer;
    }}
    </style>
    '''
    st.markdown(page_bg_img, unsafe_allow_html=True)

# --- チャット表示 ---
for idx, msg in enumerate(st.session_state.messages):
    if msg["role"] == "user":
        with st.chat_message("user", avatar="👤"):
            st.write(msg["content"])
            if st.button("✏️ この発言を編集してやり直す", key=f"edit_{idx}", help="ここから会話を修正できます"):
                edit_message_dialog(msg["content"], msg["id"], idx)
    else:
        with st.chat_message("ai", avatar=ai_icon):
            st.write(msg["content"])

# --- チャット入力処理 ---
user_input = None
if user_input := st.chat_input(f"{ai_name}にメッセージを送信..."):
    pass
elif "temp_user_input" in st.session_state and st.session_state.temp_user_input:
    user_input = st.session_state.temp_user_input
    del st.session_state.temp_user_input

# メッセージ送信実行
if user_input:
    current_title = session_options.get(st.session_state.current_session_id, "")
    if current_title == "新しいチャット":
        new_title = user_input[:12] + "..." if len(user_input) > 12 else user_input
        update_session_title(st.session_state.current_session_id, new_title)

    user_msg_id = save_chat_to_supabase("user", my_name, user_input, st.session_state.current_session_id)
    st.session_state.messages.append({"id": user_msg_id, "role": "user", "content": user_input})
    st.rerun()

# AIの返答処理
if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    last_user_content = st.session_state.messages[-1]["content"]
    
    with st.chat_message("ai", avatar=ai_icon):
        message_placeholder = st.empty()
        full_response = ""
        try:
            response_stream = st.session_state.chat_session.send_message_stream(last_user_content)
            for chunk in response_stream:
                if chunk.text:
                    full_response += chunk.text
                    message_placeholder.markdown(full_response + "▌")
            
            # --- 🖼️ 会話内背景コマンド `[BG: xxx]` のパース＆画面クリーンアップ処理を追加！ ---
            bg_command = None
            clean_response = full_response
            
            # 返答の先頭に [BG: xxx] があるか正規表現でチェック
            match = re.match(r"^\[BG:\s*([a-zA-Z0-9_-]+)\]\s*\n?", full_response)
            if match:
                bg_command = match.group(1).lower()  # 例: "beach_day" などを小文字で取得
                # ユーザーの画面や履歴からはコマンド文字列を除去
                clean_response = full_response[match.end():].strip()
            
            # きれいになった最終返答を描画
            message_placeholder.markdown(clean_response)
            
            # もし背景コマンドが指定され、該当する png ファイルが存在すれば背景画像を更新
            if bg_command:
                target_bg = f"{ai_name}_bg_{bg_command}.png"
                if os.path.exists(target_bg):
                    st.session_state.current_bg = target_bg
            # -------------------------------------------------------------------------
            
            # データベースには [BG: xxx] を削った純粋なメッセージのみを保存
            ai_msg_id = save_chat_to_supabase("ai", ai_name, clean_response, st.session_state.current_session_id)
            st.session_state.messages.append({"id": ai_msg_id, "role": "ai", "content": clean_response})
            st.rerun()
                
        except Exception as e:
            st.error(f"通信エラーが発生しました: {e}")

# =================================================================
# 🌟 直前の会話を1つ取り消す（Undo）ボタン
# =================================================================
if len(st.session_state.messages) >= 2:
    st.markdown("---")
    if st.button("↩️ 直前の会話（自分とAIの1往復）を取り消してやり直す", use_container_width=True):
        if delete_last_exchange_from_supabase(st.session_state.current_session_id):
            st.session_state.messages = st.session_state.messages[:-2]
            st.session_state.chat_session = None # セッション再初期化
            st.success("直前の会話を取り消しました！")
            st.rerun()