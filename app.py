import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, timedelta

st.set_page_config(
    page_title="Study Progress",
    page_icon="📚",
    layout="wide"
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


# =====================
# データ読み込み
# =====================

sheets = connect_sheets()

materials_df = load_sheet(sheets["materials"])
questions_df = load_sheet(sheets["questions"])
logs_df = load_sheet(sheets["logs"])
tasks_df = load_sheet(sheets["daily_tasks"])


# =====================
# 画面
# =====================

st.title("📚 Study Progress")
st.caption("問題単位で進捗・復習・翌日のタスクを管理するアプリ")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🏠 今日のタスク",
    "📘 教材登録",
    "📝 問題一覧・編集",
    "🌙 学習記録",
    "📊 進捗",
    "📁 データ確認"
])


# =====================
# 今日のタスク
# =====================

with tab1:
    st.subheader("🏠 今日やること")

    today = str(date.today())

    col1, col2 = st.columns([1, 2])

    with col1:
        if st.button("今日のタスクを自動生成", type="primary"):
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

                st.rerun()

    with col2:
        st.caption("復習・苦手問題・新規問題を自動で今日のタスクに入れます。")

    tasks_df = load_sheet(sheets["daily_tasks"])

    if tasks_df.empty:
        st.info("まだ今日のタスクはありません。")
    else:
        today_tasks = tasks_df[
            tasks_df["task_date"].astype(str) == today
        ].copy()

        if today_tasks.empty:
            st.info("今日のタスクはまだありません。上のボタンで作成できます。")
        else:
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

            st.markdown("### 今日のタスクリスト")

            for _, row in merged.iterrows():
                task_status = row.get("status_task", "未完了")
                question_status = row.get("status_question", "")

                with st.container(border=True):
                    st.markdown(
                        f"### {row['教材']}　第{int(row['question_number'])}問"
                    )

                    st.write(f"**種類：** {row.get('task_type', '')}")
                    st.write(f"**タスク状態：** {task_status}")

                    if question_status:
                        st.write(f"**問題状態：** {question_status}")

                    if str(row.get("issue", "")) != "":
                        st.write(f"**論点：** {row.get('issue', '')}")

                    if str(row.get("tags", "")) != "":
                        st.write(f"**タグ：** {row.get('tags', '')}")

                    if str(row.get("user_note", "")) != "":
                        st.write(f"**メモ：** {row.get('user_note', '')}")


# =====================
# 教材登録
# =====================

with tab2:
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

        submitted = st.form_submit_button("教材を登録して問題番号を自動生成")

        if submitted:
            if subject == "" or material_name == "":
                st.error("科目と教材名を入力してください。")
            elif len(study_days) == 0:
                st.error("少なくとも1つ曜日を選んでください。")
            else:
                material_id = next_id(materials_df, "material_id")

                material_row = [
                    material_id,
                    subject,
                    material_name,
                    int(total_questions),
                    str(target_date),
                    ",".join(study_days)
                ]

                sheets["materials"].append_row(material_row)

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
                    f"教材を登録し、第1問〜第{int(total_questions)}問を自動生成しました。"
                )
                st.rerun()

    st.divider()
    st.subheader("登録済み教材")

    if materials_df.empty:
        st.info("まだ教材が登録されていません。")
    else:
        st.dataframe(materials_df, use_container_width=True)


# =====================
# 問題一覧・編集
# =====================

with tab3:
    st.subheader("📝 問題一覧・編集")

    if materials_df.empty or questions_df.empty:
        st.info("先に教材を登録してください。")
    else:
        material_options = {
            f'{row["subject"]}｜{row["material_name"]}': row["material_id"]
            for _, row in materials_df.iterrows()
        }

        selected_material_label = st.selectbox(
            "教材を選択",
            list(material_options.keys())
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

        st.markdown("### 問題一覧")
        st.dataframe(filtered_questions, use_container_width=True)

        st.divider()
        st.markdown("### 問題詳細を編集")

        question_options = {
            f'第{int(row["question_number"])}問': row["question_id"]
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

        status_options = ["未着手", "学習中", "復習待ち", "苦手", "完了"]

        with st.form("edit_question_form"):
            current_status = selected_question.get("status", "未着手")

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
                value=str(selected_question.get("issue", "")),
                placeholder="例：政教分離、目的効果基準"
            )

            tags = st.text_input(
                "タグ・関連過去問",
                value=str(selected_question.get("tags", "")),
                placeholder="例：司法H15, 慶應2019"
            )

            user_note = st.text_area(
                "メモ",
                value=str(selected_question.get("user_note", "")),
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

            submitted = st.form_submit_button("問題情報を保存")

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
                    st.rerun()
                else:
                    st.error("更新対象の問題が見つかりませんでした。")


# =====================
# 学習記録
# =====================

with tab4:
    st.subheader("🌙 今日の学習記録")

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
            f'第{int(row["question_number"])}問｜論点:{row.get("issue", "")}': row["question_id"]
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

            submitted = st.form_submit_button("学習記録を保存")

            if submitted:
                log_id = next_id(logs_df, "log_id")

                log_row = [
                    log_id,
                    str(date.today()),
                    selected_question_id_log,
                    result,
                    difficulty,
                    int(study_minutes),
                    comment
                ]

                sheets["logs"].append_row(log_row)

                selected_q = questions_df[
                    questions_df["question_id"].astype(str) == str(selected_question_id_log)
                ].iloc[0]

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
                    selected_question_id_log,
                    {
                        "status": new_status,
                        "last_done_date": str(date.today()),
                        "next_review_date": str(next_review),
                        "difficulty": difficulty,
                        "round": current_round
                    }
                )

                st.success("学習記録を保存し、問題の状態も更新しました。")
                st.rerun()

    st.divider()
    st.subheader("最近の学習ログ")

    if logs_df.empty:
        st.info("まだ学習ログがありません。")
    else:
        st.dataframe(logs_df.tail(20), use_container_width=True)


# =====================
# 進捗
# =====================

with tab5:
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

            done = len(qs[
                qs["status"].astype(str).isin(["復習待ち", "苦手", "完了"])
            ])

            completed = len(qs[
                qs["status"].astype(str) == "完了"
            ])

            weak = len(qs[
                qs["status"].astype(str) == "苦手"
            ])

            progress = done / total if total > 0 else 0

            st.markdown(f"### {material['subject']}｜{material['material_name']}")

            c1, c2, c3, c4 = st.columns(4)

            c1.metric("総問題数", total)
            c2.metric("着手済み", done)
            c3.metric("完了", completed)
            c4.metric("苦手", weak)

            st.progress(progress)
            st.caption(f"着手率：{round(progress * 100, 1)}%")

            weak_qs = qs[qs["status"].astype(str) == "苦手"]

            if not weak_qs.empty:
                with st.expander("苦手問題を見る"):
                    st.dataframe(weak_qs, use_container_width=True)


# =====================
# データ確認
# =====================

with tab6:
    st.subheader("📁 データ確認")
    st.caption("アプリで管理しているデータを確認できます。")

    st.markdown("### 📘 materials")
    st.dataframe(materials_df, use_container_width=True)

    st.markdown("### 📝 questions")
    st.dataframe(questions_df, use_container_width=True)

    st.markdown("### 🌙 logs")
    st.dataframe(logs_df, use_container_width=True)

    st.markdown("### 📅 daily_tasks")
    st.dataframe(tasks_df, use_container_width=True)
