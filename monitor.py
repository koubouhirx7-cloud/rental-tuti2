import urllib.request
import json
import os
import time
from datetime import datetime, timedelta

# 設定
# GitHub Secrets から読み込む
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

BIKE_IDS = [
    3592, 3593, 3595, 3596, 3597, 3598, 3600, 3602, 3603, 3604, 
    3605, 3606, 3607, 3608, 3657, 3665, 3666, 3667, 3668, 3669, 3670
]
STATE_FILE = "last_records.json"

def log_setup_info():
    if WEBHOOK_URL:
        masked_url = WEBHOOK_URL[:30] + "..." if len(WEBHOOK_URL) > 30 else "Too Short"
        print(f"INFO: Webhook URL configured. Starts with: {masked_url}")
    else:
        print("ERROR: DISCORD_WEBHOOK_URL environment variable is not set.")


def fetch_history(bike_id):
    url = f"https://api.rideblink.net/api/v1/bike/history/{bike_id}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                return json.loads(response.read().decode())
        except Exception as e:
            print(f"Error fetching bike {bike_id} (Attempt {attempt+1}/3): {e}")
            time.sleep(1)
    return []

def format_datetime(iso_str):
    if not iso_str or iso_str == "-":
        return "-"
    try:
        # ISO 8601 形式の文字列を読み込み
        dt = datetime.strptime(iso_str.replace('Z', ''), '%Y-%m-%dT%H:%M:%S.%f')
        # 日本時間 (UTC+9) に変換
        jst_dt = dt + timedelta(hours=9)
        # 表示用にフォーマット
        return jst_dt.strftime('%Y/%m/%d %H:%M')
    except:
        return iso_str

def send_discord_notification(record):
    bike_id = record.get('bike_id')
    name = record.get('name', '不明')
    start = format_datetime(record.get('scheduled_start'))
    end_val = record.get('end_date')
    end = format_datetime(end_val)
    port = record.get('port') or '不明'
    
    # 状態の判定 (レンタル中か返却済みか)
    is_return = end_val and end_val != "-"
    status_title = "✅ **自転車が返却されました**" if is_return else "🚲 **レンタルが開始されました**"
    color = 0x2ecc71 if is_return else 0x3498db # 緑 (返却) または 青 (開始)
    
    # 自転車の特徴
    features = []
    if "トレイラー" in name: features.append("🚛 トレイラー付")
    if "子供" in name or "チャイルド" in name: features.append("👶 子供椅子付")
    if "電動" in name: features.append("⚡ 電動アシスト")
    feature_text = " (" + ", ".join(features) + ")" if features else ""
    
    # Google Maps リンク
    map_link = ""
    location = record.get('end_location')
    if location and 'x' in location and 'y' in location:
        lat, lon = location['y'], location['x']
        map_link = f"\n📍 **返却場所地図:** [Google Mapsで表示](https://www.google.com/maps/search/?api=1&query={lat},{lon})"

    content = (
        f"{status_title}\n"
        f"--------------------------------\n"
        f"**自転車:** {name}{feature_text}\n"
        f"**ポート:** {port}\n"
        f"**開始:** {start}\n"
        f"**返却:** {end}{map_link}\n"
        f"--------------------------------"
    )
    
    data = json.dumps({"content": content}).encode('utf-8')
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    req = urllib.request.Request(WEBHOOK_URL, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            print(f"Notification sent for bike {bike_id}")
    except Exception as e:
        print(f"Failed to send notification: {e}")

def main():
    log_setup_info()
    
    CHECK_INTERVAL = 60  # seconds

    # 前回の状態を読み込み
    last_ids = set()
    if os.path.exists(STATE_FILE):
        print(f"INFO: State file {STATE_FILE} found.")
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                last_ids = set(json.load(f))
            print(f"INFO: Loaded {len(last_ids)} IDs from state file.")
        except Exception as e:
            print(f"ERROR: Failed to load state file: {e}")
            pass
    else:
        print(f"INFO: State file {STATE_FILE} NOT found. Starting fresh (first run will not send notifications).")

    print(f"INFO: Starting single check...")

    # while True loop removed for GitHub Actions cron execution
    timestamp = datetime.now().strftime('%Y/%m/%d %H:%M:%S')
    print(f"\n[{timestamp}] Checking for updates...")
    
    try:
        current_ids = set()
        new_records = []
        fetch_errors = 0

        for bike_id in BIKE_IDS:
            history = fetch_history(bike_id)
            if not history and history != []: # Fetch failed
                fetch_errors += 1
                # print(f"Skipping update for bike {bike_id} due to fetch error.")
                continue

            for record in history:
                # ユニークなキーを作成（bike_id + start_date + end_date）
                record_key = f"{record.get('bike_id')}_{record.get('scheduled_start')}_{record.get('end_date')}"
                current_ids.add(record_key)
                
                if record_key not in last_ids:
                    if last_ids:  # 初回実行時は通知しない
                        new_records.append(record)
                    else:
                        # 初回ロード時はログだけ出す
                        pass

        # 重要な修正: 全ての取得に失敗した場合や、取得結果が0件だった場合に
        # 状態ファイルを空で上書きしないようにする
        if not current_ids and fetch_errors > 0:
            print("Warning: All fetches failed or returned no IDs. Not updating state file to prevent data loss.")
        else:
            # 新しい順に通知
            if new_records:
                print(f"Found {len(new_records)} new updates.")
                for record in new_records:
                    send_discord_notification(record)
                    time.sleep(1) # Discord のレート制限対策
            else:
                print("No new updates found.")

            # 状態を保存（前回のIDも保持しつつ、最新の状況を反映）
            updated_ids = last_ids.union(current_ids)
            
            # Update memory cache
            last_ids = updated_ids
            
            # Save to disk
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(list(updated_ids), f, ensure_ascii=False)
    
    except Exception as e:
        print(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()

