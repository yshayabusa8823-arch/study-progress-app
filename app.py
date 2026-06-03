import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
import time
import json
import random



st.set_page_config(
    page_title="Study Progress",
    page_icon="❄",
    layout="centered"
)

SHEET_NAME = "StudyProgressDB"

WEEKDAY_MAP = {
    0: "月",
    1: "火",
    2: "水",
    3: "木",
    4: "金",
    5: "土",
    6: "日",
}

WEEKDAYS = ["月", "火", "水","木", "金", "土", "日"]

MOTIVATION_MESSAGES = [

    ("🌸 今日も少しずつ積み上げよう",
     "完璧じゃなくてOK。1問進めば、ちゃんと前に進んでる。"),

    ("❄ 焦らなくて大丈夫",
     "積み重ねは、見えないところでもちゃんと育ってる。"),

    ("🌙 今日の1問が未来を変える",
     "小さい前進でも、続けば大きな力になる。"),

    ("✨ 今やるその1問が強い",
     "モチベが低い日でも、進んだ事実は残る。"),

    ("📚 ゆっくりでも進んでる",
     "昨日より少し前に進めば、それで十分。"),

    ("💎 今日の努力は消えない",
     "理解に時間がかかっても、ちゃんと積み上がってる。"),

    ("🫧 まずは1問だけ",
     "始めると意外と進められる日もある。"),

    ("🌠 苦手発見は前進",
     "できなかった問題は、伸びしろを見つけた証拠。"),

    ("☕ 無理しすぎなくてOK",
     "継続できるペースが、一番強い。"),

    ("🩵 今日ここを開いた時点で偉い",
     "勉強しようと思った、その気持ちがもう前進。"),

    ("📖 積み重ねは裏切らない",
     "数日後、数週間後にちゃんと差になる。"),

    ("🌌 少しずつで大丈夫",
     "焦るより、止まらないことの方が大事。"),
]
# =====================
# Google Sheets 接続
# =====================

def get_or_create_worksheet(spreadsheet, title, headers):
    try:
        ws = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(
            title=title,
            rows=1000,
            cols=max(len(headers), 10)
        )
        ws.append_row(headers)

    values = ws.get_all_values()
    if not values:
        ws.append_row(headers)

    return ws


@st.cache_resource
def connect_sheets():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scope
    )

    client = gspread.authorize(creds)
    spreadsheet = client.open(SHEET_NAME)

    undo_headers = [
        "action_id",
        "created_at",
        "log_id",
        "question_id",
        "task_date",
        "task_type",
        "prev_question_json",
        "prev_task_status",
        "undone"
    ]

    return {
        "materials": spreadsheet.worksheet("materials"),
        "questions": spreadsheet.worksheet("questions"),
        "logs": spreadsheet.worksheet("logs"),
        "daily_tasks": spreadsheet.worksheet("daily_tasks"),
        "undo_actions": get_or_create_worksheet(
            spreadsheet,
            "undo_actions",
            undo_headers
        ),
    }


# =====================
# 共通関数
# =====================

@st.cache_data(ttl=30, show_spinner=False)
def load_sheet(_ws, cache_key):
    """
    Google Sheets の読み込みを30秒キャッシュする。
    _ws は先頭がアンダースコアなので Streamlit のハッシュ対象外。
    cache_key でシートごとにキャッシュを分ける。
    """
    records = _ws.get_all_records()
    return pd.DataFrame(records)

def load_sheet_live(ws):
    records = ws.get_all_records()
    return pd.DataFrame(records)


def load_all_data_live(sheets):
    return {
        "materials_df": load_sheet_live(sheets["materials"]),
        "questions_df": load_sheet_live(sheets["questions"]),
        "logs_df": load_sheet_live(sheets["logs"]),
        "tasks_df": load_sheet_live(sheets["daily_tasks"]),
        "undo_df": load_sheet_live(sheets["undo_actions"]),
    }


def ensure_date_fresh():
    today_key = str(today_jst())

    if "app_today_key" not in st.session_state:
        st.session_state["app_today_key"] = today_key
        return

    if st.session_state["app_today_key"] != today_key:
        st.session_state["app_today_key"] = today_key
        st.cache_data.clear()
        st.rerun()

def refresh_data_and_rerun():
    """
    書き込み後だけキャッシュを消して再読み込みする。
    通常の画面再描画では30秒キャッシュを使うので、API読み込みを抑えられる。
    """
    st.cache_data.clear()
    st.rerun()


def safe_str(value):
    if pd.isna(value):
        return ""
    return str(value)

def today_jst():
    return datetime.now(ZoneInfo("Asia/Tokyo")).date()

def safe_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default

def days_until_exam(month, day):
    today = today_jst()
    exam_date = date(today.year, month, day)

    if exam_date < today:
        exam_date = date(today.year + 1, month, day)

    return exam_date, (exam_date - today).days


def next_id(df, id_col):
    if df.empty or id_col not in df.columns:
        return 1
    ids = pd.to_numeric(df[id_col], errors="coerce").fillna(0)
    return int(ids.max()) + 1


def col_letter(n):
    result = ""
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def get_material_name(materials_df, material_id):
    if materials_df.empty:
        return ""

    target = materials_df[
        materials_df["material_id"].astype(str) == str(material_id)
    ]

    if target.empty:
        return ""

    row = target.iloc[0]
    return f'{row["subject"]}｜{row["material_name"]}'

def subject_style(subject):
    styles = {

        "憲法": {
            "border": "#ef4444",
            "bg": "linear-gradient(135deg, #fff1f2, #ffffff)",
            "badge_bg": "#fee2e2",
            "badge_text": "#991b1b",
        },

        "民法": {
            "border": "#3b82f6",
            "bg": "linear-gradient(135deg, #eff6ff, #ffffff)",
            "badge_bg": "#dbeafe",
            "badge_text": "#1e3a8a",
        },

        "刑法": {
            "border": "#22c55e",
            "bg": "linear-gradient(135deg, #f0fdf4, #ffffff)",
            "badge_bg": "#dcfce7",
            "badge_text": "#14532d",
        },

        "行政法": {
            "border": "#f59e0b",
            "bg": "linear-gradient(135deg, #fffbeb, #ffffff)",
            "badge_bg": "#fef3c7",
            "badge_text": "#92400e",
        },

        "商法": {
            "border": "#8b5cf6",
            "bg": "linear-gradient(135deg, #f5f3ff, #ffffff)",
            "badge_bg": "#ede9fe",
            "badge_text": "#5b21b6",
        },

        "民事訴訟法": {
            "border": "#06b6d4",
            "bg": "linear-gradient(135deg, #ecfeff, #ffffff)",
            "badge_bg": "#cffafe",
            "badge_text": "#155e75",
        },

        "刑事訴訟法": {
            "border": "#ec4899",
            "bg": "linear-gradient(135deg, #fdf2f8, #ffffff)",
            "badge_bg": "#fbcfe8",
            "badge_text": "#9d174d",
        },

        "知的財産法": {
            "border": "#14b8a6",
            "bg": "linear-gradient(135deg, #f0fdfa, #ffffff)",
            "badge_bg": "#ccfbf1",
            "badge_text": "#115e59",
        },

        "会社法": {
            "border": "#6366f1",
            "bg": "linear-gradient(135deg, #eef2ff, #ffffff)",
            "badge_bg": "#c7d2fe",
            "badge_text": "#3730a3",
        },

        "労働法": {
            "border": "#f97316",
            "bg": "linear-gradient(135deg, #fff7ed, #ffffff)",
            "badge_bg": "#fed7aa",
            "badge_text": "#9a3412",
        },
    }

    return styles.get(subject, {
        "border": "#cbd5e1",
        "bg": "linear-gradient(135deg, #f8fafc, #ffffff)",
        "badge_bg": "#f1f5f9",
        "badge_text": "#334155",
    })

def subject_color(subject):
    colors = {
        "憲法": "#fee2e2",
        "民法": "#dbeafe",
        "刑法": "#dcfce7",
        "行政法": "#fef3c7",
        "商法": "#f3e8ff",
        "民事訴訟法": "#e0f2fe",
        "刑事訴訟法": "#fae8ff",
    }
    return colors.get(str(subject), "#f1f5f9")


def subject_badge(subject):
    color = subject_color(subject)
    return f"""
    <span style="
        display:inline-block;
        padding:0.25rem 0.7rem;
        border-radius:999px;
        background:{color};
        font-weight:800;
        margin-right:0.35rem;
        color:#334155;
    ">
        {subject}
    </span>
    """

def latest_comment_for_question(logs_df, question_id):
    if logs_df.empty or "question_id" not in logs_df.columns:
        return ""

    q_logs = logs_df[
        logs_df["question_id"].astype(str) == str(question_id)
    ].copy()

    if q_logs.empty:
        return ""

    q_logs = q_logs.tail(1)
    comment = safe_str(q_logs.iloc[0].get("comment", ""))

    return comment

def update_question_row(ws, questions_df, question_id, new_values):
    target = questions_df[
        questions_df["question_id"].astype(str) == str(question_id)
    ]

    if target.empty:
        return False

    sheet_row = target.index[0] + 2
    headers = list(questions_df.columns)
    row_values = ws.row_values(sheet_row)

    while len(row_values) < len(headers):
        row_values.append("")

    for col_name, value in new_values.items():
        if col_name in headers:
            row_values[headers.index(col_name)] = value

    end_col = col_letter(len(headers))
    ws.update(f"A{sheet_row}:{end_col}{sheet_row}", [row_values])
    return True


def update_material_row(ws, materials_df, material_id, new_values):
    target = materials_df[
        materials_df["material_id"].astype(str) == str(material_id)
    ]

    if target.empty:
        return False

    sheet_row = target.index[0] + 2
    headers = list(materials_df.columns)
    row_values = ws.row_values(sheet_row)

    while len(row_values) < len(headers):
        row_values.append("")

    for col_name, value in new_values.items():
        if col_name in headers:
            row_values[headers.index(col_name)] = value

    end_col = col_letter(len(headers))
    ws.update(f"A{sheet_row}:{end_col}{sheet_row}", [row_values])
    return True


def update_task_status(ws, tasks_df, task_date, question_id, task_type, new_status):
    """
    タスク状態だけを更新する。
    以前は row_values() で1回読んでから update() していたが、
    statusセルだけを update_cell() することで Read API を使わない。
    """
    if tasks_df.empty or "status" not in tasks_df.columns:
        return False

    target = tasks_df[
        (tasks_df["task_date"].astype(str) == str(task_date)) &
        (tasks_df["question_id"].astype(str) == str(question_id)) &
        (tasks_df["task_type"].astype(str) == str(task_type))
    ]

    if target.empty:
        return False

    sheet_row = target.index[0] + 2
    status_col = list(tasks_df.columns).index("status") + 1
    ws.update_cell(sheet_row, status_col, new_status)
    return True

def update_task_row(ws, tasks_df, task_date, question_id, task_type, new_values):
    if tasks_df.empty:
        return False

    target = tasks_df[
        (tasks_df["task_date"].astype(str) == str(task_date)) &
        (tasks_df["question_id"].astype(str) == str(question_id)) &
        (tasks_df["task_type"].astype(str) == str(task_type))
    ]

    if target.empty:
        return False

    sheet_row = target.index[0] + 2
    headers = list(tasks_df.columns)
    row_values = ws.row_values(sheet_row)

    while len(row_values) < len(headers):
        row_values.append("")

    for col_name, value in new_values.items():
        if col_name in headers:
            row_values[headers.index(col_name)] = value

    end_col = col_letter(len(headers))
    ws.update(f"A{sheet_row}:{end_col}{sheet_row}", [row_values])
    return True


def delete_task(ws, tasks_df, task_date, question_id, task_type):
    if tasks_df.empty:
        return False

    target = tasks_df[
        (tasks_df["task_date"].astype(str) == str(task_date)) &
        (tasks_df["question_id"].astype(str) == str(question_id)) &
        (tasks_df["task_type"].astype(str) == str(task_type))
    ]

    if target.empty:
        return False

    sheet_row = target.index[0] + 2
    ws.delete_rows(sheet_row)
    return True


def find_task_status(tasks_df, task_date, question_id, task_type):
    if tasks_df.empty:
        return ""

    target = tasks_df[
        (tasks_df["task_date"].astype(str) == str(task_date)) &
        (tasks_df["question_id"].astype(str) == str(question_id)) &
        (tasks_df["task_type"].astype(str) == str(task_type))
    ]

    if target.empty:
        return ""

    row = target.iloc[0]
    return safe_str(row.get("status", ""))


def save_undo_action(
    sheets,
    undo_df,
    log_id,
    selected_q,
    tasks_df,
    question_id,
    task_type
):
    today_str = str(today_jst())
    action_id = next_id(undo_df, "action_id")

    prev_question = {
        "status": safe_str(selected_q.get("status", "")),
        "last_done_date": safe_str(selected_q.get("last_done_date", "")),
        "next_review_date": safe_str(selected_q.get("next_review_date", "")),
        "difficulty": safe_str(selected_q.get("difficulty", "")),
        "round": safe_str(selected_q.get("round", "")),
    }

    prev_task_status = find_task_status(
        tasks_df,
        today_str,
        question_id,
        task_type
    )

    sheets["undo_actions"].append_row([
        int(action_id),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        int(log_id),
        int(question_id),
        today_str,
        task_type,
        json.dumps(prev_question, ensure_ascii=False),
        prev_task_status,
        ""
    ])


def delete_log_by_id(ws, logs_df, log_id):
    if logs_df.empty:
        return False

    target = logs_df[
        logs_df["log_id"].astype(str) == str(log_id)
    ]

    if target.empty:
        return False

    sheet_row = target.index[0] + 2
    ws.delete_rows(sheet_row)
    return True


def delete_logs_by_question_id(ws, logs_df, question_id):
    """
    指定した問題の学習ログを全部削除する。
    行番号がずれないように下の行から削除する。
    """
    if logs_df.empty:
        return 0

    target = logs_df[
        logs_df["question_id"].astype(str) == str(question_id)
    ]

    if target.empty:
        return 0

    sheet_rows = [idx + 2 for idx in target.index]

    for sheet_row in sorted(sheet_rows, reverse=True):
        ws.delete_rows(sheet_row)

    return len(sheet_rows)


def reset_tasks_for_question(ws, tasks_df, question_id):
    """
    指定した問題に紐づくタスクを未完了に戻す。
    タスク自体は消さない。
    複数行をまとめて batch_update するので API 消費を抑える。
    """
    if tasks_df.empty or "status" not in tasks_df.columns:
        return 0

    target = tasks_df[
        tasks_df["question_id"].astype(str) == str(question_id)
    ]

    if target.empty:
        return 0

    headers = list(tasks_df.columns)
    status_col_letter = col_letter(headers.index("status") + 1)

    updates = []
    for idx, _ in target.iterrows():
        sheet_row = idx + 2
        updates.append({
            "range": f"{status_col_letter}{sheet_row}",
            "values": [["未完了"]]
        })

    if updates:
        ws.batch_update(updates)

    return len(updates)

def reset_question_before_learning(sheets, questions_df, logs_df, tasks_df, question_id):
    """
    間違えて実施済みにした問題を、実施前の状態に戻す。
    - 問題状態を未着手にする
    - last_done_date を空にする
    - next_review_date を空にする
    - 学習ログを削除する
    - 紐づくタスクは未完了に戻す
    """
    update_question_row(
        sheets["questions"],
        questions_df,
        question_id,
        {
            "status": "未着手",
            "last_done_date": "",
            "next_review_date": "",
            "difficulty": 3,
            "round": 1
        }
    )

    deleted_logs = delete_logs_by_question_id(
        sheets["logs"],
        logs_df,
        question_id
    )

    reset_tasks = reset_tasks_for_question(
        sheets["daily_tasks"],
        tasks_df,
        question_id
    )

    return deleted_logs, reset_tasks


def mark_undo_done(ws, undo_df, action_id):
    target = undo_df[
        undo_df["action_id"].astype(str) == str(action_id)
    ]

    if target.empty:
        return False

    sheet_row = target.index[0] + 2
    headers = list(undo_df.columns)

    if "undone" not in headers:
        return False

    col = headers.index("undone") + 1
    ws.update_cell(sheet_row, col, "済")
    return True


def count_study_days_until(target_date, study_days, start_date=None):
    if start_date is None:
        start_date = today_jst()

    count = 0
    d = start_date

    while d <= target_date:
        if WEEKDAY_MAP[d.weekday()] in study_days:
            count += 1
        d += timedelta(days=1)

    return max(count, 1)


def task_exists(tasks_df, task_date, question_id, task_type=None):
    if tasks_df.empty:
        return False

    matched = tasks_df[
        (tasks_df["task_date"].astype(str) == str(task_date)) &
        (tasks_df["question_id"].astype(str) == str(question_id))
    ]

    if task_type is not None:
        matched = matched[
            matched["task_type"].astype(str) == str(task_type)
        ]

    return not matched.empty

def calc_today_summary(tasks_df):
    today_str = str(today_jst())

    if tasks_df.empty:
        return {
            "total": 0,
            "done": 0,
            "remaining": 0
        }

    today_tasks = tasks_df[
        tasks_df["task_date"].astype(str) == today_str
    ].copy()

    if today_tasks.empty:
        return {
            "total": 0,
            "done": 0,
            "remaining": 0
        }

    total = len(today_tasks)

    if "status" in today_tasks.columns:
        done = len(today_tasks[
            today_tasks["status"].astype(str) == "完了"
        ])
    else:
        done = 0

    remaining = total - done

    return {
        "total": total,
        "done": done,
        "remaining": remaining
    }

def calc_ai_ready_summary(logs_df):

    today_str = str(today_jst())

    if logs_df.empty:
        return "まだ記録がありません。まず1問だけやってみよう。"

    today_logs = logs_df[
        logs_df["date"].astype(str) == today_str
    ]

    if today_logs.empty:
        return "今日はまだ記録がありません。まず1問だけ始めよう。"

    weak_count = len(
        today_logs[
            today_logs["result"].astype(str) == "苦手"
        ]
    )

    vague_count = len(
        today_logs[
            today_logs["result"].astype(str) == "微妙"
        ]
    )

    perfect_count = len(
        today_logs[
            today_logs["result"].astype(str) == "完璧"
        ]
    )

    messages = []

    if perfect_count > 0:
        messages.append(f"✨ 完璧 {perfect_count}問")

    if vague_count > 0:
        messages.append(f"🌱 微妙 {vague_count}問")

    if weak_count > 0:
        messages.append(f"🔥 苦手 {weak_count}問")

    summary = " / ".join(messages)

    if weak_count > 0:
        advice = "苦手復習を優先しよう。"

    elif vague_count > 0:
        advice = "明日の復習で固めよう。"

    else:
        advice = "かなり良いペース！"

    return f"{summary}<br>{advice}"

def calc_pace_summary(materials_df, questions_df):
    if materials_df.empty or questions_df.empty:
        return {
            "status": "データなし",
            "message": "教材を登録すると判定します"
        }

    today = today_jst()
    total_needed_today = 0
    danger_count = 0

    for _, material in materials_df.iterrows():
        material_id = material["material_id"]
        study_days = safe_str(material.get("study_days", "")).split(",")
        study_days = [d for d in study_days if d in WEEKDAYS]

        if not study_days:
            continue

        qs = questions_df[
            questions_df["material_id"].astype(str) == str(material_id)
        ]

        if qs.empty:
            continue

        total = len(qs)
        touched = len(qs[
            qs["status"].astype(str).isin(["復習待ち", "苦手", "完了", "学習中"])
        ])

        remaining = max(total - touched, 0)

        if remaining == 0:
            continue

        target_dt = pd.to_datetime(
            material.get("target_date", ""),
            errors="coerce"
        )

        if pd.isna(target_dt):
            continue

        target_date = target_dt.date()

        study_days_left = count_study_days_until(
            target_date,
            study_days,
            start_date=today
        )

        needed_per_study_day = max(1, -(-remaining // study_days_left))

        if WEEKDAY_MAP[today.weekday()] in study_days:
            total_needed_today += needed_per_study_day

        if study_days_left <= 3 and remaining > needed_per_study_day * study_days_left:
            danger_count += 1

    if total_needed_today == 0:
        return {
            "status": "休息日",
            "message": "今日は進める予定の教材が少なめ"
        }

    if danger_count > 0:
        return {
            "status": "要注意",
            "message": f"今日は目安 {total_needed_today} 問。遅れ気味の教材あり"
        }

    return {
        "status": "順調",
        "message": f"今日は目安 {total_needed_today} 問ペース"
    }

def estimate_finish_plan(total, touched, study_days, target_date_raw):
    remaining = max(total - touched, 0)

    if remaining == 0:
        return {
            "remaining": 0,
            "study_days_left": 0,
            "per_day": 0,
            "finish_date": "一周完了！"
        }

    today = today_jst()

    try:
        target_date = pd.to_datetime(target_date_raw).date()
    except Exception:
        target_date = today

    study_days_left = count_study_days_until(
        target_date,
        study_days,
        start_date=today
    )

    per_day = max(1, -(-remaining // study_days_left))

    d = today
    left = remaining

    while left > 0:
        if WEEKDAY_MAP[d.weekday()] in study_days:
            left -= per_day
        d += timedelta(days=1)

    finish_date = d - timedelta(days=1)

    return {
        "remaining": remaining,
        "study_days_left": study_days_left,
        "per_day": per_day,
        "finish_date": f"{finish_date.month}月{finish_date.day}日"
    }


# =====================
# タスク生成
# =====================

def generate_today_tasks(materials_df, questions_df, tasks_df, sheets):
    today = today_jst()
    today_str = str(today)
    new_rows = []

    if materials_df.empty or questions_df.empty:
        return 0

    for _, material in materials_df.iterrows():
        material_id = material["material_id"]
        study_days = safe_str(material.get("study_days", "")).split(",")

        if WEEKDAY_MAP[today.weekday()] not in study_days:
            continue

        qs = questions_df[
            questions_df["material_id"].astype(str) == str(material_id)
        ].copy()

        if qs.empty:
            continue

        qs["question_number"] = pd.to_numeric(
            qs["question_number"],
            errors="coerce"
        )
        qs = qs.sort_values("question_number")

        review_qs = qs[
            (qs["next_review_date"].astype(str) == today_str) &
            (qs["status"].astype(str) != "苦手")
        ]

        for _, q in review_qs.iterrows():
            if not task_exists(tasks_df, today_str, q["question_id"]):
                new_rows.append([
                    today_str,
                    int(q["question_id"]),
                    "復習",
                    1,
                    "未完了"
                ])

        weak_qs = qs[
            qs["status"].astype(str) == "苦手"
        ]

        for _, q in weak_qs.iterrows():
            if not task_exists(tasks_df, today_str, q["question_id"]):
                new_rows.append([
                    today_str,
                    int(q["question_id"]),
                    "苦手復習",
                    2,
                    "未完了"
                ])

        unstarted_qs = qs[
            qs["status"].astype(str).isin(["未着手", "学習中"])
        ]

        if unstarted_qs.empty:
            continue

        try:
            target = pd.to_datetime(material["target_date"]).date()
        except Exception:
            target = today

        remaining_questions = len(unstarted_qs)
        remaining_days = count_study_days_until(target, study_days, today)
        new_count = max(1, -(-remaining_questions // remaining_days))

        new_qs = unstarted_qs.head(new_count)

        for _, q in new_qs.iterrows():
            if not task_exists(tasks_df, today_str, q["question_id"]):
                new_rows.append([
                    today_str,
                    int(q["question_id"]),
                    "新規",
                    3,
                    "未完了"
                ])

    if new_rows:
        sheets["daily_tasks"].append_rows(new_rows)

    return len(new_rows)


def build_tasks_df_for_date(tasks_df, questions_df, materials_df, target_date, hide_done=False):
    target_str = str(target_date)

    if tasks_df.empty:
        return pd.DataFrame()

    target_tasks = tasks_df[
        tasks_df["task_date"].astype(str) == target_str
    ].copy()

    if hide_done and "status" in target_tasks.columns:
        target_tasks = target_tasks[
            target_tasks["status"].astype(str) != "完了"
        ]

    if target_tasks.empty:
        return pd.DataFrame()

    merged = target_tasks.merge(
        questions_df,
        on="question_id",
        how="left",
        suffixes=("_task", "_question")
    )

    merged["教材"] = merged["material_id"].apply(
        lambda x: get_material_name(materials_df, x)
    )

    merged["question_number"] = pd.to_numeric(
        merged["question_number"],
        errors="coerce"
    )

    merged["priority"] = pd.to_numeric(
        merged["priority"],
        errors="coerce"
    ).fillna(99)

    merged = merged.sort_values(
        ["priority", "教材", "question_number"]
    )

    return merged


def build_today_tasks_df(tasks_df, questions_df, materials_df, hide_done=False):
    return build_tasks_df_for_date(
        tasks_df,
        questions_df,
        materials_df,
        today_jst(),
        hide_done=hide_done
    )


def build_tomorrow_preview_df(materials_df, questions_df):
    tomorrow = today_jst() + timedelta(days=1)
    tomorrow_str = str(tomorrow)
    tomorrow_weekday = WEEKDAY_MAP[tomorrow.weekday()]
    preview_rows = []

    if materials_df.empty or questions_df.empty:
        return pd.DataFrame()

    for _, material in materials_df.iterrows():
        material_id = material["material_id"]
        study_days = safe_str(material.get("study_days", "")).split(",")

        qs = questions_df[
            questions_df["material_id"].astype(str) == str(material_id)
        ].copy()

        if qs.empty:
            continue

        qs["question_number"] = pd.to_numeric(
            qs["question_number"],
            errors="coerce"
        )
        qs = qs.sort_values("question_number")

        review_qs = qs[
            (qs["next_review_date"].astype(str) == tomorrow_str) &
            (qs["status"].astype(str) != "苦手")
        ]

        for _, q in review_qs.iterrows():
            row = q.to_dict()
            row["task_type"] = "復習予定"
            row["教材"] = get_material_name(materials_df, q["material_id"])
            row["priority"] = 1
            preview_rows.append(row)

        weak_qs = qs[
            (qs["status"].astype(str) == "苦手") &
            (qs["next_review_date"].astype(str) == tomorrow_str)
        ]

        for _, q in weak_qs.iterrows():
            row = q.to_dict()
            row["task_type"] = "苦手復習予定"
            row["教材"] = get_material_name(materials_df, q["material_id"])
            row["priority"] = 2
            preview_rows.append(row)

        if tomorrow_weekday in study_days:
            unstarted_qs = qs[
                qs["status"].astype(str).isin(["未着手", "学習中"])
            ]

            if not unstarted_qs.empty:
                target_dt = pd.to_datetime(
                    material.get("target_date", ""),
                    errors="coerce"
                )

                if pd.isna(target_dt):
                    target = tomorrow
                else:
                    target = target_dt.date()

                remaining_questions = len(unstarted_qs)
                remaining_days = count_study_days_until(
                    target,
                    study_days,
                    start_date=tomorrow
                )

                new_count = max(1, -(-remaining_questions // remaining_days))
                new_qs = unstarted_qs.head(new_count)

                for _, q in new_qs.iterrows():
                    row = q.to_dict()
                    row["task_type"] = "新規予定"
                    row["教材"] = get_material_name(materials_df, q["material_id"])
                    row["priority"] = 3
                    preview_rows.append(row)

    if not preview_rows:
        return pd.DataFrame()

    df = pd.DataFrame(preview_rows)
    df["question_number"] = pd.to_numeric(
        df["question_number"],
        errors="coerce"
    )
    df = df.sort_values(["priority", "教材", "question_number"])

    return df


# =====================
# 学習記録保存
# =====================

def save_learning_log(
    sheets,
    logs_df,
    questions_df,
    tasks_df,
    question_id,
    task_type,
    result,
    difficulty,
    study_minutes,
    comment
):
    log_id = next_id(logs_df, "log_id")
    today_str = str(today_jst())

    selected_q = questions_df[
        questions_df["question_id"].astype(str) == str(question_id)
    ]

    if selected_q.empty:
        return

    selected_q = selected_q.iloc[0]

    undo_df = load_sheet(sheets["undo_actions"], "undo_actions")

    save_undo_action(
        sheets=sheets,
        undo_df=undo_df,
        log_id=log_id,
        selected_q=selected_q,
        tasks_df=tasks_df,
        question_id=question_id,
        task_type=task_type
    )

    sheets["logs"].append_row([
        int(log_id),
        today_str,
        int(question_id),
        result,
        int(difficulty),
        int(study_minutes),
        comment
    ])

    current_round = selected_q.get("round", 1)
    current_round = int(current_round) if str(current_round).isdigit() else 1

    if result == "完璧":
        new_status = "完了"
        next_review = ""
        new_round = current_round + 1

    elif result == "微妙":
        new_status = "復習待ち"
        next_review = today_jst() + timedelta(days=1)
        new_round = current_round + 1

    elif result == "苦手":
        new_status = "苦手"
        next_review = today_jst() + timedelta(days=1)
        new_round = current_round + 1

    elif result == "未完了":
        new_status = "未着手"
        next_review = selected_q.get("next_review_date", "")
        new_round = current_round

    else:
        new_status = "未着手"
        next_review = today_jst() + timedelta(days=1)
        new_round = current_round

    update_question_row(
        sheets["questions"],
        questions_df,
        question_id,
        {
            "status": new_status,
            "last_done_date": today_str,
            "next_review_date": str(next_review) if next_review else "",
            "difficulty": int(difficulty),
            "round": new_round
        }
    )

    update_task_status(
        sheets["daily_tasks"],
        tasks_df,
        today_str,
        question_id,
        task_type,
        "完了" if result != "未完了" else "未完了"
    )


def show_result_effect(result):
    if result == "できた":
        st.success("完了！すごい！🎉")
        st.balloons()
    elif result == "微妙":
        st.info("記録OK！明日の復習で固めよう！🌱")
    elif result == "できなかった":
        st.warning("大丈夫、苦手を見つけたのが勝ち！🔥")
    else:
        st.info("未完了として保存したよ。明日に回そう。")

    refresh_data_and_rerun()


# =====================
# データ読み込み
# =====================

sheets = connect_sheets()

ensure_date_fresh()

materials_df = load_sheet(sheets["materials"], "materials")
questions_df = load_sheet(sheets["questions"], "questions")
logs_df = load_sheet(sheets["logs"], "logs")
tasks_df = load_sheet(sheets["daily_tasks"], "daily_tasks")
undo_df = load_sheet(sheets["undo_actions"], "undo_actions")


# =====================
# CSS
# =====================

# =====================
# CSS
# =====================

# =====================
# CSS
# =====================

st.markdown(
    """
    <style>

    .stApp {
        background:
            radial-gradient(circle at top left, rgba(167,139,250,0.24) 0%, transparent 30%),
            radial-gradient(circle at top right, rgba(147,197,253,0.18) 0%, transparent 28%),
            radial-gradient(circle at bottom left, rgba(216,180,254,0.16) 0%, transparent 26%),
            linear-gradient(
                135deg,
                #eeeaff 0%,
                #e9e7ff 26%,
                #e8ecff 52%,
                #f0f4ff 78%,
                #f7f9ff 100%
            );
        background-attachment: fixed;
    }

/* =========================================================
   色調整版
   ・水色かなり薄め
   ・白発光強め
   ・ブルベ夏の透明感重視
========================================================= */

.stApp::before {
    content:
        "✦        ❄          ✧       ✦"
        "      ✧        ❄          ✦"
        "   ✦        ✧       ❄        ✦";

    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 0;
    white-space: pre-wrap;

    color: rgba(255,255,255,0.94);

    font-size: 30px;
    line-height: 135px;
    letter-spacing: 34px;
    padding: 28px 34px;

    opacity: 0.78;

    text-shadow:
        0 0 8px rgba(255,255,255,1),
        0 0 18px rgba(255,255,255,0.95),
        0 0 34px rgba(255,255,255,0.8),
        0 0 48px rgba(245,243,255,0.55);

    animation: snowFloatStrong 14s ease-in-out infinite alternate;
}

.stApp::after {
    content:
        "✧     ✦        ✧       ✦       ⋆"
        "   ❄       ✦       ✧       ❄"
        "      ✦        ⋆       ✧       ✦";

    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 0;
    white-space: pre-wrap;

    color: rgba(255,255,255,0.86);

    font-size: 18px;
    line-height: 95px;
    letter-spacing: 25px;
    padding: 58px 18px;

    opacity: 0.62;

    text-shadow:
        0 0 6px rgba(255,255,255,0.95),
        0 0 14px rgba(255,255,255,0.82),
        0 0 26px rgba(245,243,255,0.55);

    animation: snowDriftStrong 20s linear infinite;
}

/* =========================================================
   動き
========================================================= */

@keyframes snowFloatStrong {

    0% {

        transform:
            translateY(0px)
            translateX(0px)
            scale(1);
    }

    100% {

        transform:
            translateY(-22px)
            translateX(14px)
            scale(1.03);
    }
}

@keyframes snowDriftStrong {

    0% {

        transform:
            translateY(-20px)
            translateX(0px);
    }

    100% {

        transform:
            translateY(24px)
            translateX(-12px);
    }
}
    .block-container {
        max-width: 900px;
        padding-top: 1.5rem;
        padding-bottom: 3rem;
    }

    h1 {
        color: #000000 !important;
        font-size: 2.75rem !important;
        font-weight: 1000 !important;
        letter-spacing: -0.06em;
        line-height: 1.05;
        margin-bottom: 0.35rem !important;
    }

    h1::after {
        content: " ✦";
        color: #b8b5ff;
        font-size: 0.8em;
        margin-left: 8px;
    }

    h2,
    h3,
    .stMarkdown h3 {
        color: #000000 !important;
        font-weight: 1000 !important;
        letter-spacing: -0.03em;
    }

    p,
    span,
    label {
        color: #222222;
    }

    hr {
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(170,170,210,0.55), transparent);
        margin: 1.7rem 0;
    }

    .stTabs [data-baseweb="tab-list"] {
        background: rgba(255,255,255,0.36);
        backdrop-filter: blur(24px);
        border-radius: 999px;
        padding: 0.42rem;
        border: 1px solid rgba(255,255,255,0.86);
        box-shadow: 0 10px 28px rgba(180,188,255,0.10);
        gap: 0.35rem;
    }

    .stTabs [data-baseweb="tab"] {
        border-radius: 999px;
        color: #444444;
        font-weight: 900;
        padding: 0.52rem 1rem;
        transition: all 0.16s ease;
    }

    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #c7c3ff, #ddd7ff, #edf2ff);
        color: #000000 !important;
        box-shadow: 0 8px 22px rgba(196,181,253,0.18);
    }

    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: rgba(255,255,255,0.34);
        backdrop-filter: blur(26px);
        border-radius: 34px;
        border: 1px solid rgba(255,255,255,0.86);
        padding: 1.05rem !important;
        margin-bottom: 1.2rem;
        box-shadow:
            0 16px 36px rgba(196,181,253,0.10),
            0 4px 14px rgba(180,188,255,0.07);
    }

    .sub-card {
        background:
            linear-gradient(
                135deg,
                rgba(255,255,255,0.50),
                rgba(245,243,255,0.34),
                rgba(239,246,255,0.28)
            );
        backdrop-filter: blur(26px);
        border-radius: 30px;
        padding: 1rem 1.1rem;
        border: 1px solid rgba(255,255,255,0.92);
        box-shadow:
            0 14px 32px rgba(196,181,253,0.12),
            inset 0 1px 0 rgba(255,255,255,0.55);
        margin-bottom: 1rem;
    }

    .sub-card-title {
        font-size: 1.02rem;
        font-weight: 1000;
        color: #000000;
        margin-bottom: 0.22rem;
    }

    .sub-card-text {
        color: #333333;
        font-weight: 750;
    }

    div[data-testid="stMetric"] {
        background:
            linear-gradient(
                135deg,
                rgba(255,255,255,0.48),
                rgba(245,243,255,0.32)
            );
        backdrop-filter: blur(24px);
        border-radius: 30px;
        border: 1px solid rgba(255,255,255,0.92);
        padding: 1rem;
        box-shadow:
            0 14px 32px rgba(196,181,253,0.12),
            inset 0 1px 0 rgba(255,255,255,0.55);
    }

    div[data-testid="stMetricLabel"] {
        color: #111111 !important;
        font-weight: 950 !important;
        opacity: 1 !important;
    }

    div[data-testid="stMetricValue"] {
        color: #000000 !important;
        font-weight: 1000 !important;
    }

    .group-title {
        background:
            linear-gradient(
                135deg,
                rgba(255,255,255,0.50),
                rgba(242,239,255,0.40),
                rgba(244,247,255,0.34)
            );
        backdrop-filter: blur(24px);
        color: #000000;
        border-radius: 26px;
        padding: 0.85rem 1.05rem;
        font-size: 1.05rem;
        font-weight: 1000;
        margin-top: 1.2rem;
        margin-bottom: 0.8rem;
        border: 1px solid rgba(255,255,255,0.92);
        box-shadow:
            0 12px 28px rgba(196,181,253,0.11),
            inset 0 1px 0 rgba(255,255,255,0.55);
    }

    .stButton > button,
    button[kind="primary"] {
        background: linear-gradient(135deg, #d7d3ff, #e6e2ff) !important;
        border: 1px solid rgba(199,195,255,0.75) !important;
        border-radius: 999px !important;
        color: #000000 !important;
        font-weight: 950 !important;
        font-size: 1rem !important;
        padding: 0.78rem 1.2rem !important;
        box-shadow: 0 8px 20px rgba(196,181,253,0.14);
        transition: all 0.16s ease;
    }

    .stButton > button:hover,
    button[kind="primary"]:hover {
        transform: translateY(-2px) scale(1.015);
        filter: brightness(1.03);
        background: linear-gradient(135deg, #d1ccff, #e2dcff) !important;
        box-shadow: 0 14px 28px rgba(196,181,253,0.20);
    }

    input,
    textarea {
        border-radius: 18px !important;
        border: 1px solid #e3e5ff !important;
        background: rgba(255,255,255,0.50) !important;
        color: #000000 !important;
    }

    div[data-baseweb="select"] > div {
        border-radius: 18px !important;
        border-color: #e3e5ff !important;
        background: rgba(255,255,255,0.48) !important;
        color: #000000 !important;
    }

    div[data-testid="stProgress"] {
        height: 14px;
        border-radius: 999px;
        overflow: hidden;
        background: rgba(255,255,255,0.34);
        border: 1px solid rgba(255,255,255,0.55);
        box-shadow: inset 0 2px 6px rgba(180,188,255,0.16);
    }

    div[data-testid="stProgress"] > div {
        background: rgba(255,255,255,0.28);
        border-radius: 999px;
    }

    div[data-testid="stProgress"] > div > div > div {
        border-radius: 999px;
        background:
            linear-gradient(
                90deg,
                #a78bfa 0%,
                #b794f6 45%,
                #c4b5fd 100%
            );
        box-shadow:
            0 0 10px rgba(167,139,250,0.45),
            0 0 20px rgba(196,181,253,0.32);
        animation: progressGlow 2.8s ease-in-out infinite;
    }

    @keyframes progressGlow {
        0% {
            filter: brightness(1);
        }
        50% {
            filter: brightness(1.12);
        }
        100% {
            filter: brightness(1);
        }
    }

    ::-webkit-scrollbar {
        width: 10px;
    }

    ::-webkit-scrollbar-thumb {
        background: linear-gradient(180deg, #c7c3ff, #dbeafe);
        border-radius: 999px;
    }

    ::-webkit-scrollbar-track {
        background: transparent;
    }

    /* =========================
   触れる曜日タグの色
========================= */

span[data-baseweb="tag"] {
    background: linear-gradient(
        135deg,
        #d8d3ff 0%,
        #eeeaff 55%,
        #f8faff 100%
    ) !important;

    color: #312e81 !important;

    border: 1px solid rgba(167,139,250,0.45) !important;

    border-radius: 14px !important;

    font-weight: 900 !important;

    box-shadow:
        0 6px 14px rgba(167,139,250,0.14),
        inset 0 1px 0 rgba(255,255,255,0.8) !important;
}

span[data-baseweb="tag"] svg {
    color: #6d5dfc !important;
    fill: #6d5dfc !important;
}

/* =========================
   カード hover 演出
========================= */

.sub-card,
div[data-testid="stVerticalBlockBorderWrapper"] {
    transition:
        transform 0.18s ease,
        box-shadow 0.18s ease,
        background 0.18s ease;
}

.sub-card:hover,
div[data-testid="stVerticalBlockBorderWrapper"]:hover {
    transform: translateY(-4px);
    box-shadow:
        0 22px 46px rgba(167,139,250,0.18),
        0 8px 18px rgba(147,197,253,0.12),
        inset 0 1px 0 rgba(255,255,255,0.65);
}

/* =========================
   Metricカード hover
========================= */

div[data-testid="stMetric"] {
    transition:
        transform 0.18s ease,
        box-shadow 0.18s ease,
        background 0.18s ease;
}

div[data-testid="stMetric"]:hover {
    transform: translateY(-4px);

    box-shadow:
        0 22px 46px rgba(167,139,250,0.18),
        0 8px 18px rgba(147,197,253,0.12),
        inset 0 1px 0 rgba(255,255,255,0.65);
}

/* =========================
   タスクカード hover
========================= */

.task-card {
    transition:
        transform 0.18s ease,
        box-shadow 0.18s ease,
        background 0.18s ease;
}

.task-card:hover {
    transform: translateY(-5px);

    box-shadow:
        0 24px 48px rgba(167,139,250,0.20),
        0 10px 22px rgba(147,197,253,0.14),
        inset 0 1px 0 rgba(255,255,255,0.68);
}

/* =========================
   スライダーを薄紫に固定
========================= */

/* 左側の進んだバー */
.stSlider [data-baseweb="slider"] div[role="presentation"]:first-child {
    background: linear-gradient(
        90deg,
        #c4b5fd 0%,
        #d8b4fe 50%,
        #ddd6fe 100%
    ) !important;

    border-radius: 999px !important;
}

/* バー全体 */
.stSlider [data-baseweb="slider"] > div > div {
    background: rgba(255,255,255,0.42) !important;
    border-radius: 999px !important;
}

/* つまみ */
.stSlider [role="slider"] {
    background: #ffffff !important;

    border: 2px solid #c4b5fd !important;

    box-shadow:
        0 0 10px rgba(196,181,253,0.45),
        0 0 18px rgba(221,214,254,0.35) !important;
}

    </style>
    """,
    unsafe_allow_html=True
)
# =====================
# 画面
# =====================

top_col1, top_col2 = st.columns([3, 1])

with top_col1:
    st.markdown("# 📚 Study Progress")
    st.caption("問題単位で進捗・復習・翌日のタスクを管理するアプリ")
    exams = [
        ("中央", 8, 22, "🔥"),
        ("早稲田", 8, 29, "🌸"),
        ("慶応", 9, 5, "💎"),
    ]

    st.markdown("### ⏳ 受験日カウントダウン")

    exam_cols = st.columns(3)

    for col, (name, month, day, icon) in zip(exam_cols, exams):
        exam_date, days_left = days_until_exam(month, day)

        with col:
            st.markdown(
                f"""
                <div class="sub-card">
                    <div class="sub-card-title">{icon} {name}</div>
                    <div class="sub-card-text">
                        {exam_date.month}月{exam_date.day}日まで<br>
                        <span style="font-size:1.6rem; font-weight:900;">
                            あと {days_left} 日
                        </span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
    title, message = random.choice(MOTIVATION_MESSAGES)

    st.markdown(
        f"""
        <div class="sub-card">
            <div class="sub-card-title">{title}</div>
            <div class="sub-card-text">
                {message}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    today_summary = calc_today_summary(tasks_df)
    pace_summary = calc_pace_summary(materials_df, questions_df)
    ai_ready_message = calc_ai_ready_summary(logs_df)

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown(
            f"""
            <div class="sub-card">
                <div class="sub-card-title">📌 今日のタスク</div>
                <div class="sub-card-text">
                    全 {today_summary["total"]} 問 / 完了 {today_summary["done"]} 問
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col2:
        st.markdown(
            f"""
            <div class="sub-card">
                <div class="sub-card-title">📚 今日の目標</div>
                <div class="sub-card-text">
                    あと {today_summary["remaining"]} 問！
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col3:
        st.markdown(
            f"""
            <div class="sub-card">
                <div class="sub-card-title">🌸 ペース：{pace_summary["status"]}</div>
                <div class="sub-card-text">
                    {pace_summary["message"]}
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown(
    f"""
    <div class="sub-card">
        <div class="sub-card-title">🧠 今日の学習分析</div>
        <div class="sub-card-text">
            {ai_ready_message}
        </div>
    </div>
    """,
    unsafe_allow_html=True
)

with top_col2:
    if st.button("🔄 更新", use_container_width=True):
        refresh_data_and_rerun()

tab_today, tab_material, tab_questions, tab_record, tab_progress = st.tabs([
    "今日",
    "教材",
    "問題",
    "記録",
    "進捗"
])
# =====================
# 今日
# =====================

with tab_today:
    st.subheader("🏠 今日やること")

    col_btn, col_info = st.columns([1, 1.4])

    with col_btn:
        if st.button("今日のタスクを作る", type="primary", use_container_width=True):
            if materials_df.empty or questions_df.empty:
                st.error("先に教材を登録してください。")
            else:
                live = load_all_data_live(sheets)

                count = generate_today_tasks(
                    live["materials_df"],
                    live["questions_df"],
                    live["tasks_df"],
                    sheets
                )

                if count == 0:
                    st.cache_data.clear()
                    st.info("新しく追加するタスクはありませんでした。")
                    st.rerun()
                else:
                    st.success(f"{count}件のタスクを作成しました。")
                    st.balloons()
                    refresh_data_and_rerun()

    with col_info:
        st.caption("復習・苦手問題・新規問題を自動で今日のタスクに入れます。")

    st.divider()
    st.markdown("### ↩️ 直前の記録を取り消す")

    undo_df_now = undo_df.copy()
    logs_df_now = logs_df.copy()
    tasks_df_now = tasks_df.copy()
    questions_df_now = questions_df.copy()

    if undo_df_now.empty:
        st.info("取り消せる操作はありません。")
    else:
        if "undone" not in undo_df_now.columns:
            undo_df_now["undone"] = ""

        available_undo = undo_df_now[
            undo_df_now["undone"].astype(str) != "済"
        ].copy()

        if available_undo.empty:
            st.info("取り消せる操作はありません。")
        else:
            latest = available_undo.tail(1).iloc[0]

            target_q = questions_df_now[
                questions_df_now["question_id"].astype(str) == str(latest["question_id"])
            ]

            if not target_q.empty:
                target_q = target_q.iloc[0]
                material_label = get_material_name(materials_df, target_q["material_id"])
                question_label = f'{material_label} 第{target_q["question_number"]}問'
            else:
                question_label = f'問題ID {latest["question_id"]}'

            st.warning(
                f"直前の操作：{question_label} / {latest['task_type']} / {latest['created_at']}"
            )

            if st.button("この直前操作を取り消す", use_container_width=True):
                try:
                    prev_question = json.loads(latest["prev_question_json"])

                    update_question_row(
                        sheets["questions"],
                        questions_df_now,
                        latest["question_id"],
                        {
                            "status": prev_question.get("status", ""),
                            "last_done_date": prev_question.get("last_done_date", ""),
                            "next_review_date": prev_question.get("next_review_date", ""),
                            "difficulty": prev_question.get("difficulty", ""),
                            "round": prev_question.get("round", "")
                        }
                    )

                    if safe_str(latest.get("prev_task_status", "")):
                        update_task_status(
                            sheets["daily_tasks"],
                            tasks_df_now,
                            latest["task_date"],
                            latest["question_id"],
                            latest["task_type"],
                            latest["prev_task_status"]
                        )

                    delete_log_by_id(
                        sheets["logs"],
                        logs_df_now,
                        latest["log_id"]
                    )

                    mark_undo_done(
                        sheets["undo_actions"],
                        undo_df_now,
                        latest["action_id"]
                    )

                    st.success("一つ前の状態に戻しました。")
                    refresh_data_and_rerun()

                except Exception as e:
                    st.error(f"取り消しに失敗しました：{e}")

    st.divider()
    st.markdown("### 好きな問題を今日に追加")

    if materials_df.empty or questions_df.empty:
        st.info("教材を登録すると、好きな問題を追加できます。")
    else:
        material_options_manual = {
            f'{row["subject"]}｜{row["material_name"]}': row["material_id"]
            for _, row in materials_df.iterrows()
        }

        with st.form("manual_add_task_form"):
            selected_material_manual = st.selectbox(
                "教材",
                list(material_options_manual.keys()),
                key="manual_task_material"
            )

            selected_material_id_manual = material_options_manual[selected_material_manual]

            target_questions = questions_df[
                questions_df["material_id"].astype(str) == str(selected_material_id_manual)
            ].copy()

            target_questions["question_number"] = pd.to_numeric(
                target_questions["question_number"],
                errors="coerce"
            )

            target_questions = target_questions.dropna(subset=["question_number"])

            if target_questions.empty:
                st.warning("この教材には問題がありません。")
                manual_question_number = 1
            else:
                max_q = int(target_questions["question_number"].max())

                manual_question_number = st.number_input(
                    "今日やる問題番号",
                    min_value=1,
                    max_value=max_q,
                    step=1
                )

            manual_task_type = st.selectbox(
                "タスク種別",
                ["新規", "復習", "苦手復習", "やり直し"]
            )

            submitted_manual = st.form_submit_button(
                "今日のタスクに追加",
                use_container_width=True
            )

            if submitted_manual:
                target_q = target_questions[
                    target_questions["question_number"].astype(int) == int(manual_question_number)
                ]

                if target_q.empty:
                    st.error("その問題番号は見つかりません。")
                else:
                    qid = target_q.iloc[0]["question_id"]
                    today_str = str(today_jst())

                    if task_exists(tasks_df, today_str, qid, manual_task_type):
                        st.info("この問題はすでに今日のタスクに入っています。")
                    else:
                        priority_map = {
                            "復習": 1,
                            "苦手復習": 2,
                            "やり直し": 2,
                            "新規": 3
                        }

                        priority = priority_map.get(manual_task_type, 3)

                        sheets["daily_tasks"].append_row([
                            today_str,
                            int(qid),
                            manual_task_type,
                            int(priority),
                            "未完了"
                        ])

                        st.success(f"第{manual_question_number}問を今日のタスクに追加しました！🎯")
                        st.balloons()
                        refresh_data_and_rerun()

    st.divider()

    all_today_tasks_df = build_today_tasks_df(
        tasks_df,
        questions_df,
        materials_df,
        hide_done=False
    )

    today_tasks_df = build_today_tasks_df(
        tasks_df,
        questions_df,
        materials_df,
        hide_done=True
    )

    if all_today_tasks_df.empty:
        st.info("今日のタスクはまだありません。上のボタンで作成できます。")
    else:
        total_tasks = len(all_today_tasks_df)

        done_tasks = len(
            all_today_tasks_df[
                all_today_tasks_df["status_task"].astype(str) == "完了"
            ]
        ) if "status_task" in all_today_tasks_df.columns else 0

        remaining_tasks = total_tasks - done_tasks

        c1, c2, c3 = st.columns(3)
        c1.metric("今日", total_tasks)
        c2.metric("完了", done_tasks)
        c3.metric("残り", remaining_tasks)

        st.progress(done_tasks / total_tasks if total_tasks else 0)

        st.markdown("### 今日のタスクリスト")

        if today_tasks_df.empty:
            st.success("今日のタスクは全部完了！すごい！🎉")
        else:
            task_type_order = ["復習", "苦手復習", "やり直し", "新規"]

            for group_type in task_type_order:
                group_df = today_tasks_df[
                    today_tasks_df["task_type"].astype(str) == group_type
                ]

                if group_df.empty:
                    continue

                st.markdown(
                    f'<div class="group-title">📌 {group_type}</div>',
                    unsafe_allow_html=True
                )

                for _, row in group_df.iterrows():
                    question_id = row["question_id"]
                    task_type = row.get("task_type", "")
                    task_status = row.get("status_task", row.get("status", "未完了"))
                    question_status = row.get("status_question", "")

                    material_label = safe_str(row.get("教材", ""))
                    qnum = int(row["question_number"]) if not pd.isna(row["question_number"]) else ""

                    with st.container(border=True):
                        subject_name = safe_str(row.get("subject", ""))
                        style = subject_style(subject_name)

                        subject_name = safe_str(row.get("subject", ""))
                        style = subject_style(subject_name)

                        card_html = f"""
                        <div class="task-card" style="
                            padding:1rem;
                            border-radius:22px;
                            margin-bottom:0.8rem;
                            border-left:8px solid {style['border']};
                            background:{style['bg']};
                            box-shadow:0 14px 32px rgba(15,23,42,0.08);
                        ">
                            <div style="
                                display:inline-block;
                                padding:0.25rem 0.75rem;
                                border-radius:999px;
                                font-weight:900;
                                margin-bottom:0.5rem;
                                background:{style['badge_bg']};
                                color:{style['badge_text']};
                            ">
                                {subject_name}
                            </div>

                            <div style="
                                font-size:1.35rem;
                                font-weight:900;
                                color:#7c2d12;
                                line-height:1.35;
                                margin-bottom:0.7rem;
                            ">
                                {material_label}<br>第{qnum}問
                            </div>

                            <span style="
                                display:inline-block;
                                padding:0.24rem 0.72rem;
                                border-radius:999px;
                                background:#fff1f2;
                                border:1px solid #fecdd3;
                                color:#9f1239;
                                margin-right:0.3rem;
                                margin-bottom:0.3rem;
                                font-size:0.85rem;
                                font-weight:750;
                            ">種類：{task_type}</span>

                            <span style="
                                display:inline-block;
                                padding:0.24rem 0.72rem;
                                border-radius:999px;
                                background:#fff1f2;
                                border:1px solid #fecdd3;
                                color:#9f1239;
                                margin-right:0.3rem;
                                margin-bottom:0.3rem;
                                font-size:0.85rem;
                                font-weight:750;
                            ">タスク：{task_status}</span>

                            <span style="
                                display:inline-block;
                                padding:0.24rem 0.72rem;
                                border-radius:999px;
                                background:#fff1f2;
                                border:1px solid #fecdd3;
                                color:#9f1239;
                                margin-right:0.3rem;
                                margin-bottom:0.3rem;
                                font-size:0.85rem;
                                font-weight:750;
                            ">問題：{question_status}</span>
                        </div>
                        """

                        st.html(card_html)

                        issue = safe_str(row.get("issue", ""))
                        tags = safe_str(row.get("tags", ""))
                        user_note = safe_str(row.get("user_note", ""))

                        if issue:
                            st.write(f"**論点：** {issue}")
                        if tags:
                            st.write(f"**タグ：** {tags}")
                        if user_note:
                            st.write(f"**メモ：** {user_note}")

                        with st.expander("このタスクを編集する"):
                            task_type_options = ["新規", "復習", "苦手復習", "やり直し"]
                            status_options_task = ["未完了", "完了"]

                            edited_task_type = st.selectbox(
                                "タスク種別",
                                task_type_options,
                                index=task_type_options.index(task_type)
                                if task_type in task_type_options else 0,
                                key=f"edit_task_type_{question_id}_{task_type}"
                            )

                            edited_priority = st.number_input(
                                "優先度",
                                min_value=1,
                                max_value=99,
                                value=safe_int(row.get("priority", 3), 3),
                                key=f"edit_priority_{question_id}_{task_type}"
                            )

                            edited_task_status = st.selectbox(
                                "タスク状態",
                                status_options_task,
                                index=status_options_task.index(task_status)
                                if task_status in status_options_task else 0,
                                key=f"edit_task_status_{question_id}_{task_type}"
                            )

                            if st.button(
                                "タスク情報を保存",
                                key=f"save_task_edit_{question_id}_{task_type}",
                                use_container_width=True
                            ):
                                ok = update_task_row(
                                    sheets["daily_tasks"],
                                    tasks_df,
                                    str(today_jst()),
                                    question_id,
                                    task_type,
                                    {
                                        "task_type": edited_task_type,
                                        "priority": int(edited_priority),
                                        "status": edited_task_status
                                    }
                                )

                                if ok:
                                    st.success("タスク情報を更新しました。")
                                    refresh_data_and_rerun()
                                else:
                                    st.error("更新対象が見つかりませんでした。")

                        with st.expander("この問題を記録する"):
                            result = st.selectbox(
                                "結果",
                                ["完璧", "微妙", "苦手", "未完了"],
                                key=f"today_result_{question_id}_{task_type}"
                            )

                            difficulty = st.slider(
                                "難易度",
                                1,
                                5,
                                int(row.get("difficulty", 3)) if str(row.get("difficulty", 3)).isdigit() else 3,
                                key=f"today_diff_{question_id}_{task_type}"
                            )

                            study_minutes = st.number_input(
                                "学習時間（分）",
                                min_value=0,
                                step=5,
                                key=f"today_min_{question_id}_{task_type}"
                            )

                            comment = st.text_area(
                                "コメント",
                                placeholder="例：規範は覚えていたが、あてはめが薄かった",
                                key=f"today_comment_{question_id}_{task_type}"
                            )

                            if st.button(
                                "保存",
                                key=f"today_save_{question_id}_{task_type}",
                                use_container_width=True
                            ):
                                save_learning_log(
                                    sheets=sheets,
                                    logs_df=logs_df,
                                    questions_df=questions_df,
                                    tasks_df=tasks_df,
                                    question_id=question_id,
                                    task_type=task_type,
                                    result=result,
                                    difficulty=difficulty,
                                    study_minutes=study_minutes,
                                    comment=comment
                                )

                                show_result_effect(result)

                            if st.button(
                                "このタスクを削除",
                                key=f"today_delete_{question_id}_{task_type}",
                                use_container_width=True
                            ):
                                ok = delete_task(
                                    sheets["daily_tasks"],
                                    tasks_df,
                                    str(today_jst()),
                                    question_id,
                                    task_type
                                )

                                if ok:
                                    st.warning("タスクを削除しました。")
                                    refresh_data_and_rerun()
                                else:
                                    st.error("削除対象が見つかりませんでした。")

    st.divider()
    st.markdown("## 🌙 明日の予定プレビュー")
    st.caption("今日の記録・教材の曜日設定・未着手問題から、明日やる予定を先読みします。")

    tomorrow_preview_df = build_tomorrow_preview_df(materials_df, questions_df)

    if tomorrow_preview_df.empty:
        st.info("明日の予定はまだありません。")
    else:
        task_type_order = ["復習予定", "苦手復習予定", "新規予定"]

        for group_type in task_type_order:
            group_df = tomorrow_preview_df[
                tomorrow_preview_df["task_type"].astype(str) == group_type
            ]

            if group_df.empty:
                continue

            st.markdown(
                f'<div class="group-title">📌 {group_type}</div>',
                unsafe_allow_html=True
            )

            for _, row in group_df.iterrows():
                material_label = safe_str(row.get("教材", ""))
                qnum = int(row["question_number"]) if not pd.isna(row["question_number"]) else ""

                with st.container(border=True):
                    subject_name = safe_str(row.get("subject", ""))
                    style = subject_style(subject_name)

                    card_html = f"""
                    <div style="
                        padding:1rem;
                        border-radius:22px;
                        margin-bottom:0.8rem;
                        border-left:8px solid {style['border']};
                        background:{style['bg']};
                        box-shadow:0 14px 32px rgba(15,23,42,0.08);
                    ">
                        <div style="
                            display:inline-block;
                            padding:0.25rem 0.75rem;
                            border-radius:999px;
                            font-weight:900;
                            margin-bottom:0.5rem;
                            background:{style['badge_bg']};
                            color:{style['badge_text']};
                        ">
                            {subject_name}
                        </div>

                        <div style="
                            font-size:1.35rem;
                            font-weight:900;
                            color:#7c2d12;
                            line-height:1.35;
                            margin-bottom:0.7rem;
                        ">
                            {material_label}<br>第{qnum}問
                        </div>

                        <span style="
                            display:inline-block;
                    　      padding:0.24rem 0.72rem;
                            border-radius:999px;
                            background:#fff1f2;
                            border:1px solid #fecdd3;
                            color:#9f1239;
                            margin-right:0.3rem;
                            margin-bottom:0.3rem;
                            font-size:0.85rem;
                            font-weight:750;
                        ">
                            種類：{group_type}
                        </span>
                    </div>
                    """

                    st.html(card_html)                                     

                    issue = safe_str(row.get("issue", ""))
                    tags = safe_str(row.get("tags", ""))
                    user_note = safe_str(row.get("user_note", ""))

                    if issue:
                        st.write(f"**論点：** {issue}")
                    if tags:
                        st.write(f"**タグ：** {tags}")
                    if user_note:
                        st.write(f"**メモ：** {user_note}")


# =====================
# 教材
# =====================

with tab_material:
    st.subheader("📘 教材を登録")

    with st.form("add_material_form"):
        subject = st.text_input("科目", placeholder="例：憲法")
        material_name = st.text_input("教材名", placeholder="例：憲法基礎問")
        total_questions = st.number_input("総問題数", min_value=1, step=1)
        target_date = st.date_input("目標完了日")

        study_days = st.multiselect(
            "この教材に触れる曜日",
            WEEKDAYS,
            default=["月", "水", "金"]
        )

        submitted = st.form_submit_button(
            "教材を登録して問題番号を作る",
            use_container_width=True
        )

        if submitted:
            if subject.strip() == "" or material_name.strip() == "":
                st.error("科目と教材名を入力してください。")
            elif len(study_days) == 0:
                st.error("少なくとも1つ曜日を選んでください。")
            else:
                material_id = next_id(materials_df, "material_id")

                sheets["materials"].append_row([
                    int(material_id),
                    subject,
                    material_name,
                    int(total_questions),
                    str(target_date),
                    ",".join(study_days)
                ])

                next_question_id = next_id(questions_df, "question_id")
                question_rows = []

                for i in range(1, int(total_questions) + 1):
                    question_rows.append([
                        int(next_question_id),
                        int(material_id),
                        int(i),
                        "未着手",
                        1,
                        "",
                        "",
                        "",
                        "",
                        "",
                        ""
                    ])
                    next_question_id += 1

                sheets["questions"].append_rows(question_rows)

                st.success(
                    f"{material_name} を登録し、第1問〜第{int(total_questions)}問を作成しました。"
                )
                st.balloons()
                refresh_data_and_rerun()

    st.divider()
    st.markdown("### 登録済み教材を編集")

    if materials_df.empty:
        st.info("まだ教材がありません。")
    else:
        material_edit_options = {
            f'{row["subject"]}｜{row["material_name"]}': row["material_id"]
            for _, row in materials_df.iterrows()
        }

        selected_material_edit_label = st.selectbox(
            "編集する教材",
            list(material_edit_options.keys()),
            key="edit_material_select"
        )

        selected_material_edit_id = material_edit_options[selected_material_edit_label]

        selected_material = materials_df[
            materials_df["material_id"].astype(str) == str(selected_material_edit_id)
        ].iloc[0]

        current_days = safe_str(selected_material.get("study_days", "")).split(",")
        current_days = [d for d in current_days if d in WEEKDAYS]

        with st.container(border=True):
            st.markdown(
                f"**現在：{selected_material['subject']}｜{selected_material['material_name']}**"
            )

            with st.form("edit_material_form"):
                edit_subject = st.text_input(
                    "科目",
                    value=safe_str(selected_material.get("subject", ""))
                )

                edit_material_name = st.text_input(
                    "教材名",
                    value=safe_str(selected_material.get("material_name", ""))
                )

                edit_total_questions = st.number_input(
                    "総問題数",
                    min_value=1,
                    step=1,
                    value=int(selected_material["total_questions"])
                    if str(selected_material["total_questions"]).isdigit() else 1
                )

                current_target_dt = pd.to_datetime(
                    selected_material.get("target_date", ""),
                    errors="coerce"
                )

                if pd.isna(current_target_dt):
                    current_target_date = today_jst()
                else:
                    current_target_date = current_target_dt.date()

                edit_target_date = st.date_input(
                    "目標完了日",
                    value=current_target_date
                )

                edit_study_days = st.multiselect(
                    "この教材に触れる曜日",
                    WEEKDAYS,
                    default=current_days if current_days else ["月", "水", "金"]
                )

                submitted_edit_material = st.form_submit_button(
                    "教材情報を保存",
                    use_container_width=True
                )

                if submitted_edit_material:
                    if edit_subject.strip() == "" or edit_material_name.strip() == "":
                        st.error("科目と教材名を入力してください。")
                    elif len(edit_study_days) == 0:
                        st.error("少なくとも1つ曜日を選んでください。")
                    else:
                        ok = update_material_row(
                            sheets["materials"],
                            materials_df,
                            selected_material_edit_id,
                            {
                                "subject": edit_subject,
                                "material_name": edit_material_name,
                                "total_questions": int(edit_total_questions),
                                "target_date": str(edit_target_date),
                                "study_days": ",".join(edit_study_days)
                            }
                        )

                        if ok:
                            st.success("教材情報を更新しました。")
                            refresh_data_and_rerun()
                        else:
                            st.error("更新対象の教材が見つかりませんでした。")

        st.caption("※総問題数を増やしても、追加分の問題番号はまだ自動生成されません。")


# =====================
# 問題
# =====================

with tab_questions:
    st.subheader("📝 問題を育てる")

    if materials_df.empty or questions_df.empty:
        st.info("先に教材を登録してください。")
    else:
        material_options = {
            f'{row["subject"]}｜{row["material_name"]}': row["material_id"]
            for _, row in materials_df.iterrows()
        }

        selected_material_label = st.selectbox(
            "教材を選択",
            list(material_options.keys()),
            key="question_material_select"
        )

        selected_material_id = material_options[selected_material_label]

        filtered_questions = questions_df[
            questions_df["material_id"].astype(str) == str(selected_material_id)
        ].copy()

        filtered_questions["question_number"] = pd.to_numeric(
            filtered_questions["question_number"],
            errors="coerce"
        )

        filtered_questions = filtered_questions.sort_values("question_number")

        st.caption("最初は問題番号だけでOK。あとから論点・タグ・メモを足していく画面です。")

        question_options = {
            f'第{int(row["question_number"])}問　{safe_str(row.get("issue", ""))}': row["question_id"]
            for _, row in filtered_questions.iterrows()
        }

        selected_question_label = st.selectbox(
            "編集する問題",
            list(question_options.keys())
        )

        selected_question_id = question_options[selected_question_label]

        selected_question = questions_df[
            questions_df["question_id"].astype(str) == str(selected_question_id)
        ].iloc[0]

        with st.container(border=True):
            st.markdown(f"### 第{selected_question['question_number']}問")

            status_options = ["未着手", "学習中", "復習待ち", "苦手", "完了"]
            current_status = safe_str(selected_question.get("status", "未着手"))

            with st.form("edit_question_form"):
                status = st.selectbox(
                    "状態",
                    status_options,
                    index=status_options.index(current_status)
                    if current_status in status_options else 0
                )

                current_round = selected_question.get("round", 1)

                round_num = st.number_input(
                    "周回数",
                    min_value=1,
                    step=1,
                    value=int(current_round) if str(current_round).isdigit() else 1
                )

                issue = st.text_input(
                    "論点",
                    value=safe_str(selected_question.get("issue", "")),
                    placeholder="例：政教分離、目的効果基準"
                )

                tags = st.text_input(
                    "タグ・関連過去問",
                    value=safe_str(selected_question.get("tags", "")),
                    placeholder="例：司法H15, 慶應2019"
                )

                user_note = st.text_area(
                    "メモ",
                    value=safe_str(selected_question.get("user_note", "")),
                    placeholder="例：玉串料判決との違いに注意"
                )

                current_difficulty = selected_question.get("difficulty", 3)

                difficulty = st.slider(
                    "苦手度・難易度",
                    min_value=1,
                    max_value=5,
                    value=int(current_difficulty)
                    if str(current_difficulty).isdigit() else 3
                )

                last_done_raw = selected_question.get("last_done_date", "")
                last_done_dt = pd.to_datetime(last_done_raw, errors="coerce")

                if pd.isna(last_done_dt):
                    default_next_review_date = today_jst() + timedelta(days=1)
                else:
                    default_next_review_date = last_done_dt.date() + timedelta(days=1)

                next_review_date = st.date_input(
                    "次回復習日",
                    value=default_next_review_date
                )

                submitted = st.form_submit_button(
                    "問題情報を保存",
                    use_container_width=True
                )

                if submitted:
                    if status == "未着手":
                        deleted_logs, reset_tasks = reset_question_before_learning(
                            sheets=sheets,
                            questions_df=questions_df,
                            logs_df=logs_df,
                            tasks_df=tasks_df,
                            question_id=selected_question_id
                        )

                        # 論点・タグ・メモは消さずに保存する
                        update_question_row(
                            sheets["questions"],
                            questions_df,
                            selected_question_id,
                            {
                                "issue": issue,
                                "tags": tags,
                                "user_note": user_note,
                            }
                        )

                        st.success(
                            f"未着手に戻しました。学習ログ {deleted_logs} 件を削除し、タスク {reset_tasks} 件を未完了に戻しました。"
                        )
                        refresh_data_and_rerun()

                    else:
                        ok = update_question_row(
                            sheets["questions"],
                            questions_df,
                            selected_question_id,
                            {
                                "status": status,
                                "round": int(round_num),
                                "issue": issue,
                                "tags": tags,
                                "user_note": user_note,
                                "difficulty": int(difficulty),
                                "next_review_date": str(next_review_date)
                            }
                        )

                        if ok:
                            st.success("問題情報を更新しました。")
                            refresh_data_and_rerun()
                        else:
                            st.error("更新対象の問題が見つかりませんでした。")

        with st.expander("この教材の問題一覧を見る"):
            for _, q in filtered_questions.head(200).iterrows():
                qid = q["question_id"]
                issue = safe_str(q.get("issue", ""))
                status = safe_str(q.get("status", ""))

                q_logs = logs_df[
                    logs_df["question_id"].astype(str) == str(qid)
                ].copy()

                if q_logs.empty:
                    history_text = "未着手"
                else:
                    q_logs = q_logs.sort_values("date")
                    history_parts = []

                    for i, (_, log) in enumerate(q_logs.iterrows(), start=1):
                        history_parts.append(
                            f"{i}回目：{log['date']}（{log['result']}）"
                        )

                    history_text = " / ".join(history_parts)

                with st.container(border=True):
                    st.write(
                        f"**第{int(q['question_number'])}問**　{status}　{issue}"
                    )
                    st.caption(history_text)
                    latest_comment = latest_comment_for_question(logs_df, qid)
                    if latest_comment:
                        st.write(f"💬 最新コメント：{latest_comment}")


# =====================
# 記録
# =====================

with tab_record:
    st.subheader("🌙 学習記録")

    if materials_df.empty or questions_df.empty:
        st.info("先に教材を登録してください。")
    else:
        material_options = {
            f'{row["subject"]}｜{row["material_name"]}': row["material_id"]
            for _, row in materials_df.iterrows()
        }

        selected_material_label_log = st.selectbox(
            "教材を選択",
            list(material_options.keys()),
            key="log_material_select"
        )

        selected_material_id_log = material_options[selected_material_label_log]

        filtered_questions_log = questions_df[
            questions_df["material_id"].astype(str) == str(selected_material_id_log)
        ].copy()

        filtered_questions_log["question_number"] = pd.to_numeric(
            filtered_questions_log["question_number"],
            errors="coerce"
        )

        filtered_questions_log = filtered_questions_log.sort_values("question_number")

        question_options_log = {
            f'第{int(row["question_number"])}問　{safe_str(row.get("issue", ""))}': row["question_id"]
            for _, row in filtered_questions_log.iterrows()
        }

        with st.form("add_log_form"):
            selected_question_label_log = st.selectbox(
                "記録する問題",
                list(question_options_log.keys())
            )

            selected_question_id_log = question_options_log[selected_question_label_log]

            result = st.selectbox(
                "結果",
                ["できた", "微妙", "できなかった", "未完了"]
            )

            difficulty = st.slider("今日の難易度", 1, 5, 3)

            study_minutes = st.number_input(
                "学習時間（分）",
                min_value=0,
                step=5
            )

            comment = st.text_area(
                "今日のコメント",
                placeholder="例：規範は覚えていたが、あてはめが薄かった"
            )

            submitted = st.form_submit_button(
                "学習記録を保存",
                use_container_width=True
            )

            if submitted:
                save_learning_log(
                    sheets=sheets,
                    logs_df=logs_df,
                    questions_df=questions_df,
                    tasks_df=tasks_df,
                    question_id=selected_question_id_log,
                    task_type="手動記録",
                    result=result,
                    difficulty=difficulty,
                    study_minutes=study_minutes,
                    comment=comment
                )

                show_result_effect(result)

    st.divider()
    logs_df = load_sheet(sheets["logs"], "logs")

    st.markdown("### 最近の記録")

    if logs_df.empty:
        st.info("まだ学習ログがありません。")
    else:
        recent_logs = logs_df.tail(10).copy()
        recent_logs = recent_logs.iloc[::-1]

        for _, log in recent_logs.iterrows():
            with st.container(border=True):
                qid = log["question_id"]
                q = questions_df[
                    questions_df["question_id"].astype(str) == str(qid)
                ]

                if not q.empty:
                    q = q.iloc[0]
                    material = get_material_name(materials_df, q["material_id"])
                    st.markdown(f"**{material}　第{q['question_number']}問**")
                else:
                    st.markdown(f"**問題ID：{qid}**")

                st.caption(
                    f"{log['date']} / {log['result']} / 難易度 {log['difficulty']} / {log['study_minutes']}分"
                )

                if safe_str(log.get("comment", "")):
                    st.write(log.get("comment", ""))


# =====================
# 進捗
# =====================

with tab_progress:
    st.subheader("📊 進捗")

    if materials_df.empty or questions_df.empty:
        st.info("まだ進捗データがありません。")
    else:
        for _, material in materials_df.iterrows():
            material_id = material["material_id"]

            qs = questions_df[
                questions_df["material_id"].astype(str) == str(material_id)
            ]

            total = len(qs)

            touched = len(qs[
                qs["status"].astype(str).isin(["復習待ち", "苦手", "完了", "学習中"])
            ])

            completed = len(qs[
                qs["status"].astype(str) == "完了"
            ])

            weak = len(qs[
                qs["status"].astype(str) == "苦手"
            ])

            progress = touched / total if total > 0 else 0

            with st.container(border=True):
                st.markdown(f"### {material['subject']}｜{material['material_name']}")

                c1, c2 = st.columns(2)
                c1.metric("総問題数", total)
                c2.metric("着手済み", touched)

                c3, c4 = st.columns(2)
                c3.metric("完了", completed)
                c4.metric("苦手", weak)

                st.progress(progress)
                st.caption(f"着手率：{round(progress * 100, 1)}%")

                study_days = safe_str(material.get("study_days", "")).split(",")
                study_days = [d for d in study_days if d in WEEKDAYS]

                plan = estimate_finish_plan(
                    total=total,
                    touched=touched,
                    study_days=study_days,
                    target_date_raw=material.get("target_date", "")
                )

                st.markdown(
                    f"""
                    <div class="sub-card">
                        <div class="sub-card-title">🗓 一周予定</div>
                        <div class="sub-card-text">
                            残り {plan["remaining"]} 問。<br>
                            このペースなら、1回の学習日に約 {plan["per_day"]} 問ずつ進めると、<br>
                            <b>{plan["finish_date"]}</b> に一周予定！
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

                weak_qs = qs[qs["status"].astype(str) == "苦手"]

                if not weak_qs.empty:
                    with st.expander("苦手問題を見る"):
                        for _, q in weak_qs.iterrows():
                            st.write(
                                f"第{q['question_number']}問　{safe_str(q.get('issue', ''))}"
                            )


# =====================
# 開発者用
# =====================

with st.expander("開発者用：データ確認"):
    st.markdown("### materials")
    st.dataframe(materials_df, use_container_width=True)

    st.markdown("### questions")
    st.dataframe(questions_df, use_container_width=True)

    st.markdown("### logs")
    st.dataframe(logs_df, use_container_width=True)

    st.markdown("### daily_tasks")
    st.dataframe(tasks_df, use_container_width=True)

    st.markdown("### undo_actions")
    st.dataframe(undo_df, use_container_width=True)
