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


def next_id(df, id_col):
    if df.empty or id_col not in df.columns:
        return 1

    ids = pd.to_numeric(df[id_col], errors="coerce").fillna(0)
    return int(ids.max()) + 1


def safe_str(value):
    if pd.isna(value):
        return ""
    return str(value)


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

    for col_name, value in new_values.items():
        if col_name not in questions_df.columns:
            continue

        col_index = list(questions_df.columns).index(col_name) + 1
        ws.update_cell(sheet_row, col_index, value)

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

    if "status" not in tasks_df.columns:
        return False

    col_index = list(tasks_df.columns).index("status") + 1
    ws.update_cell(sheet_row, col_index, new_status)

    return True


def count_study_days_until(target_date, study_days):
    today = date.today()
    count = 0
    d = today

    while d <= target_date:
        if WEEKDAY_MAP[d.weekday()] in study_days:
            count += 1
        d += timedelta(days=1)

    return max(count, 1)


def task_exists(tasks_df, task_date, question_id, task_type):
    if tasks_df.empty:
        return False

    matched = tasks_df[
        (tasks_df["task_date"].astype(str) == str(task_date)) &
        (tasks_df["question_id"].astype(str) == str(question_id)) &
        (tasks_df["task_type"].astype(str) == str(task_type))
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
        study_days = str(material["study_days"]).split(",")

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
            qs["next_review_date"].astype(str) == today_str
        ]

        for _, q in review_qs.iterrows():
            if not task_exists(tasks_df, today_str, q["question_id"], "復習"):
                new_rows.append([
                    today_str,
                    q["question_id"],
                    "復習",
                    1,
                    "未完了"
                ])

        weak_qs = qs[
            qs["status"].astype(str) == "苦手"
        ]

        for _, q in weak_qs.iterrows():
            if not task_exists(tasks_df, today_str, q["question_id"], "苦手復習"):
                new_rows.append([
                    today_str,
                    q["question_id"],
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
        remaining_days = count_study_days_until(target, study_days)
        new_count = max(1, -(-remaining_questions // remaining_days))

        new_qs = unstarted_qs.head(new_count)

        for _, q in new_qs.iterrows():
            if not task_exists(tasks_df, today_str, q["question_id"], "新規"):
                new_rows.append([
                    today_str,
                    q["question_id"],
                    "新規",
                    3,
                    "未完了"
                ])

    if new_rows:
        sheets["daily_tasks"].append_rows(new_rows)

    return len(new_rows)


def build_today_tasks_df(tasks_df, questions_df, materials_df):
    today_str = str(date.today())

    if tasks_df.empty:
        return pd.DataFrame()

    today_tasks = tasks_df[
        tasks_df["task_date"].astype(str) == today_str
    ].copy()

    if today_tasks.empty:
        return pd.DataFrame()

    merged = today_tasks.merge(
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

    merged = merged.sort_values(
        ["priority", "教材", "question_number"]
    )

    return merged


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
        log_id,
        today_str,
        question_id,
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

    if result == "できた":
        new_status = "復習待ち"
        next_review = date.today() + timedelta(days=1)
    elif result == "微妙":
        new_status = "復習待ち"
        next_review = date.today() + timedelta(days=1)
    elif result == "できなかった":
        new_status = "苦手"
        next_review = date.today() + timedelta(days=1)
    else:
        new_status = "未着手"
        next_review = date.today() + timedelta(days=1)

    update_question_row(
        sheets["questions"],
        questions_df,
        question_id,
        {
            "status": new_status,
            "last_done_date": today_str,
            "next_review_date": str(next_review),
            "difficulty": difficulty,
            "round": current_round
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

    time.sleep(1.5)
    st.rerun()


sheets = connect_sheets()

materials_df = load_sheet(sheets["materials"])
questions_df = load_sheet(sheets["questions"])
logs_df = load_sheet(sheets["logs"])
tasks_df = load_sheet(sheets["daily_tasks"])


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

    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 16px;
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
    </style>
    """,
    unsafe_allow_html=True
)


st.markdown("# 📚 Study Progress")
st.caption("問題単位で進捗・復習・翌日のタスクを管理するアプリ")

tab_today, tab_material, tab_questions, tab_record, tab_progress = st.tabs([
    "今日",
    "教材",
    "問題",
    "記録",
    "進捗"
])


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
                max_q = 1
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
                ["新規", "復習", "やり直し"]
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
                        priority = 1 if manual_task_type in ["復習", "やり直し"] else 3

                        sheets["daily_tasks"].append_row([
                            str(today_str),
                            str(qid),
                            str(manual_task_type),
                            str(priority),
                            "未完了"
                        ])

                        st.success(f"第{manual_question_number}問を今日のタスクに追加しました！🎯")
                        st.balloons()
                        time.sleep(1.2)
                        st.rerun()

    st.divider()

    tasks_df = load_sheet(sheets["daily_tasks"])
    today_tasks_df = build_today_tasks_df(tasks_df, questions_df, materials_df)

    if today_tasks_df.empty:
        st.info("今日のタスクはまだありません。上のボタンで作成できます。")
    else:
        total_tasks = len(today_tasks_df)

        done_tasks = len(
            today_tasks_df[
                today_tasks_df["status_task"].astype(str) == "完了"
            ]
        ) if "status_task" in today_tasks_df.columns else 0

        c1, c2, c3 = st.columns(3)
        c1.metric("今日", total_tasks)
        c2.metric("完了", done_tasks)
        c3.metric("残り", total_tasks - done_tasks)

        st.progress(done_tasks / total_tasks if total_tasks else 0)

        st.markdown("### 今日のタスクリスト")

        for _, row in today_tasks_df.iterrows():
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


with tab_material:
    st.subheader("📘 教材を登録")

    with st.form("add_material_form"):
        subject = st.text_input("科目", placeholder="例：憲法")
        material_name = st.text_input("教材名", placeholder="例：憲法基礎問")
        total_questions = st.number_input("総問題数", min_value=1, step=1)
        target_date = st.date_input("目標完了日")

        study_days = st.multiselect(
            "この教材に触れる曜日",
            ["月", "火", "水", "木", "金", "土", "日"],
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
                    material_id,
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
                        next_question_id,
                        material_id,
                        i,
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
    st.markdown("### 登録済み教材")

    if materials_df.empty:
        st.info("まだ教材がありません。")
    else:
        for _, row in materials_df.iterrows():
            with st.container(border=True):
                st.markdown(f"**{row['subject']}｜{row['material_name']}**")
                st.caption(
                    f"総問題数：{row['total_questions']} / 目標：{row['target_date']} / 曜日：{row['study_days']}"
                )


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

                next_review_date = st.date_input(
                    "次回復習日",
                    value=date.today()
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
                            "round": round_num,
                            "issue": issue,
                            "tags": tags,
                            "user_note": user_note,
                            "difficulty": difficulty,
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
            for _, q in filtered_questions.head(100).iterrows():
                issue = safe_str(q.get("issue", ""))
                status = safe_str(q.get("status", ""))
                st.write(f"第{int(q['question_number'])}問　{status}　{issue}")


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


with st.expander("開発者用：データ確認"):
    st.markdown("### materials")
    st.dataframe(materials_df, use_container_width=True)

    st.markdown("### questions")
    st.dataframe(questions_df, use_container_width=True)

    st.markdown("### logs")
    st.dataframe(logs_df, use_container_width=True)

    st.markdown("### daily_tasks")
    st.dataframe(tasks_df, use_container_width=True)
