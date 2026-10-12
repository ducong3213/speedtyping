"""Speed Typing Game - Flask web app + analytics dashboard.

Phan chia nhiem vu cac thanh vien:
- Thanh vien 1: Giao dien nguoi dung (UI/UX), bo dem thoi gian, xu ly nhap lieu tieng Viet (IME) va tuong tac go phim (index.html).
- Thanh vien 2: Backend Flask Server, thiet ke co so du lieu SQLite, thuat toan luyen tap thich ung Adaptive Learning (Rolling Window).
- Thanh vien 3: Telemetry ghi nhan nhip go phim (delay_ms, CSV log), Dashboard thong ke (Chart.js) va Keyboard Heatmap (dashboard.html).
"""

# ==================================================================
# 1. IMPORTS
# ==================================================================
import csv
import os
import random
import secrets
import sqlite3
import time
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, render_template, request, jsonify

# ==================================================================
# 2. CONFIG
# ==================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "typing.db")
WORDS_PATH = os.path.join(BASE_DIR, "vietnamese_words.txt")
CSV_PATH = os.path.join(BASE_DIR, "keystrokes_log.csv")

UTC_TZ = ZoneInfo("UTC")
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

KB_LAYOUT = ["qwertyuiop", "asdfghjkl", "zxcvbnm", " "]

TOKENS = {}           # token -> câu đã phát cho lượt chơi đó (một lần)
LAST_SUBMIT = {}      # chặn spam theo IP

MIN_AVG_DELAY_MS = 60   # trung bình < 60ms/phím => siêu nhân (~200 WPM+)
MAX_WPM = 250
WORD_COUNT = 100        # Số từ phát cho chế độ tính giờ (đủ cho 30s / 60s)

app = Flask(__name__)


# ==================================================================
# 3. DATABASE HELPERS
# ==================================================================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS sessions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        wpm REAL, accuracy REAL, total_chars INTEGER, errors INTEGER,
        mode TEXT DEFAULT 'normal',
        adaptive_session_id TEXT DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS keystrokes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER, expected TEXT, typed TEXT,
        correct INTEGER, delay_ms INTEGER)""")
    # Migration an toàn cho các DB đã tồn tại từ trước
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN mode TEXT DEFAULT 'normal'")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN adaptive_session_id TEXT DEFAULT NULL")
    except Exception:
        pass
    conn.commit()
    conn.close()


# ==================================================================
# 4. UTILITY HELPERS
# ==================================================================
def load_words():
    """Đọc danh sách từ vựng tiếng Việt từ vietnamese_words.txt."""
    if os.path.exists(WORDS_PATH):
        with open(WORDS_PATH, encoding="utf-8") as f:
            return [w.strip() for w in f.read().split() if w.strip()]
    return ["người", "được", "những", "trong", "thành", "không", "nhiều", "chúng", "thông", "phát"]


def generate_sentence(count=WORD_COUNT):
    """Sinh một đoạn văn ngẫu nhiên từ kho từ vựng thông dụng."""
    words = load_words()
    return " ".join(random.choices(words, k=count))


def to_vn(iso_str):
    """Đổi timestamp UTC (từ SQLite) sang giờ Việt Nam để hiển thị."""
    try:
        dt = datetime.fromisoformat(iso_str).replace(tzinfo=UTC_TZ)
        return dt.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return iso_str


def normalize_key(ch):
    """Ánh xạ ký tự tiếng Việt có dấu về phím QWERTY gốc phục vụ heatmap."""
    if not ch:
        return ""
    ch = ch.lower()
    if ch in ("đ",):
        return "d"
    nfkd = unicodedata.normalize("NFKD", ch)
    base = "".join([c for c in nfkd if not unicodedata.combining(c)])
    return base if base in "abcdefghijklmnopqrstuvwxyz " else ch


def build_heatmap(rows):
    """Gom thống kê phím thành dict phục vụ bản đồ nhiệt (hỗ trợ tiếng Việt)."""
    heat_stats = {}
    for r in rows:
        ch = normalize_key(r["expected"])
        if not ch:
            continue
        if ch not in heat_stats:
            heat_stats[ch] = {"errs": 0, "delays": []}
        errs = r["errs"] or 0
        heat_stats[ch]["errs"] += errs
        if r["avg_delay"]:
            heat_stats[ch]["delays"].append(r["avg_delay"])

    heat = {}
    for ch, stat in heat_stats.items():
        errs = stat["errs"]
        avg_delay = round(sum(stat["delays"]) / len(stat["delays"])) if stat["delays"] else None
        cls = "k-bad" if errs > 3 else "k-mid" if errs > 0 else "k-ok"
        heat[ch] = {"cls": cls, "errs": errs, "delay": avg_delay}
    return heat


def log_csv(session_id, sentence, keystrokes):
    """Telemetry: nối từng nhịp gõ vào keystrokes_log.csv (đúng đề bài)."""
    new_file = not os.path.exists(CSV_PATH)
    ts = datetime.now(VN_TZ).isoformat(timespec="milliseconds")
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["timestamp", "session_id", "expected",
                        "typed", "correct", "delay_ms"])
        for i, k in enumerate(keystrokes):
            w.writerow([ts, session_id, sentence[i], k.get("typed", ""),
                        1 if k.get("typed", "") == sentence[i] else 0,
                        int(k.get("delay_ms", 0))])


def pick_adaptive_sentence(count=WORD_COUNT, adaptive_session_id=None):
    """Adaptive Mode: chỉ dùng lỗi từ tối đa 3 ván gần nhất trong CÙNG 1 session adaptive."""
    if not adaptive_session_id:
        return generate_sentence(count)

    conn = get_db()
    last_sessions = conn.execute("""
        SELECT id FROM sessions 
        WHERE mode = 'adaptive' AND adaptive_session_id = ?
        ORDER BY id DESC LIMIT 3
    """, (adaptive_session_id,)).fetchall()
    
    if not last_sessions:
        conn.close()
        # Ván đầu tiên trong session adaptive này: chưa có dữ liệu lỗi -> phát câu bình thường
        return generate_sentence(count)

    session_ids = [s["id"] for s in last_sessions]
    placeholders = ",".join(["?"] * len(session_ids))
    rows = conn.execute(f"""
        SELECT expected, SUM(correct = 0) AS errs
        FROM keystrokes
        WHERE session_id IN ({placeholders})
        GROUP BY expected
    """, session_ids).fetchall()
    conn.close()

    errs = {r["expected"]: (r["errs"] or 0) for r in rows}
    words = load_words()
    if not words or not any(errs.values()):
        return generate_sentence(count)

    scored = sorted(words,
                    key=lambda w: sum(errs.get(ch, 0) for ch in w),
                    reverse=True)
    top_candidates = scored[:60]
    adaptive_words = random.choices(top_candidates, k=int(count * 0.7)) + random.choices(words, k=count - int(count * 0.7))
    random.shuffle(adaptive_words)
    return " ".join(adaptive_words)


def issue_sentence(mode="normal", adaptive_session_id=None):
    """Phát cặp (token một lần, câu gõ) theo chế độ được chọn."""
    token = secrets.token_hex(8)
    sentence = (pick_adaptive_sentence(adaptive_session_id=adaptive_session_id) if mode == "adaptive"
                else generate_sentence())
    TOKENS[token] = {
        "sentence": sentence,
        "mode": mode,
        "adaptive_session_id": adaptive_session_id
    }
    return token, sentence


# ==================================================================
# 5. ROUTES
# ==================================================================
@app.route("/")
def index():
    mode = request.args.get("mode", "normal")
    adaptive_session_id = request.args.get("adaptive_session_id")
    if mode not in ("normal", "adaptive"):
        mode = "normal"
    token, sentence = issue_sentence(mode, adaptive_session_id)
    return render_template("index.html",
                           sentence=sentence,
                           token=token,
                           initial_mode=mode,
                           adaptive_session_id=adaptive_session_id)


@app.route("/api/sentence")
def next_sentence():
    """Cấp câu + token mới cho ván kế tiếp (không cần tải lại trang)."""
    mode = request.args.get("mode", "normal")
    adaptive_session_id = request.args.get("adaptive_session_id")
    if mode not in ("normal", "adaptive"):
        mode = "normal"
    token, sentence = issue_sentence(mode, adaptive_session_id)
    return jsonify(sentence=sentence, token=token, mode=mode, adaptive_session_id=adaptive_session_id)


@app.route("/api/submit", methods=["POST"])
def submit():
    # Lớp 1: rate limit — mỗi IP tối đa 1 submit / 5 giây
    ip = request.remote_addr or "unknown"
    now = time.time()
    if now - LAST_SUBMIT.get(ip, 0) < 5:
        return jsonify(status="too fast"), 429
    LAST_SUBMIT[ip] = now

    data = request.get_json(silent=True) or {}

    # Lớp 2: token một lần + lấy đúng câu gốc đã phát cho token đó
    token = data.get("token", "")
    token_meta = TOKENS.pop(token, None)
    if token_meta is None:
        return jsonify(status="invalid token"), 403

    if isinstance(token_meta, dict):
        sentence = token_meta["sentence"]
        mode = token_meta.get("mode", "normal")
        adaptive_session_id = token_meta.get("adaptive_session_id")
    else:
        sentence = token_meta
        mode = "normal"
        adaptive_session_id = None

    # Lớp 3: server TỰ đối chiếu từng phím với câu gốc, không tin client
    keystrokes = data.get("keystrokes", [])
    if not keystrokes or len(keystrokes) > len(sentence):
        return jsonify(status="invalid"), 400

    delays = []
    correct = 0
    for i, k in enumerate(keystrokes):
        if k.get("expected") != sentence[i]:
            return jsonify(status="invalid"), 400      # sai thứ tự = không phải câu của tôi
        if k.get("typed", "") == sentence[i]:          # server tự phán đúng/sai
            correct += 1
        d = k.get("delay_ms", 0)
        if not isinstance(d, (int, float)) or d < 0 or d > 10000:
            return jsonify(status="invalid"), 400
        delays.append(d)

    elapsed = sum(delays) / 1000.0
    if elapsed <= 0:
        return jsonify(status="invalid"), 400

    # Tính WPM và Accuracy theo TỪ (Word-based):
    # Chỉ tính WPM cho các từ gõ đúng 100%, Accuracy = (từ đúng / tổng số từ) * 100
    typed_chars = "".join([k.get("typed", "") for k in keystrokes])
    expected_sub = sentence[:len(keystrokes)]

    exp_words = expected_sub.strip().split()
    typed_words = typed_chars.strip().split()

    total_words = max(len(exp_words), len(typed_words))
    correct_words = 0
    correct_chars_count = 0

    for i in range(min(len(exp_words), len(typed_words))):
        if exp_words[i] == typed_words[i]:
            correct_words += 1
            correct_chars_count += len(exp_words[i]) + 1

    wpm = round((correct_chars_count / 5.0) / (elapsed / 60.0), 1)
    accuracy = round((correct_words / total_words) * 100, 1) if total_words > 0 else 100.0
    total = len(keystrokes)
    errors = total_words - correct_words

    # Lớp 4: heuristic "có phải người thật không?"
    if wpm > MAX_WPM:
        return jsonify(status="invalid"), 400
    if sum(delays) / total < MIN_AVG_DELAY_MS:
        return jsonify(status="superhuman"), 400       # phản xạ nhanh hơn người thật
    if len(set(delays)) <= 2:
        return jsonify(status="robotic"), 400          # delay đều tăm tắp = máy gõ

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO sessions(wpm, accuracy, total_chars, errors, mode, adaptive_session_id) VALUES (?,?,?,?,?,?)",
        (wpm, accuracy, total, errors, mode, adaptive_session_id))
    sid = cur.lastrowid
    for i, k in enumerate(keystrokes):
        conn.execute(
            "INSERT INTO keystrokes(session_id, expected, typed, correct, delay_ms) VALUES (?,?,?,?,?)",
            (sid, sentence[i], k.get("typed", ""),
             1 if k.get("typed", "") == sentence[i] else 0, int(delays[i])))
    conn.commit()
    conn.close()

    # Telemetry song song: ghi file CSV phục vụ phân tích offline
    try:
        log_csv(sid, sentence, keystrokes)
    except OSError:
        pass    # file log hỏng cũng không được làm hỏng lượt chơi

    return jsonify(status="ok", session_id=sid)


@app.route("/dashboard")
def dashboard():
    mode = request.args.get("mode", "normal")
    adaptive_session_id = request.args.get("adaptive_session_id")
    if mode not in ("normal", "adaptive"):
        mode = "normal"

    conn = get_db()
    sessions = conn.execute(
        "SELECT * FROM sessions ORDER BY id DESC LIMIT 20").fetchall()
    rows = conn.execute("""SELECT expected, SUM(correct = 0) AS errs,
            COUNT(*) AS hits, ROUND(AVG(delay_ms)) AS avg_delay
        FROM keystrokes GROUP BY expected""").fetchall()
    conn.close()

    # Lịch sử lượt chơi kèm thời gian hiển thị giờ Việt Nam
    session_list = []
    for s in sessions:
        d = dict(s)
        d["created_at_vn"] = to_vn(s["created_at"])
        session_list.append(d)

    heat = build_heatmap(rows)
    wpm_history = [s["wpm"] for s in reversed(sessions)]
    acc_history = [s["accuracy"] for s in reversed(sessions)]

    return render_template("dashboard.html",
                           sessions=session_list,
                           layout=KB_LAYOUT,
                           heat=heat,
                           wpm_history=wpm_history,
                           acc_history=acc_history,
                           current_mode=mode,
                           adaptive_session_id=adaptive_session_id)


# ==================================================================
# 6. ENTRY POINT
# ==================================================================
init_db()

if __name__ == "__main__":
    app.run(debug=True)