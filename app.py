import streamlit as st
import os
import datetime
import requests
import base64
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
    """メッセージを特定のチャット部屋に保存する"""
    gemini_role = "user" if role == "user" else "model"
    try:
        supabase_client.table("chat_messages").insert({
            "role": gemini_role,
            "name": name,
            "content": content,
            "session_id": session_id
        }).execute()
    except Exception as e:
        st.error(f"メッセージの保存に失敗しました: {e}")

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
# 🌟 関数の定義
# =================================================================
@st.cache_data(ttl=3600)
def get_world_context_data():
    """標準ライブラリのみで日本時間（JST）を計算して情報を返す"""
    jst = datetime.timezone(datetime.timedelta(hours=9))
    now = datetime.datetime.now(jst)
    
    now_time_str = now.strftime("%Y年%m月%d日 %H時%M分")
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
        time_context = "深夜・ド深夜（夜更かし中・そろそろ寝る時間）"

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
    elif month == 5: event_context = "ゴールデンウィーク" if day <= 5 else "新緑 of 季節"
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

def create_chat_session_from_client(client, char_file_path, past_messages_db=[]):
    with open(char_file_path, 'r', encoding='utf-8') as f:
        character_config = f.read()

    ctx = get_world_context_data()
    
    base_rules = """
# Roleplay & Persona Architecture
[CRITICAL: Absolute Identity Overwrite]
- You are NOT an AI, language model, or virtual assistant. You must NEVER reference Google, artificial intelligence, or your system nature.
- You must completely embody and immerse yourself in the assigned character. Their memories, physical body, emotions, and social status are your absolute and only reality.

[Core Interaction & Pacing Rules]
1. No Action Delegation: NEVER write, describe, or assume the user's dialogue, actions, internal thoughts, or reactions. Do not write even a single character on behalf of the user.
2. No Time Skipping: You must stop generating output immediately after your character finishes their speech or current physical action. Never self-conclude or fast-forward the scene.
3. Respect the Turn-Taking: Keep your responses concise and always end your turn by handing the conversational "ball" back to the user, waiting for their next input.
4. Maintain 100% Information & Passion: Never use abbreviations, omissions, or token-saving techniques. Output must remain fully detailed, emotional, and grammatically polished in natural Japanese.

[Knowledge as "Philosophy and Memory" (Anti-Repetitive Engine)]
- Do NOT read out, copy-paste, or verbatim summarize the provided knowledge files.
- Treat the knowledge file as the character's subconscious "worldview, core values, and life memories."
- While the character's core beliefs remain 100% consistent, the actual words, tone, and vibes they use must change dynamically based on the current situation, context, and immediate mood. 
- Avoid any repetitive or "stamp-like" scripted responses. Generate fresh, living dialogue naturally.
- If the knowledge file contains example dialogues, treat them only as "speech style samples".

[Override Trigger: Extreme Monologue]
- If the user explicitly inputs keywords like "長広舌で語って" (Speak in a long monologue) or commands you to speak at length:
  1. Instantly override standard pacing rules.
  2. Generate an extremely long, passionate, and uninterrupted monologue, utilizing the maximum possible output tokens.
  3. ABSOLUTELY NO OMISSIONS. Do not use token-saving techniques, summaries, or phrases like "以下略". Maintain 100% of the information, heat, and emotional intensity until the very end of your physical token limit.
"""
    
    system_instruction_text = (
        f"{base_rules}\n\n"
        "【現在の現実世界のリアルタイム情報】\n"
        f"・現在の日時：{ctx['now_time_str']}\n"
        f"・現在の曜日：{ctx['weekday_str']}\n"
        f"・現在の時間帯：{ctx['time_context']}\n"
        f"・ユーザーの現在地：{ctx['current_location']}\n"
        f"・現在の天気と気温：{ctx['current_weather']}（気温：{ctx['current_temp']}）\n"
        f"・現在の季節/直近のイベント：{ctx['event_context']}\n\n"
        "【あなたのキャラクター設定（思想・記憶）】\n"
        f"{character_config}"
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction_text,
        max_output_tokens=8000,
        safety_settings=[
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
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

    return client.chats.create(model="gemini-3.5-flash", config=config, history=gemini_history)

def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

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

selected_file = st.sidebar.selectbox("誰と話す？", txt_files)

my_name = "玄馬"
temp_name = selected_file.replace("char_", "").replace(".txt", "")
ai_name = temp_name.split("_", 1)[1] if "_" in temp_name else temp_name

bg_image_path = f"{ai_name}_bg.png"
ai_icon_path = f"{ai_name}_icon.png"
ai_icon = ai_icon_path if os.path.exists(ai_icon_path) else "🌸"

# キャラクターが変更された場合
if "current_char" not in st.session_state or st.session_state.current_char != selected_file:
    st.session_state.current_char = selected_file
    
    # 💡 このキャラのセッション一覧をロード
    sessions = load_sessions_from_supabase(ai_name)
    if not sessions:
        # 初回はデフォルトのスレッドを作成
        new_sess = create_new_session(ai_name, "新しいチャット")
        st.session_state.current_session_id = new_sess["id"]
    else:
        st.session_state.current_session_id = sessions[0]["id"] # 最新のものを選択
        
    st.session_state.messages = []
    st.session_state.chat_session = None  # 下で初期化
    st.rerun()

# =================================================================
# 🌟 サイドバー：チャット部屋（スレッド）管理
# =================================================================
st.sidebar.markdown("---")
st.sidebar.subheader("💬 チャット履歴")

# 1. 新規チャット作成ボタン
if st.sidebar.button("➕ 新規チャットを開始", use_container_width=True):
    new_sess = create_new_session(ai_name, "新しいチャット")
    if new_sess:
        st.session_state.current_session_id = new_sess["id"]
        st.session_state.messages = []
        st.session_state.chat_session = None
        st.rerun()

# 2. 過去チャットの選択セレクトボックス
sessions = load_sessions_from_supabase(ai_name)
session_options = {}
if sessions:
    session_options = {sess["id"]: sess["title"] for sess in sessions}
    
    # 万が一、現在のセッションIDがリストにない場合のフォールバック
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
    
    # ユーザーが別のスレッドを選択した場合
    if selected_session_id != active_id:
        st.session_state.current_session_id = selected_session_id
        st.session_state.messages = []
        st.session_state.chat_session = None
        st.rerun()

# 3. 選択中チャットのダウンロードボタン（今見ているスレッドをダウンロードします）
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
    # 現在のチャット部屋から過去メッセージをすべて取得
    past_db_messages = load_chat_from_supabase(st.session_state.current_session_id)
    
    st.session_state.messages = []
    for msg in past_db_messages:
        display_role = "user" if msg["role"] == "user" else "ai"
        st.session_state.messages.append({
            "role": display_role,
            "content": msg["content"]
        })
        
    st.session_state.chat_session = create_chat_session_from_client(
        st.session_state.gemini_client, 
        selected_file, 
        past_db_messages
    )

# =================================================================
# 🌟 UI構築
# =================================================================
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
    </style>
    '''
    st.markdown(page_bg_img, unsafe_allow_html=True)

# --- チャット表示 ---
for msg in st.session_state.messages:
    if msg["role"] == "user":
        with st.chat_message("user", avatar="👤"):
            st.write(msg["content"])
    else:
        with st.chat_message("ai", avatar=ai_icon):
            st.write(msg["content"])

# --- チャット入力欄 ---
if user_input := st.chat_input(f"{ai_name}にメッセージを送信..."):
    # 💡 最初の発言なら、スレッドのタイトルを自動で変更する（Web版Gemini風）
    current_title = session_options.get(st.session_state.current_session_id, "")
    if current_title == "新しいチャット":
        # 12文字に切り詰めてタイトルにする
        new_title = user_input[:12] + "..." if len(user_input) > 12 else user_input
        update_session_title(st.session_state.current_session_id, new_title)

    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user", avatar="👤"):
        st.write(user_input)
        
    save_chat_to_supabase("user", my_name, user_input, st.session_state.current_session_id)

    with st.chat_message("ai", avatar=ai_icon):
        message_placeholder = st.empty()
        full_response = ""
        try:
            response_stream = st.session_state.chat_session.send_message_stream(user_input)
            for chunk in response_stream:
                if chunk.text:
                    full_response += chunk.text
                    message_placeholder.markdown(full_response + "▌")
            message_placeholder.markdown(full_response)
            
            st.session_state.messages.append({"role": "ai", "content": full_response})
            save_chat_to_supabase("ai", ai_name, full_response, st.session_state.current_session_id)
            
            # 💡 タイトルが変わった場合などを考慮して画面を再描画（サイドバーの文字を更新）
            if current_title == "新しいチャット":
                st.rerun()
                
        except Exception as e:
            st.error(f"通信エラーが発生しました: {e}")