import streamlit as st
import os
import datetime
import requests
import base64
from google import genai
from google.genai import types

# 🌟 ページの設定（スマホでも見やすいようにcenteredに戻します）
st.set_page_config(
    page_title="AI Roleplay App",
    page_icon="💬",
    layout="centered",
    initial_sidebar_state="expanded"
)

# =================================================================
# 🌟 パスワード認証機能（ここを追加しました！）
# =================================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

# 認証されていない場合は、パスワード入力画面だけを表示して処理を止める
if not st.session_state.authenticated:
    st.title("🔒 プライベートチャット")
    st.write("このアプリを利用するには合言葉が必要です。")
    password_input = st.text_input("合言葉（パスワード）を入力してください", type="password")
    
    if st.button("ログイン"):
        # StreamlitのSecretsに保存したパスワードと一致するか確認
        if password_input == st.secrets["APP_PASSWORD"]:
            st.session_state.authenticated = True
            st.rerun() # 画面をリロードしてチャット画面へ
        else:
            st.error("❌ 合言葉が違います")
    
    st.stop() # 認証されるまではここでプログラムをストップし、下のチャット画面は出さない

# =================================================================
# 🌟 関数の定義
# =================================================================
@st.cache_data(ttl=3600)
def get_world_context():
    now = datetime.datetime.now()
    now_time_str = now.strftime("%Y年%m月%d日 %H時%M分")
    weekdays_ja = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
    weekday_str = weekdays_ja[now.weekday()]

    hour = now.hour
    if 5 <= hour < 9: time_context = "朝"
    elif 9 <= hour < 12: time_context = "午前中"
    elif 12 <= hour < 13: time_context = "お昼時"
    elif 13 <= hour < 17: time_context = "午後"
    elif 17 <= hour < 20: time_context = "夜"
    elif 20 <= hour < 23: time_context = "夜"
    else: time_context = "深夜"

    current_location, current_weather, current_temp = "日本", "不明", "不明"
    try:
        geo_res = requests.get('http://ip-api.com/json/?lang=ja', timeout=3).json()
        if geo_res.get('status') == 'success':
            current_location = f"{geo_res.get('regionName')}{geo_res.get('city')}"
            lat, lon = geo_res.get('lat'), geo_res.get('lon')
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
    if month == 1: event_context = "お正月"
    elif month == 2: event_context = "バレンタイン（もうすぐ）" if day <= 14 else "冬の終わり"
    elif month == 3: event_context = "卒業シーズン"
    elif month == 4: event_context = "新生活・春"
    elif month == 5: event_context = "ゴールデンウィーク" if day <= 5 else "新緑"
    elif month == 6: event_context = "梅雨"
    elif month == 7: event_context = "本格的な夏"
    elif month == 8: event_context = "お盆・夏真っ盛り"
    elif month == 9: event_context = "秋の訪れ"
    elif month == 10: event_context = "ハロウィン" if day <= 31 else "秋深し"
    elif month == 11: event_context = "冬の足音"
    elif month == 12: event_context = "クリスマス・年末"
    else: event_context = "特になし"

    return f"・日時：{now_time_str} ({weekday_str}) {time_context}\n・現在地：{current_location}\n・天気：{current_weather} ({current_temp})\n・季節：{event_context}"

def create_chat_session_from_client(client, char_file_path):
    with open(char_file_path, 'r', encoding='utf-8') as f:
        character_config = f.read()

    world_context = get_world_context()
    
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
  3. ABSOLUTELY NO OMISSIONS. Maintain 100% of the information, heat, and emotional intensity until the very end of your physical token limit.
"""
    system_instruction_text = f"{base_rules}\n\n【現在の現実世界のリアルタイム情報】\n{world_context}\n\n【あなたのキャラクター設定】\n{character_config}"

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
    return client.chats.create(model="gemini-3.5-flash", config=config)

# 背景画像を読み込むための関数
def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

def save_chat_to_log(role, name, content):
    """チャットの内容を日付ごとのテキストファイルに保存する関数"""
    # 現在の日付でファイル名を作成 (例: chatlog_20260716.txt)
    today_str = datetime.datetime.now().strftime("%Y%m%d")
    filename = f"chatlog_{today_str}.txt"
    
    # 現在の時刻を取得 (例: 12:30:45)
    now_time = datetime.datetime.now().strftime("%H:%M:%S")
    
    # 追記モード('a')でファイルを開き、書き込む
    with open(filename, 'a', encoding='utf-8') as f:
        f.write(f"[{now_time}] {name}: {content}\n")
        # AIの発言の後に空行を入れて区切りをわかりやすくする
        if role == "ai":
            f.write("-" * 40 + "\n")

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

# 表示名の設定
my_name = "Genma"
temp_name = selected_file.replace("char_", "").replace(".txt", "")
ai_name = temp_name.split("_", 1)[1] if "_" in temp_name else temp_name

# アイコン・背景のパスを生成
bg_image_path = f"{ai_name}_bg.png"
ai_icon_path = f"{ai_name}_icon.png"
ai_icon = ai_icon_path if os.path.exists(ai_icon_path) else "🌸"

# キャラクターが変更されたら、接続を作る
if "current_char" not in st.session_state or st.session_state.current_char != selected_file:
    st.session_state.current_char = selected_file
    st.session_state.messages = []
    st.session_state.chat_session = create_chat_session_from_client(st.session_state.gemini_client, selected_file)
    st.rerun()

# =================================================================
# 🌟 チャット履歴ダウンロードボタン（サイドバーに追加）
# =================================================================
today_str = datetime.datetime.now().strftime("%Y%m%d")
log_filename = f"chatlog_{today_str}.txt"

# ログファイルがサーバー内に存在している場合だけボタンを表示
if os.path.exists(log_filename):
    with open(log_filename, "r", encoding="utf-8") as f:
        log_content = f.read()
    
    st.sidebar.download_button(
        label="📥 今日のチャット履歴をダウンロード",
        data=log_content,
        file_name=log_filename,
        mime="text/plain"
    )

# =================================================================
# 🌟 UI構築（背景画像の上にチャットを重ねるスタイル）
# =================================================================
# 🌟 背景画像を画面全体に適用（スマホでの見栄えを重視）
if os.path.exists(bg_image_path):
    bin_str = get_base64_of_bin_file(bg_image_path)
    page_bg_img = f'''
    <style>
    .stApp {{
        background-image: url("data:image/png;base64,{bin_str}");
        background-size: contain;      /* 💡変更：画面内に画像全体を収める */
        background-position: center 50px; 
        background-repeat: no-repeat;  /* 💡追加：画像が繰り返されるのを防ぐ */
        background-attachment: fixed;
        background-color: #E6F2FF;     /* 💡追加：余白ができた場合の背景色（お好みで） */
    }}
    /* 吹き出しを少し白く透けさせて読みやすくする */
    .stChatMessage {{
        background-color: rgba(255, 255, 255, 0.85) !important;
        border-radius: 15px;
        padding: 10px;
        margin-bottom: 10px;
    }}
    /* タイトルなどの文字も読みやすく調整 */
    h1 {{
        color: white;
        text-shadow: 2px 2px 4px #000000;
    }}
    </style>
    '''
    st.markdown(page_bg_img, unsafe_allow_html=True)


# --- チャット画面の表示 ---
for msg in st.session_state.messages:
    if msg["role"] == "user":
        with st.chat_message("user", avatar="👤"):
            st.write(msg["content"])
    else:
        with st.chat_message("ai", avatar=ai_icon):
            st.write(msg["content"])

# --- ユーザー入力欄 ---
if user_input := st.chat_input(f"{ai_name}にメッセージを送信..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user", avatar="👤"):
        st.write(user_input)
        
    # 💡 追加：ユーザーの発言をテキストファイルに保存
    save_chat_to_log("user", "あなた", user_input)

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
            
            # 💡 追加：AIの発言がすべて完了した後にテキストファイルに保存
            save_chat_to_log("ai", ai_name, full_response)
            
        except Exception as e:
            st.error(f"通信エラーが発生しました: {e}")