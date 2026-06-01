import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, timedelta
import time

st.set_page_config(
    page_title="Study Progress",
    page_icon="📚",
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

WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]


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

    return {
        "materials": spreadsheet.worksheet("materials"),
        "questions": spreadsheet.worksheet("questions"),
        "logs": spreadsheet.worksheet("logs"),
        "daily_tasks": spreadsheet.worksheet("daily_tasks"),
    }


def load_sheet(ws):
    records = ws.get_all_records()
    return pd.DataFrame(records)


def safe_str(value):
    if pd.isna(value):
        return ""
    return str(value)


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

    if "status" not in headers:
        return False

    row_values[headers.index("status")] = new_status
    end_col = col_letter(len(headers))

    ws.update(f"A{sheet_row}:{end_col}{sheet_row}", [row_values])
    return True


def count_study_days_until(target_date, study_days, start_date=None):
    if start_date is None:
        start_date = date.today()

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


def generate_today_tasks(materials_df, questions_df, tasks_df, sheets):
    today = date.today()
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
        date.today(),
        hide_done=hide_done
    )


def build_tomorrow_preview_df(materials_df, questions_df):
    tomorrow = date.today() + timedelta(days=1)
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
    today_str = str(date.today())

    sheets["logs"].append_row([
        int(log_id),
        today_str,
        int(question_id),
        result,
        int(difficulty),
        int(study_minutes),
        comment
    ])

    selected_q = questions_df[
        questions_df["question_id"].astype(str) == str(question_id)
    ]

    if selected_q.empty:
        return

    selected_q = selected_q.iloc[0]
    current_round = selected_q.get("round", 1)
    current_round = int(current_round) if str(current_round).isdigit() else 1

    # =====================
    # 問題ステータスの決定
    # =====================

    if result == "未完了":
        new_status = "未着手"
        next_review = selected_q.get("next_review_date", "")
        new_round = current_round

    elif task_type in ["復習", "苦手復習", "やり直し"] and result == "できた":
        # 復習系で「できた」なら卒業扱い
        new_status = "完了"
        next_review = ""
        new_round = current_round + 1

    elif result == "できた":
        # 新規で「できた」なら翌日に1回復習
        new_status = "復習待ち"
        next_review = date.today() + timedelta(days=1)
        new_round = current_round + 1

    elif result == "微妙":
        # 微妙なら明日もう一回
        new_status = "復習待ち"
        next_review = date.today() + timedelta(days=1)
        new_round = current_round + 1

    elif result == "できなかった":
        # できなかったら苦手として明日復習
        new_status = "苦手"
        next_review = date.today() + timedelta(days=1)
        new_round = current_round + 1

    else:
        new_status = "未着手"
        next_review = date.today() + timedelta(days=1)
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

    time.sleep(1.5)
    st.rerun()


# =====================
# データ読み込み
# =====================

sheets = connect_sheets()

materials_df = load_sheet(sheets["materials"])
questions_df = load_sheet(sheets["questions"])
logs_df = load_sheet(sheets["logs"])
tasks_df = load_sheet(sheets["daily_tasks"])


# =====================
# CSS
# =====================

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 3rem;
        max-width: 780px;
    }

    h1 {
        font-size: 2.1rem !important;
        line-height: 1.15 !important;
        margin-bottom: 0.2rem !important;
    }

    h2 {
        font-size: 1.45rem !important;
        margin-top: 1rem !important;
    }

    h3 {
        font-size: 1.15rem !important;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 0.2rem;
        overflow-x: auto;
        white-space: nowrap;
    }

    .stTabs [data-baseweb="tab"] {
        font-size: 0.95rem;
        padding-left: 0.65rem;
        padding-right: 0.65rem;
    }

    div[data-testid="stMetric"] {
        background: #fafafa;
        border: 1px solid #eeeeee;
        padding: 0.75rem;
        border-radius: 14px;
    }

    .card-title {
        font-size: 1.22rem;
        font-weight: 700;
        margin-bottom: 0.35rem;
    }

    .pill {
        display: inline-block;
        padding: 0.18rem 0.55rem;
        border-radius: 999px;
        background: #f2f2f2;
        margin-right: 0.25rem;
        margin-bottom: 0.25rem;
        font-size: 0.85rem;
    }

    .group-title {
        font-size: 1.05rem;
        font-weight: 700;
        margin-top: 1.2rem;
        margin-bottom: 0.5rem;
        padding: 0.45rem 0.7rem;
        background: #f7f7f7;
        border-radius: 12px;
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

with top_col2:
    if st.button("🔄 更新", use_container_width=True):
        st.rerun()

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
                count = generate_today_tasks(
                    materials_df,
                    questions_df,
                    tasks_df,
                    sheets
                )

                if count == 0:
                    st.info("新しく追加するタスクはありませんでした。")
                else:
                    st.success(f"{count}件のタスクを作成しました。")
                    st.balloons()
                    time.sleep(1.2)

                st.rerun()

    with col_info:
        st.caption("復習・苦手問題・新規問題を自動で今日のタスクに入れます。")

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
                    today_str = str(date.today())

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
                        time.sleep(1.2)
                        st.rerun()

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
                        st.markdown(
                            f"""
                            <div class="card-title">{material_label}<br>第{qnum}問</div>
                            <span class="pill">種類：{task_type}</span>
                            <span class="pill">タスク：{task_status}</span>
                            <span class="pill">問題：{question_status}</span>
                            """,
                            unsafe_allow_html=True
                        )

                        issue = safe_str(row.get("issue", ""))
                        tags = safe_str(row.get("tags", ""))
                        user_note = safe_str(row.get("user_note", ""))

                        if issue:
                            st.write(f"**論点：** {issue}")
                        if tags:
                            st.write(f"**タグ：** {tags}")
                        if user_note:
                            st.write(f"**メモ：** {user_note}")

                        with st.expander("この問題を記録する"):
                            result = st.selectbox(
                                "結果",
                                ["できた", "微妙", "できなかった", "未完了"],
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
                                    str(date.today()),
                                    question_id,
                                    task_type
                                )

                                if ok:
                                    st.warning("タスクを削除しました。")
                                    time.sleep(1.0)
                                    st.rerun()
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
                    st.markdown(
                        f"""
                        <div class="card-title">{material_label}<br>第{qnum}問</div>
                        <span class="pill">種類：{group_type}</span>
                        """,
                        unsafe_allow_html=True
                    )

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
                time.sleep(1.2)
                st.rerun()

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
                    current_target_date = date.today()
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
                            time.sleep(1.0)
                            st.rerun()
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
                    default_next_review_date = date.today() + timedelta(days=1)
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
                        time.sleep(1.0)
                        st.rerun()
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
    logs_df = load_sheet(sheets["logs"])

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
