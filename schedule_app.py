"""
スケジュール管理アプリ
設置工事～納品までのプロジェクトスケジュール表
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta, date
import json
import os
import math
import time

# ページ設定
st.set_page_config(
    page_title="プロジェクト スケジュール管理",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ========================
# 認証ゲート（閲覧PW / 編集PW の2段階）
# ========================
# パスワードは st.secrets（.streamlit/secrets.toml または Streamlit Cloud の Secrets）から読む。
#   view_password : 閲覧専用でアクセスするためのパスワード（関係者に配布）
#   edit_password : 編集・保存までできるパスワード（自分だけが持つ）
# secrets が未設定の場合（＝ローカルで自分が使う想定）は認証なしでフル編集可能にフォールバックする。

def _get_secret(key):
    try:
        return st.secrets.get(key)
    except Exception:
        # secrets.toml が無いローカル環境では st.secrets アクセスで例外になることがある
        return None


def check_auth():
    """認証を行い、編集可否(can_edit)を返す。

    戻り値:
        True  … 編集モード（保存・編集可能）
        False … 閲覧専用モード（表示のみ）
    認証に失敗した場合はログイン画面を描画して st.stop() する。
    """
    view_pw = _get_secret("view_password")
    edit_pw = _get_secret("edit_password")

    # パスワードが1つも設定されていない → ローカル利用とみなし認証スキップ（フル編集）
    if not view_pw and not edit_pw:
        return True

    # すでに認証済みならそのモードを返す
    if st.session_state.get("auth_ok"):
        return st.session_state.get("can_edit", False)

    # ---- ログイン画面 ----
    st.title("🔒 スケジュール共有ページ")
    st.caption("関係者向けの共有ページです。配布されたパスワードを入力してください。")
    with st.form("login_form"):
        pw = st.text_input("パスワード", type="password")
        submitted = st.form_submit_button("ログイン")

    if submitted:
        if edit_pw and pw == edit_pw:
            st.session_state.auth_ok = True
            st.session_state.can_edit = True
            st.rerun()
        elif view_pw and pw == view_pw:
            st.session_state.auth_ok = True
            st.session_state.can_edit = False
            st.rerun()
        else:
            st.error("パスワードが違います。")

    # 未認証の間はここで停止（以降の描画・保存を一切行わない）
    st.stop()


# ========================
# デフォルトデータ定義
# ========================

DEFAULT_PROJECT_TITLE = "スピーカー納品プロジェクト スケジュール"
DEFAULT_CUSTOMER = "お客様名"

# 12月中旬納品 = 12/15 を基点に2週間ずつ逆算
# 工程7つ × 2週間 = 14週間前スタート
# 12/15 - 14週 = 約 9/8

DEFAULT_PHASES = [
    {
        "id": 1,
        "category": "弊社作業",
        "name": "部品手配",
        "weeks": 2,
        "color": "#4472C4",
        "note": ""
    },
    {
        "id": 2,
        "category": "弊社作業",
        "name": "1stサンプル組み立て",
        "weeks": 2,
        "color": "#4472C4",
        "note": ""
    },
    {
        "id": 3,
        "category": "弊社作業",
        "name": "評価",
        "weeks": 2,
        "color": "#70AD47",
        "note": ""
    },
    {
        "id": 4,
        "category": "弊社作業",
        "name": "調整",
        "weeks": 2,
        "color": "#70AD47",
        "note": ""
    },
    {
        "id": 5,
        "category": "弊社作業",
        "name": "量産サンプル 部品手配",
        "weeks": 2,
        "color": "#ED7D31",
        "note": ""
    },
    {
        "id": 6,
        "category": "弊社作業",
        "name": "量産サンプル 組み立て",
        "weeks": 2,
        "color": "#ED7D31",
        "note": ""
    },
    {
        "id": 7,
        "category": "納品",
        "name": "納品（スピーカー引き渡し）",
        "weeks": 2,
        "color": "#FF0000",
        "note": "12月中旬 顧客納品"
    },
]

# 顧客側マイルストーン
DEFAULT_MILESTONES = [
    {"name": "設置工事開始", "date": "2027-01-15", "color": "#7030A0"},
    {"name": "調整開始",     "date": "2027-02-01", "color": "#7030A0"},
    {"name": "納品・引き渡し", "date": "2027-02-25", "color": "#C00000"},
]

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "schedule_config.json")

# ========================
# 設定の保存・読み込み
# ========================

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "project_title": DEFAULT_PROJECT_TITLE,
        "customer": DEFAULT_CUSTOMER,
        "delivery_date": "2026-12-15",
        "phases": DEFAULT_PHASES,
        "milestones": DEFAULT_MILESTONES,
    }

def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

# ========================
# スケジュール計算
# ========================

def calc_schedule(phases, delivery_date_str):
    """納品日を基点に逆算してstart/end日付を付与"""
    delivery = datetime.strptime(delivery_date_str, "%Y-%m-%d")
    result = []
    current_end = delivery

    for phase in reversed(phases):
        weeks = phase["weeks"]
        end = current_end
        start = end - timedelta(weeks=weeks)
        result.insert(0, {
            **phase,
            "start": start,
            "end": end,
        })
        current_end = start

    return result


def _phase_min_weeks(phase):
    """工程の短縮下限（週）。未設定なら現在のweeks（＝短縮不可）とみなす。"""
    try:
        mw = int(phase.get("min_weeks", phase["weeks"]))
    except (TypeError, ValueError):
        mw = phase["weeks"]
    # 下限は1週以上、かつ現在のweeksを超えない
    return max(1, min(mw, phase["weeks"]))


def compress_phases(phases, overflow_weeks):
    """納品日超過分（overflow_weeks）を吸収するため、短縮余地のある工程を
    後工程から順に縮める。縮めた結果の週数リストと、縮めきれなかった残り週を返す。

    Returns:
        effective_weeks: list[int]  各工程の短縮後の週数
        reductions: list[dict]      縮めた工程の情報（index, name, from, to）
        remaining: int              吸収しきれなかった超過週（0なら完全に収まった）
    """
    effective = [p["weeks"] for p in phases]
    reductions = []
    remaining = max(0, int(overflow_weeks))

    if remaining <= 0:
        return effective, reductions, 0

    # 後工程（納品に近い側）から縮めていく
    for i in range(len(phases) - 1, -1, -1):
        if remaining <= 0:
            break
        slack = phases[i]["weeks"] - _phase_min_weeks(phases[i])
        if slack <= 0:
            continue
        cut = min(slack, remaining)
        effective[i] = phases[i]["weeks"] - cut
        remaining -= cut
        reductions.append({
            "index": i,
            "name": phases[i].get("name", f"工程{i+1}"),
            "from": phases[i]["weeks"],
            "to": effective[i],
            "cut": cut,
        })

    return effective, reductions, remaining


def _build_forward(phases, start_dt, effective_weeks):
    """開始日と各工程の実効週数からstart/endを割り当てる。"""
    result = []
    current_start = start_dt
    for phase, w in zip(phases, effective_weeks):
        start = current_start
        end = start + timedelta(weeks=w)
        result.append({
            **phase,
            "weeks": w,
            "orig_weeks": phase["weeks"],
            "start": start,
            "end": end,
        })
        current_start = end
    return result


def calc_schedule_forward(phases, start_date_str, target_delivery_str=None):
    """開始日を基点に順算してstart/end日付を付与。
    開始日が後ろ倒しになると、全工程がそのままスライドし納品日も後ろにずれる。

    target_delivery_str が与えられ、素直に積んだ納品日がそれを超える場合は、
    短縮余地（min_weeks）のある工程を自動で縮めて納品日に収めようとする。

    Returns:
        schedule: list[dict]
        info: dict  短縮に関する情報
              {"compressed": bool, "reductions": [...],
               "remaining_weeks": int, "target": datetime|None,
               "natural_end": datetime}
    """
    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")

    # まずは短縮なしで素直に積む
    natural = _build_forward(phases, start_dt, [p["weeks"] for p in phases])
    natural_end = natural[-1]["end"] if natural else start_dt

    info = {
        "compressed": False,
        "reductions": [],
        "remaining_weeks": 0,
        "target": None,
        "natural_end": natural_end,
    }

    if not target_delivery_str:
        return natural, info

    target = datetime.strptime(target_delivery_str, "%Y-%m-%d")
    info["target"] = target

    overflow_days = (natural_end - target).days
    if overflow_days <= 0:
        # 目標内に収まっている（短縮不要）
        return natural, info

    # 日数→週（切り上げ）で超過分を算出し、短縮を試みる
    overflow_weeks = (overflow_days + 6) // 7
    effective, reductions, remaining = compress_phases(phases, overflow_weeks)

    if reductions:
        schedule = _build_forward(phases, start_dt, effective)
        info["compressed"] = True
        info["reductions"] = reductions
        info["remaining_weeks"] = remaining
        return schedule, info

    # 縮める余地がない → 素直な積み上げのまま、超過を通知
    info["remaining_weeks"] = overflow_weeks
    return natural, info

# ========================
# Ganttチャート生成（カスタム）
# ========================

CATEGORY_COLORS = {
    "弊社作業": "#4472C4",
    "評価・調整": "#70AD47",
    "量産": "#ED7D31",
    "納品": "#C00000",
}

# 工程ごとの色（idベース）
PHASE_COLORS = [
    "#4472C4",  # 1 部品手配
    "#5B9BD5",  # 2 1stサンプル
    "#70AD47",  # 3 評価
    "#A9D18E",  # 4 調整
    "#ED7D31",  # 5 量産部品
    "#F4B183",  # 6 量産組み立て
    "#C00000",  # 7 納品
]

def get_phase_color(phase, idx):
    """工程の色を返す（configに色があればそれを使う）"""
    return phase.get("color") or PHASE_COLORS[idx % len(PHASE_COLORS)]

def make_week_ticks(start_dt, end_dt):
    """週の月曜日リストを生成"""
    ticks = []
    # 最初の月曜日に揃える
    d = start_dt - timedelta(days=start_dt.weekday())
    while d <= end_dt + timedelta(weeks=1):
        ticks.append(d)
        d += timedelta(weeks=1)
    return ticks

def make_gantt(schedule, milestones, view_mode="月単位"):
    if not schedule:
        return go.Figure()

    fig = go.Figure()

    n = len(schedule)
    n_ms = len(milestones) if milestones else 0

    # マイルストーンは1行にまとめて表示（日付テキスト無し、◆のみ）
    total_rows = n + (1 if n_ms > 0 else 0)
    ms_row_y = n  # マイルストーン行のY位置

    bar_height = 0.55

    # X軸の範囲
    x_min = schedule[0]["start"] - timedelta(days=7)
    x_max = schedule[-1]["end"] + timedelta(days=7)
    for ms in milestones:
        if ms.get("date"):
            try:
                ms_dt = datetime.strptime(ms["date"], "%Y-%m-%d") + timedelta(days=14)
                if ms_dt > x_max:
                    x_max = ms_dt
            except Exception:
                pass

    # ---- 月の背景色（交互） ----
    current = date(x_min.year, x_min.month, 1)
    end_month = date(x_max.year, x_max.month, 1)
    alt = 0
    while current <= end_month:
        if current.month == 12:
            next_m = date(current.year + 1, 1, 1)
        else:
            next_m = date(current.year, current.month + 1, 1)

        fill_color = "rgba(235,240,255,0.4)" if alt % 2 == 0 else "rgba(255,255,255,0)"
        fig.add_shape(
            type="rect",
            x0=datetime(current.year, current.month, current.day),
            x1=datetime(next_m.year, next_m.month, next_m.day),
            y0=-0.8,
            y1=total_rows - 0.3,
            fillcolor=fill_color,
            line_width=0,
            layer="below",
        )
        alt += 1
        current = next_m

    # ---- マイルストーン行と工程行の区切り線 ----
    if n_ms > 0:
        sep_y = n - 0.5
        fig.add_shape(
            type="line",
            x0=x_min, x1=x_max,
            y0=sep_y, y1=sep_y,
            line=dict(color="rgba(120,120,120,0.4)", width=1, dash="solid"),
            layer="below",
        )

    # ---- 週グリッド線 ----
    week_ticks = make_week_ticks(x_min, x_max)
    for wt in week_ticks:
        fig.add_shape(
            type="line",
            x0=wt, x1=wt,
            y0=-0.8, y1=total_rows - 0.3,
            line=dict(color="rgba(180,180,180,0.35)", width=0.8, dash="dot"),
            layer="below",
        )

    # ---- ガントバー ----
    for idx, item in enumerate(schedule):
        color = get_phase_color(item, idx)
        y_pos = n - 1 - idx  # 上から順に並べる（0=最下、n-1=最上の工程行）

        start_dt = item["start"]
        end_dt   = item["end"]
        duration_days = (end_dt - start_dt).days

        # バー本体（shape）
        fig.add_shape(
            type="rect",
            x0=start_dt,
            x1=end_dt,
            y0=y_pos - bar_height / 2,
            y1=y_pos + bar_height / 2,
            fillcolor=color,
            line=dict(color="rgba(255,255,255,0.8)", width=1),
            layer="above",
        )

        # バーの右端に日付を小さく表示
        fig.add_annotation(
            x=end_dt,
            y=y_pos,
            text=f"{end_dt.strftime('%m/%d')}",
            showarrow=False,
            font=dict(color="rgba(80,80,80,0.8)", size=9, family="Meiryo, sans-serif"),
            xanchor="left",
            yanchor="middle",
            xshift=4,
        )

        # ホバー用の透明なバー
        hover_text = (
            f"<b>{item['name']}</b><br>"
            f"開始: {start_dt.strftime('%Y/%m/%d')}<br>"
            f"終了: {end_dt.strftime('%Y/%m/%d')}<br>"
            f"期間: {item['weeks']} 週間 ({duration_days} 日)"
        )
        if item.get("note"):
            hover_text += f"<br>備考: {item['note']}"

        fig.add_trace(go.Scatter(
            x=[start_dt, end_dt, end_dt, start_dt, start_dt],
            y=[
                y_pos - bar_height / 2,
                y_pos - bar_height / 2,
                y_pos + bar_height / 2,
                y_pos + bar_height / 2,
                y_pos - bar_height / 2,
            ],
            fill="toself",
            fillcolor="rgba(0,0,0,0)",
            line=dict(color="rgba(0,0,0,0)"),
            hoverinfo="text",
            hovertext=hover_text,
            name=item["name"],
            showlegend=False,
            mode="lines",
        ))

    # ---- マイルストーン（1行に◆マーカー＋名前テキスト、日付なし）----
    for ms_idx, ms in enumerate(milestones):
        try:
            ms_dt = datetime.strptime(ms["date"], "%Y-%m-%d")
            ms_color = ms.get("color", "#7030A0")

            # 縦線（チャート全高を通す）
            fig.add_shape(
                type="line",
                x0=ms_dt, x1=ms_dt,
                y0=-0.8, y1=total_rows - 0.3,
                line=dict(color=ms_color, width=2, dash="dash"),
            )

            # ◆マーカー＋名前テキスト（日付なし）をMS行に配置
            fig.add_trace(go.Scatter(
                x=[ms_dt],
                y=[ms_row_y],
                mode="markers+text",
                marker=dict(symbol="diamond", size=10, color=ms_color),
                text=[ms["name"]],
                textposition="top center",
                textfont=dict(color=ms_color, size=8, family="Meiryo, sans-serif"),
                hovertext=f"<b>{ms['name']}</b><br>{ms_dt.strftime('%Y/%m/%d')}",
                hoverinfo="text",
                showlegend=False,
                cliponaxis=False,
            ))
        except Exception:
            pass

    # ---- 今日の線 ----
    today = datetime.today()
    if x_min <= today <= x_max:
        fig.add_shape(
            type="line",
            x0=today, x1=today,
            y0=-0.8, y1=total_rows - 0.3,
            line=dict(color="rgba(255,80,80,0.6)", width=1.5, dash="dot"),
        )
        fig.add_annotation(
            x=today,
            y=-0.7,
            text=f"▲Today ({today.strftime('%m/%d')})",
            showarrow=False,
            yanchor="top",
            font=dict(color="rgba(200,50,50,0.8)", size=9),
        )

    # ---- Y軸ラベル ----
    ytick_vals = list(range(n))
    ytick_text = [schedule[n - 1 - i]["name"] for i in range(n)]
    # マイルストーン行（1行）
    if n_ms > 0:
        ytick_vals.append(ms_row_y)
        ytick_text.append("【顧客側目標】")

    # ---- 表示粒度に応じた目盛り設定 ----
    WEEK_MS = 7 * 24 * 60 * 60 * 1000
    DAY2_MS = 2 * 24 * 60 * 60 * 1000

    if view_mode == "週単位":
        major_dtick = WEEK_MS
        major_fmt   = "%m/%d"
        minor_dtick = DAY2_MS
    elif view_mode == "2週単位":
        major_dtick = 2 * WEEK_MS
        major_fmt   = "%m/%d"
        minor_dtick = WEEK_MS
    else:  # 月単位
        major_dtick = "M1"
        major_fmt   = "%Y年%m月"
        minor_dtick = WEEK_MS

    # ---- レイアウト ----
    fig.update_layout(
        height=max(400, total_rows * 58 + 120),
        margin=dict(l=10, r=30, t=50, b=50),
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Meiryo, sans-serif", size=12),
        showlegend=False,
        xaxis=dict(
            type="date",
            range=[x_min, x_max],
            tickformat=major_fmt,
            dtick=major_dtick,
            ticklabelmode="period",
            showgrid=True,
            gridcolor="rgba(150,150,150,0.3)",
            gridwidth=1,
            title="",
            side="top",
            rangeselector=dict(
                buttons=[
                    dict(count=1, label="1M", step="month", stepmode="backward"),
                    dict(count=3, label="3M", step="month", stepmode="backward"),
                    dict(count=6, label="6M", step="month", stepmode="backward"),
                    dict(step="all", label="全期間"),
                ],
                font=dict(size=11),
                bgcolor="#f0f0f0",
                activecolor="#4472C4",
                x=0.5, xanchor="center",
                y=1.12,
            ),
            rangeslider=dict(
                visible=True,
                thickness=0.06,
                bgcolor="#f5f5f5",
            ),
            minor=dict(
                dtick=minor_dtick,
                ticklen=3,
                tickcolor="rgba(150,150,150,0.5)",
                showgrid=True,
                gridcolor="rgba(200,200,200,0.3)",
                gridwidth=0.8,
            ),
            ticklen=6,
            tickcolor="rgba(80,80,80,0.6)",
            tickfont=dict(size=10),
        ),
        yaxis=dict(
            tickvals=ytick_vals,
            ticktext=ytick_text,
            range=[-0.8, total_rows + 0.3],
            showgrid=False,
            zeroline=False,
            tickfont=dict(size=11),
            automargin=True,
        ),
        hoverlabel=dict(
            bgcolor="white",
            font_size=12,
            font_family="Meiryo, sans-serif",
        ),
    )

    return fig

# ========================
# メインUI
# ========================

def main():
    # 認証（can_edit=False なら閲覧専用モード）
    can_edit = check_auth()

    cfg = load_config()

    # 閲覧専用モードの案内バナー
    if not can_edit:
        st.info("👀 閲覧専用モードで表示しています。編集・保存はできません。", icon="🔒")

    # ---- サイドバー：設定パネル ----
    with st.sidebar:
        st.header("⚙️ 設定")
        if not can_edit:
            st.caption("🔒 閲覧専用モードのため、設定の変更はできません。")

        new_title = st.text_input("プロジェクト名", value=cfg["project_title"], disabled=not can_edit)
        new_customer = st.text_input("顧客名", value=cfg["customer"], disabled=not can_edit)

        st.subheader("📅 基点の設定")
        schedule_mode = st.radio(
            "計算の基点",
            options=["逆算（納品日から）", "順算（開始日から）"],
            index=1 if cfg.get("schedule_mode") == "forward" else 0,
            disabled=not can_edit,
            help=(
                "逆算：納品日を固定し、そこから各工程をさかのぼって開始日を決めます。\n"
                "順算：開始日を固定し、そこから各工程を積み上げて納品日を決めます。"
                "開始日が後ろ倒しになると全工程がそのままスライドします。"
            ),
        )
        is_forward = schedule_mode.startswith("順算")

        if is_forward:
            start_date_input = st.date_input(
                "着手（開始）日",
                value=datetime.strptime(
                    cfg.get("start_date", cfg["delivery_date"]), "%Y-%m-%d"
                ).date(),
                disabled=not can_edit,
                help="ここを後ろ倒しにすると、以降の全工程と納品日が同じだけスライドします。",
            )
            # 逆算用の納品日は保持（モード切替時に失わないため）
            delivery_date = datetime.strptime(cfg["delivery_date"], "%Y-%m-%d").date()
        else:
            delivery_date = st.date_input(
                "スピーカー納品日",
                value=datetime.strptime(cfg["delivery_date"], "%Y-%m-%d").date(),
                disabled=not can_edit,
            )
            start_date_input = datetime.strptime(
                cfg.get("start_date", cfg["delivery_date"]), "%Y-%m-%d"
            ).date()

        st.markdown("---")
        st.subheader("🔧 工程設定（週数）")
        st.caption("工程名・標準週数(W)・最短週数(最短)の変更、追加・削除・順序入替ができます")
        st.caption("💡 最短 < W にすると、順算で納品日を超えたとき自動でその工程を縮めます（最短=Wなら短縮不可）")

        # session_stateにphasesを保持（追加/削除/移動の即時反映用）
        if "phases" not in st.session_state:
            st.session_state.phases = [p.copy() for p in cfg["phases"]]

        phases = st.session_state.phases

        # 見出し行
        head_cols = st.columns([3, 1, 1, 0.6, 0.6, 0.6])
        head_cols[0].caption("工程名")
        head_cols[1].caption("W")
        head_cols[2].caption("最短")

        # --- 各工程の表示 ---
        to_delete = None
        to_move_up = None
        to_move_down = None

        for i, phase in enumerate(phases):
            row_cols = st.columns([3, 1, 1, 0.6, 0.6, 0.6])
            with row_cols[0]:
                phases[i]["name"] = st.text_input(
                    "名",
                    value=phase["name"],
                    key=f"pname_{i}",
                    label_visibility="collapsed",
                    disabled=not can_edit,
                )
            with row_cols[1]:
                phases[i]["weeks"] = st.number_input(
                    "W",
                    min_value=1,
                    max_value=52,
                    value=phase["weeks"],
                    key=f"pweeks_{i}",
                    label_visibility="collapsed",
                    disabled=not can_edit,
                )
            with row_cols[2]:
                # 最短週数：デフォルトは標準週数（＝短縮不可）
                _min_default = int(phase.get("min_weeks", phase["weeks"]))
                _min_default = max(1, min(_min_default, phases[i]["weeks"]))
                phases[i]["min_weeks"] = st.number_input(
                    "最短",
                    min_value=1,
                    max_value=int(phases[i]["weeks"]),
                    value=_min_default,
                    key=f"pmin_{i}",
                    label_visibility="collapsed",
                    disabled=not can_edit,
                )
            with row_cols[3]:
                if st.button("▲", key=f"up_{i}", disabled=(i == 0) or not can_edit):
                    to_move_up = i
            with row_cols[4]:
                if st.button("▼", key=f"dn_{i}", disabled=(i == len(phases) - 1) or not can_edit):
                    to_move_down = i
            with row_cols[5]:
                if st.button("✕", key=f"del_{i}", disabled=not can_edit):
                    to_delete = i

        # 移動・削除の処理
        if to_move_up is not None and to_move_up > 0:
            phases[to_move_up], phases[to_move_up - 1] = phases[to_move_up - 1], phases[to_move_up]
            st.rerun()
        if to_move_down is not None and to_move_down < len(phases) - 1:
            phases[to_move_down], phases[to_move_down + 1] = phases[to_move_down + 1], phases[to_move_down]
            st.rerun()
        if to_delete is not None:
            phases.pop(to_delete)
            st.rerun()

        # 追加ボタン
        if st.button("➕ 工程を追加", use_container_width=True, disabled=not can_edit):
            new_id = max((p.get("id", 0) for p in phases), default=0) + 1
            phases.append({
                "id": new_id,
                "category": "弊社作業",
                "name": "新しい工程",
                "weeks": 2,
                "min_weeks": 2,
                "color": PHASE_COLORS[new_id % len(PHASE_COLORS)],
                "note": "",
            })
            st.rerun()

        # IDの振り直し（保存用）
        updated_phases = []
        for i, p in enumerate(phases):
            _w = int(p["weeks"])
            _mw = int(p.get("min_weeks", _w))
            _mw = max(1, min(_mw, _w))
            updated_phases.append({
                "id": i + 1,
                "category": p.get("category", "弊社作業"),
                "name": p["name"],
                "weeks": _w,
                "min_weeks": _mw,
                "color": p.get("color", PHASE_COLORS[i % len(PHASE_COLORS)]),
                "note": p.get("note", ""),
            })

        st.markdown("---")
        st.subheader("🏁 顧客側マイルストーン")
        updated_milestones = []
        for i, ms in enumerate(cfg["milestones"]):
            ms_cols = st.columns([2, 2])
            with ms_cols[0]:
                ms_name = st.text_input(
                    "名称",
                    value=ms["name"],
                    key=f"ms_name_{i}",
                    label_visibility="collapsed",
                    disabled=not can_edit,
                )
            with ms_cols[1]:
                ms_date = st.date_input(
                    "日付",
                    value=datetime.strptime(ms["date"], "%Y-%m-%d").date(),
                    key=f"ms_date_{i}",
                    label_visibility="collapsed",
                    disabled=not can_edit,
                )
            updated_milestones.append({
                **ms,
                "name": ms_name,
                "date": ms_date.strftime("%Y-%m-%d")
            })

        st.markdown("---")
        # 保存ロジック：手動保存ボタン + 15分おき自動保存
        AUTOSAVE_INTERVAL = 15 * 60  # 15分（秒）

        if "last_save_time" not in st.session_state:
            st.session_state.last_save_time = time.time()

        new_cfg = {
            "project_title": new_title,
            "customer": new_customer,
            "schedule_mode": "forward" if is_forward else "backward",
            "delivery_date": delivery_date.strftime("%Y-%m-%d"),
            "start_date": start_date_input.strftime("%Y-%m-%d"),
            "phases": updated_phases,
            "milestones": updated_milestones,
        }

        elapsed = time.time() - st.session_state.last_save_time
        auto_saved = False
        # 閲覧専用モードでは自動保存しない
        if can_edit and elapsed >= AUTOSAVE_INTERVAL:
            save_config(new_cfg)
            st.session_state.last_save_time = time.time()
            auto_saved = True

        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 保存", use_container_width=True, disabled=not can_edit):
                save_config(new_cfg)
                st.session_state.last_save_time = time.time()
                st.success("保存しました")
        with col2:
            if st.button("↩️ リセット", use_container_width=True, disabled=not can_edit):
                if os.path.exists(CONFIG_FILE):
                    os.remove(CONFIG_FILE)
                if "phases" in st.session_state:
                    del st.session_state.phases
                st.success("リセットしました")
                st.rerun()

        # 保存状態の表示
        if not can_edit:
            st.caption("🔒 閲覧専用モードのため保存されません。")
        else:
            mins_since_save = int(elapsed // 60) if not auto_saved else 0
            if auto_saved:
                st.caption("✅ 自動保存しました")
            else:
                st.caption(f"💡 最終保存から {mins_since_save}分経過（15分で自動保存）")

    # ---- メインエリア ----
    # タイトル
    st.title(f"📅 {cfg['project_title']}")
    st.markdown(f"**顧客：** {cfg['customer']}　　**作成日：** {datetime.today().strftime('%Y年%m月%d日')}")
    st.markdown("---")

    # スケジュール計算（サイドバーの現在の編集状態を反映）
    current_phases = updated_phases if updated_phases else cfg["phases"]
    compress_info = None
    if is_forward:
        # 順算：目標納品日を超えたら短縮余地のある工程を自動で縮める
        schedule, compress_info = calc_schedule_forward(
            current_phases,
            new_cfg["start_date"],
            target_delivery_str=new_cfg["delivery_date"],
        )
    else:
        schedule = calc_schedule(current_phases, new_cfg["delivery_date"])

    # ---- サマリーカード ----
    start_date = schedule[0]["start"]
    end_date   = schedule[-1]["end"]
    total_weeks = sum(item["weeks"] for item in schedule)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🚀 開始予定", start_date.strftime("%Y/%m/%d"))
    col2.metric("📦 納品予定", end_date.strftime("%Y/%m/%d"))
    col3.metric("📋 総工程数", f"{len(schedule)} 工程")
    col4.metric("⏱️ 総所要期間", f"{total_weeks} 週間")

    # ---- 順算モードの短縮・超過通知 ----
    if is_forward and compress_info is not None:
        target = compress_info.get("target")
        if compress_info.get("compressed"):
            lines = [
                f"- {r['name']}：{r['from']}週 → {r['to']}週（{r['cut']}週短縮）"
                for r in compress_info["reductions"]
            ]
            msg = "⚙️ 納品日に収めるため、短縮可能な工程を自動で縮めました：\n" + "\n".join(lines)
            if compress_info.get("remaining_weeks", 0) > 0:
                st.warning(
                    msg
                    + f"\n\n⚠️ ただし短縮余地が足りず、まだ約 {compress_info['remaining_weeks']}週 超過しています。"
                    + "納品日の見直しか、工程の最短週数の再検討が必要です。"
                )
            else:
                st.success(msg + f"\n\n✅ 目標納品日（{target.strftime('%Y/%m/%d') if target else ''}）に収まりました。")
        elif compress_info.get("remaining_weeks", 0) > 0:
            st.warning(
                f"⚠️ 開始日が後ろ倒しになり、納品予定（{end_date.strftime('%Y/%m/%d')}）が"
                f"目標納品日（{target.strftime('%Y/%m/%d') if target else ''}）を約 "
                f"{compress_info['remaining_weeks']}週 超過しています。\n\n"
                "短縮したい工程の「最短」週数を標準より小さく設定すると、自動で縮めて収めようとします。"
            )

    st.markdown("---")

    # ---- Ganttチャート ----
    st.subheader("📊 ガントチャート")

    # 表示粒度コントロール
    view_col1, view_col2, view_col3 = st.columns([2, 2, 4])
    with view_col1:
        view_mode = st.radio(
            "表示粒度",
            ["月単位", "2週単位", "週単位"],
            horizontal=True,
            label_visibility="collapsed",
        )
    with view_col2:
        show_milestone = st.checkbox("マイルストーン表示", value=True)

    milestones = cfg["milestones"] if show_milestone else []
    fig = make_gantt(schedule, milestones, view_mode)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": True, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})

    st.markdown("---")

    # ---- スケジュール詳細表 ----
    st.subheader("📋 工程詳細")

    table_data = []
    for i, item in enumerate(schedule, 1):
        orig_w = item.get("orig_weeks", item["weeks"])
        if orig_w != item["weeks"]:
            duration_txt = f"{item['weeks']} 週間（短縮 ←{orig_w}週）"
        else:
            duration_txt = f"{item['weeks']} 週間"
        table_data.append({
            "No.": i,
            "カテゴリ": item["category"],
            "工程名": item["name"],
            "開始日": item["start"].strftime("%Y/%m/%d"),
            "終了日": item["end"].strftime("%Y/%m/%d"),
            "所要期間": duration_txt,
            "備考": item.get("note", ""),
        })

    df = pd.DataFrame(table_data)
    # 全行を縦スクロールなしで表示するため、行数に応じて高さを計算
    # （ヘッダー約38px + 1行あたり約35px + 余白）
    table_height = 38 + len(df) * 35 + 3
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=table_height,
        column_config={
            "No.":     st.column_config.NumberColumn(width="small"),
            "カテゴリ": st.column_config.TextColumn(width="medium"),
            "工程名":  st.column_config.TextColumn(width="large"),
            "開始日":  st.column_config.TextColumn(width="medium"),
            "終了日":  st.column_config.TextColumn(width="medium"),
            "所要期間": st.column_config.TextColumn(width="small"),
            "備考":    st.column_config.TextColumn(width="large"),
        }
    )

    st.markdown("---")

    # ---- マイルストーン表 ----
    st.subheader("🏁 顧客側マイルストーン")

    ms_data = []
    for ms in cfg["milestones"]:
        try:
            ms_dt = datetime.strptime(ms["date"], "%Y-%m-%d")
            ms_data.append({
                "マイルストーン": ms["name"],
                "目標日": ms_dt.strftime("%Y/%m/%d"),
                "備考": ""
            })
        except Exception:
            pass

    df_ms = pd.DataFrame(ms_data)
    st.dataframe(df_ms, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ---- BOM（部品構成表）----
    st.subheader("🔩 BOM（部品構成表）")

    # 参考画像（見出しのすぐ下、テーブルの上に小さく表示）
    IMAGES_DIR = os.path.join(os.path.dirname(__file__), "schedule_images")
    os.makedirs(IMAGES_DIR, exist_ok=True)

    saved_images = sorted([
        f for f in os.listdir(IMAGES_DIR)
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"))
    ]) if os.path.exists(IMAGES_DIR) else []

    if saved_images:
        cols = st.columns(min(len(saved_images), 4))
        for i, img_name in enumerate(saved_images):
            img_path = os.path.join(IMAGES_DIR, img_name)
            with cols[i % 4]:
                st.image(img_path, caption=img_name, width=150)
                if st.button("✕", key=f"del_img_{img_name}", disabled=not can_edit):
                    os.remove(img_path)
                    st.rerun()

    uploaded_files = st.file_uploader(
        "📎 参考画像を追加",
        type=["png", "jpg", "jpeg", "gif", "bmp", "webp"],
        accept_multiple_files=True,
        disabled=not can_edit,
        key="image_uploader",
    )
    if uploaded_files and can_edit:
        for uf in uploaded_files:
            save_path = os.path.join(IMAGES_DIR, uf.name)
            with open(save_path, "wb") as f:
                f.write(uf.getbuffer())
        st.rerun()

    BOM_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "bom_config.json")

    # 見積書PDF（部品ごとに複数添付可）の保存先
    QUOTES_DIR = os.path.join(os.path.dirname(__file__), "schedule_bom_quotes")
    QUOTES_INDEX_FILE = os.path.join(os.path.dirname(__file__), "bom_quotes.json")
    os.makedirs(QUOTES_DIR, exist_ok=True)

    def load_quotes_index():
        """{部品名: [保存ファイル名, ...]} の辞書を返す"""
        if os.path.exists(QUOTES_INDEX_FILE):
            try:
                with open(QUOTES_INDEX_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception:
                pass
        return {}

    def save_quotes_index(index):
        with open(QUOTES_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    def _sanitize_filename(name):
        """保存用に安全なファイル名へ変換"""
        import re as _re
        name = os.path.basename(name)
        return _re.sub(r'[\\/:*?"<>|]', "_", name)

    # デフォルトBOMデータ
    # 単重(g)は分かる範囲のみ初期値を設定（0は未入力＝後から手入力）
    #   FE126NV2 : メーカー公称 約1.0kg → 1000g
    #   ネジ・ナット・ワッシャー類 : 一般的なスチール規格品の概算値
    # 「数量」= 発注数（まとめ買いのキリの良い数、金額計算用）
    # 「員数/set」= スピーカー1セットに実際使う個数（重量計算用）
    #   ネジ類の員数は締結点数から推定した目安。実際の点数に合わせて手入力してください。
    DEFAULT_BOM = [
        {"部品名": "FE126NV2",                    "発注中": False, "在庫あり": False, "数量": 24,  "在庫数": 0, "員数/set": 1, "単価": 0, "合計(円)": 0, "単重(g)": 1000, "購入先": "FOSTEX", "URL": ""},
        {"部品名": "BRAKET",                      "発注中": False, "在庫あり": False, "数量": 24,  "在庫数": 0, "員数/set": 1, "単価": 0, "合計(円)": 0, "単重(g)": 0,    "購入先": "多摩プラスチック", "URL": ""},
        {"部品名": "COLLAR_for FE126-A",          "発注中": False, "在庫あり": False, "数量": 24,  "在庫数": 0, "員数/set": 1, "単価": 0, "合計(円)": 0, "単重(g)": 0,    "購入先": "多摩プラスチック", "URL": ""},
        {"部品名": "COLLAR_for FE126-B",          "発注中": False, "在庫あり": False, "数量": 24,  "在庫数": 0, "員数/set": 1, "単価": 0, "合計(円)": 0, "単重(g)": 0,    "購入先": "多摩プラスチック", "URL": ""},
        {"部品名": "M4x40 ネジ(SCB4-40)",         "発注中": False, "在庫あり": False, "数量": 100, "在庫数": 0, "員数/set": 4, "単価": 0, "合計(円)": 0, "単重(g)": 4,    "購入先": "MISUMI", "URL": ""},
        {"部品名": "M4ナット(ゆるみ止め) E-PACK-GLNUTS4", "発注中": False, "在庫あり": False, "数量": 100, "在庫数": 0, "員数/set": 4, "単価": 0, "合計(円)": 0, "単重(g)": 1,    "購入先": "MISUMI", "URL": ""},
        {"部品名": "M4平ワッシャー 36-280",       "発注中": False, "在庫あり": False, "数量": 100, "在庫数": 0, "員数/set": 4, "単価": 0, "合計(円)": 0, "単重(g)": 1,    "購入先": "MISUMI", "URL": ""},
        {"部品名": "M6ナット",                    "発注中": False, "在庫あり": False, "数量": 48,  "在庫数": 0, "員数/set": 2, "単価": 0, "合計(円)": 0, "単重(g)": 3,    "購入先": "MISUMI", "URL": ""},
        {"部品名": "2Pプッシュターミナル",        "発注中": False, "在庫あり": False, "数量": 24,  "在庫数": 0, "員数/set": 1, "単価": 0, "合計(円)": 0, "単重(g)": 0,    "購入先": "MISUMI", "URL": ""},
        {"部品名": "平行ケーブル20cm",            "発注中": False, "在庫あり": False, "数量": 24,  "在庫数": 0, "員数/set": 1, "単価": 0, "合計(円)": 0, "単重(g)": 0,    "購入先": "未定(MARUETU)", "URL": ""},
        {"部品名": "Φ3x12mmタップスクリュー",    "発注中": False, "在庫あり": False, "数量": 48,  "在庫数": 0, "員数/set": 2, "単価": 0, "合計(円)": 0, "単重(g)": 2,    "購入先": "MISUMI", "URL": ""},
        {"部品名": "ケーブル φ2.6x20AWG",        "発注中": False, "在庫あり": False, "数量": 10,  "在庫数": 0, "員数/set": 0, "単価": 0, "合計(円)": 0, "単重(g)": 0,    "購入先": "MISUMI", "URL": ""},
        {"部品名": "落下防止ワイヤー30cm",        "発注中": False, "在庫あり": False, "数量": 24,  "在庫数": 0, "員数/set": 1, "単価": 0, "合計(円)": 0, "単重(g)": 0,    "購入先": "MISUMI", "URL": ""},
    ]

    def load_bom():
        if os.path.exists(BOM_CONFIG_FILE):
            try:
                with open(BOM_CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return DEFAULT_BOM

    def save_bom(bom_data):
        with open(BOM_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(bom_data, f, ensure_ascii=False, indent=2)

    bom_data = load_bom()
    df_bom = pd.DataFrame(bom_data)

    # 合計(円)・URL・発注中・在庫あり列がない場合は追加
    if "合計(円)" not in df_bom.columns:
        df_bom["合計(円)"] = 0
    if "URL" not in df_bom.columns:
        df_bom["URL"] = ""
    if "発注中" not in df_bom.columns:
        df_bom["発注中"] = False
    if "在庫あり" not in df_bom.columns:
        df_bom["在庫あり"] = False
    if "単重(g)" not in df_bom.columns:
        df_bom["単重(g)"] = 0
    if "員数/set" not in df_bom.columns:
        df_bom["員数/set"] = 0
    if "在庫数" not in df_bom.columns:
        df_bom["在庫数"] = 0

    # 税込/税抜 切替チェックボックス
    TAX_RATE = 0.10
    tax_col1, tax_col2 = st.columns([2, 6])
    with tax_col1:
        show_tax_excluded = st.checkbox("税抜表示に切替", value=False)

    tax_label = "税抜" if show_tax_excluded else "税込"
    st.caption(f"📌 現在の表示：**{tax_label}** ／ 単価入力で合計を自動計算。単価不明なら合計(円)に直接入力。")

    # 事前に合計計算（単価>0なら自動計算、0なら手入力値を維持）
    qty = df_bom["数量"].fillna(0).astype(int)
    price = df_bom["単価"].fillna(0).astype(int)
    manual_total = df_bom["合計(円)"].fillna(0).astype(int)
    df_bom["合計(円)"] = (qty * price).where(price > 0, manual_total)

    # 重量計算（1セット重量 = 員数/set × 単重(g)）
    # 単重は小数を許容（例: 1.5g）
    unit_weight = df_bom["単重(g)"].fillna(0).astype(float)
    per_set_qty = df_bom["員数/set"].fillna(0).astype(float)
    df_bom["1set重量(g)"] = (per_set_qty * unit_weight).round(1)

    # 表示用データ（税抜時は ÷ 1.1）
    display_bom = df_bom.copy()
    if show_tax_excluded:
        display_bom["単価"] = (display_bom["単価"].fillna(0) / (1 + TAX_RATE)).astype(int)
        display_bom["合計(円)"] = (display_bom["合計(円)"].fillna(0) / (1 + TAX_RATE)).astype(int)

    price_col_name = f"単価({tax_label})"
    total_col_name = f"合計({tax_label})"

    # 重量は税と無関係なので display_bom 側にもコピー（税抜切替の影響を受けない）
    display_bom["員数/set"] = df_bom["員数/set"].fillna(0).astype(int)
    display_bom["単重(g)"] = df_bom["単重(g)"].fillna(0).astype(float)
    display_bom["1set重量(g)"] = df_bom["1set重量(g)"].fillna(0).astype(float)
    # 在庫数も税と無関係なのでそのままコピー
    display_bom["在庫数"] = df_bom["在庫数"].fillna(0).astype(int)

    # 見積書PDFの添付状況を読み込み、部品ごとの添付件数を参照列として付与
    # 列名を表示用に変更（列順は固定。発注中・在庫ありは一番右）
    # ※ 1set重量(g)はdata_editorだと編集値がリアルタイム反映されないため編集表からは外し、
    #    編集後に再計算した結果を別途表示する
    # ※ 見積PDFの件数は参照専用なので編集テーブルには入れず、表の下にサマリー表示する
    editor_df = display_bom[["部品名", "数量", "在庫数", "員数/set", "単重(g)", "単価", "合計(円)", "購入先", "URL", "発注中", "在庫あり"]].rename(
        columns={"単価": price_col_name, "合計(円)": total_col_name}
    )

    # 全行を内部スクロールなしで表示するための高さを計算
    #   行高 ≈ 35px、ヘッダ ≈ 38px、dynamic時の末尾追加行(+1)と余白を加味
    ROW_PX = 35
    HEADER_PX = 38
    n_rows = len(editor_df)
    editor_height = HEADER_PX + (n_rows + 1) * ROW_PX + 3

    # 1つの編集可能テーブルに全列表示
    edited_bom = st.data_editor(
        editor_df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic" if can_edit else "fixed",
        height=editor_height,
        disabled=not can_edit,
        column_config={
            "部品名":       st.column_config.TextColumn("部品名", width="large"),
            "発注中":       st.column_config.CheckboxColumn("発注中", width="small", default=False),
            "在庫あり":     st.column_config.CheckboxColumn("在庫あり", width="small", default=False),
            "数量":         st.column_config.NumberColumn("数量(pcs)", min_value=0, step=1, width="small"),
            "在庫数":       st.column_config.NumberColumn("在庫数(pcs)", min_value=0, step=1, width="small",
                                                          help="現在の手持ち在庫数。発注要否の判断に使用"),
            price_col_name: st.column_config.NumberColumn(price_col_name, min_value=0, step=1, format="%d"),
            total_col_name: st.column_config.NumberColumn(total_col_name, min_value=0, step=1, format="%d",
                                                          help="単価入力時は自動計算。単価不明なら直接入力"),
            "員数/set":     st.column_config.NumberColumn("員数/set", min_value=0, step=1, width="small",
                                                          help="スピーカー1セットに実際使う個数（発注数とは別）。ネジ点数など実態に合わせて手入力"),
            "単重(g)":      st.column_config.NumberColumn("単重(g)", min_value=0.0, step=0.1, format="%.1f", width="small",
                                                          help="1個あたりの重量(g)。小数可（例:1.5）。分かる範囲で初期値済み、残りは手入力"),
            "購入先":       st.column_config.TextColumn("購入先", width="medium"),
            "URL":          st.column_config.LinkColumn("URL", width="medium", display_text="🔗 リンク"),
        },
        key="bom_editor",
    )

    # 見積PDFの添付件数サマリー（件数だけ・ファイル本体は読まないので軽量）
    _qidx = load_quotes_index()
    _attached = [(k, len(v)) for k, v in _qidx.items() if v]
    if _attached:
        _summary = "　".join(f"{name}: 📄×{cnt}" for name, cnt in _attached)
        st.caption(f"🧾 見積書PDF添付あり → {_summary}")

    # 総合計を表示
    if edited_bom is not None and not edited_bom.empty:
        # 編集結果を税込に戻して計算
        e_qty = edited_bom["数量"].fillna(0).astype(int)
        e_price_display = edited_bom[price_col_name].fillna(0).astype(int)
        e_manual_display = edited_bom[total_col_name].fillna(0).astype(int)

        # 税込に変換して保存用データを作成
        if show_tax_excluded:
            e_price_taxinc = (e_price_display * (1 + TAX_RATE)).round().astype(int)
            e_manual_taxinc = (e_manual_display * (1 + TAX_RATE)).round().astype(int)
        else:
            e_price_taxinc = e_price_display
            e_manual_taxinc = e_manual_display

        final_total_taxinc = (e_qty * e_price_taxinc).where(e_price_taxinc > 0, e_manual_taxinc)
        grand_total_taxinc = final_total_taxinc.sum()

        # 表示は現在の税込/税抜モード
        final_total_display = (e_qty * e_price_display).where(e_price_display > 0, e_manual_display)
        grand_total_display = final_total_display.sum()

        # 1セット重量の再計算（編集結果を反映）: 員数/set × 単重(g)
        e_per_set_qty = edited_bom["員数/set"].fillna(0).astype(float)
        e_unit_weight = edited_bom["単重(g)"].fillna(0).astype(float)
        e_set_weight = (e_per_set_qty * e_unit_weight)
        per_set_weight_g = float(e_set_weight.sum())

        wcol1, wcol2 = st.columns(2)
        with wcol1:
            st.markdown(f"### 💰 総合計（{tax_label}）：¥{grand_total_display:,.0f}")
            if show_tax_excluded:
                st.caption(f"※ 税込換算：¥{grand_total_taxinc:,.0f}")
        with wcol2:
            st.markdown(f"### ⚖️ 1セットあたり重量：{per_set_weight_g / 1000:,.3f} kg")
            st.caption(f"※ {per_set_weight_g:,.1f} g ／ 員数/set × 単重(g) の合計。単重・員数が未入力の部品は含まれません")

        # 部品ごとの1set重量内訳（編集値を反映した計算結果）
        with st.expander("⚖️ 1set重量の内訳を見る"):
            weight_breakdown = pd.DataFrame({
                "部品名": edited_bom["部品名"],
                "員数/set": e_per_set_qty.astype(int),
                "単重(g)": e_unit_weight.round(2),
                "1set重量(g)": e_set_weight.round(1),
            })
            st.dataframe(weight_breakdown, use_container_width=True, hide_index=True)

        # ---- 在庫状況ビュー（在庫数 < 必要数量 の行をグレーで強調）----
        # ※ st.data_editor は行の色付けに未対応のため、読み取り専用の確認表を併設
        e_stock = edited_bom["在庫数"].fillna(0).astype(int)
        shortage = (e_stock < e_qty)
        n_short = int(shortage.sum())

        status_df = pd.DataFrame({
            "部品名": edited_bom["部品名"],
            "必要数量": e_qty,
            "在庫数": e_stock,
            "不足数": (e_qty - e_stock).clip(lower=0),
            "状態": shortage.map(lambda s: "⚠️ 要発注" if s else "✅ 充足"),
        })

        def _highlight_shortage(row):
            # 在庫数が必要数量に達していない行を薄いグレーで塗る
            if row["在庫数"] < row["必要数量"]:
                return ["background-color: #e0e0e0; color: #555555"] * len(row)
            return [""] * len(row)

        st.markdown("##### 📦 在庫状況")
        if n_short > 0:
            st.caption(f"⚠️ 必要数量に達していない部品が {n_short} 件あります（グレー表示）")
        else:
            st.caption("✅ すべての部品が必要数量を満たしています")

        status_height = 38 + len(status_df) * 35 + 3
        st.dataframe(
            status_df.style.apply(_highlight_shortage, axis=1),
            use_container_width=True,
            hide_index=True,
            height=status_height,
        )

        # 保存（15分間隔自動 + 手動ボタン）- 常に税込で保存
        if "last_bom_save_time" not in st.session_state:
            st.session_state.last_bom_save_time = time.time()

        bom_elapsed = time.time() - st.session_state.last_bom_save_time

        # 保存用データ（税込に変換して保存）
        save_df = pd.DataFrame({
            "部品名": edited_bom["部品名"],
            "発注中": edited_bom["発注中"].fillna(False).astype(bool),
            "在庫あり": edited_bom["在庫あり"].fillna(False).astype(bool),
            "数量": e_qty,
            "在庫数": edited_bom["在庫数"].fillna(0).astype(int),
            "員数/set": e_per_set_qty.round().astype(int),
            "単価": e_price_taxinc,
            "合計(円)": final_total_taxinc,
            "単重(g)": e_unit_weight.round(2),
            "購入先": edited_bom["購入先"],
            "URL": edited_bom["URL"],
        })
        bom_save_data = save_df.to_dict(orient="records")

        bom_auto_saved = False
        # 閲覧専用モードでは自動保存しない
        if can_edit and bom_elapsed >= AUTOSAVE_INTERVAL:
            save_bom(bom_save_data)
            st.session_state.last_bom_save_time = time.time()
            bom_auto_saved = True

        bom_col1, bom_col2 = st.columns([1, 5])
        with bom_col1:
            if st.button("💾 BOM保存", use_container_width=True, disabled=not can_edit):
                save_bom(bom_save_data)
                st.session_state.last_bom_save_time = time.time()
                st.success("保存しました")

        if not can_edit:
            st.caption("🔒 閲覧専用モードのため保存されません。")
        else:
            bom_mins = int(bom_elapsed // 60) if not bom_auto_saved else 0
            if bom_auto_saved:
                st.caption("✅ 自動保存しました")
            else:
                st.caption(f"💡 最終保存から {bom_mins}分経過（15分で自動保存）")

    # ---- 見積書(PDF)の添付・管理（部品ごとに複数添付可）----
    st.markdown("---")
    st.subheader("🧾 見積書(PDF)の添付・管理")
    st.caption("URLが無い部品でも、PDFの見積書を部品ごとに複数添付できます。添付するとBOM表の「見積PDF」列に件数が表示されます。")

    # 添付対象の部品候補（現在の編集中テーブルの部品名を使用）
    if edited_bom is not None and not edited_bom.empty:
        part_names = [str(p) for p in edited_bom["部品名"].tolist() if str(p).strip()]
    else:
        part_names = [str(p.get("部品名", "")) for p in bom_data if str(p.get("部品名", "")).strip()]
    part_names = list(dict.fromkeys(part_names))  # 重複除去・順序維持

    if not part_names:
        st.info("先にBOM表へ部品を追加してください。")
    else:
        q_index = load_quotes_index()

        sel_col, up_col = st.columns([2, 3])
        with sel_col:
            target_part = st.selectbox("添付先の部品", options=part_names, key="quote_target_part")
        with up_col:
            quote_files = st.file_uploader(
                "📎 見積書PDFを追加（複数可）",
                type=["pdf"],
                accept_multiple_files=True,
                key="quote_uploader",
                disabled=not can_edit,
            )

        # 明示的な「添付」ボタンを押したときだけ保存する。
        # （file_uploaderは再実行後もファイルを保持するため、押すたびに1回だけ処理する）
        if "processed_quote_ids" not in st.session_state:
            st.session_state.processed_quote_ids = set()

        do_attach = st.button(
            "➕ 選択したPDFを添付",
            disabled=not (quote_files and target_part) or not can_edit,
            key="attach_quote_btn",
        )

        if do_attach and quote_files and target_part and can_edit:
            existing = q_index.get(target_part, [])
            added = 0
            skipped = 0
            for qf in quote_files:
                # 各アップロードファイルの一意ID（同一ファイルの二重保存を防止）
                uid = getattr(qf, "file_id", None) or f"{qf.name}:{qf.size}"
                dedup_key = f"{target_part}::{uid}"
                if dedup_key in st.session_state.processed_quote_ids:
                    skipped += 1
                    continue

                # 部品名ごとのサブフォルダに保存（部品名もサニタイズ）
                part_dir = os.path.join(QUOTES_DIR, _sanitize_filename(target_part))
                os.makedirs(part_dir, exist_ok=True)

                base = _sanitize_filename(qf.name)
                save_path = os.path.join(part_dir, base)
                # 同名ファイルがある場合は連番を付与
                stem, ext = os.path.splitext(base)
                counter = 1
                while os.path.exists(save_path):
                    base = f"{stem}_{counter}{ext}"
                    save_path = os.path.join(part_dir, base)
                    counter += 1

                with open(save_path, "wb") as f:
                    f.write(qf.getbuffer())
                rel = os.path.join(_sanitize_filename(target_part), base)
                existing.append(rel)
                st.session_state.processed_quote_ids.add(dedup_key)
                added += 1

            if added:
                q_index[target_part] = existing
                save_quotes_index(q_index)
                st.success(f"{added}件の見積書を「{target_part}」に添付しました")
                st.rerun()
            elif skipped:
                st.info("選択中のPDFはすでに添付済みです（重複保存を防止しました）。")

        # 添付済み一覧（全部品分）
        any_quote = any(len(v) > 0 for v in q_index.values())
        if any_quote:
            st.markdown("**添付済みの見積書**")
            # どのファイルをダウンロード待ちにするか（遅延読み込み用）
            pending_dl = st.session_state.get("pending_quote_dl")

            for pname in part_names:
                files = q_index.get(pname, [])
                if not files:
                    continue
                with st.expander(f"📄 {pname}（{len(files)}件）", expanded=False):
                    for rel in list(files):
                        abs_path = os.path.join(QUOTES_DIR, rel)
                        fname = os.path.basename(rel)
                        exists = os.path.exists(abs_path)
                        fcol1, fcol2, fcol3 = st.columns([5, 1.2, 1])
                        fcol1.write(f"• {fname}" + ("" if exists else "（ファイル無）"))

                        # ダウンロードは要求された1件だけ実ファイルを読む（全件readで重くなるのを回避）
                        if exists and pending_dl == rel:
                            with open(abs_path, "rb") as fh:
                                clicked = fcol2.download_button(
                                    "⬇️ 保存",
                                    data=fh.read(),
                                    file_name=fname,
                                    mime="application/pdf",
                                    key=f"dl_{rel}",
                                )
                            if clicked:
                                st.session_state.pop("pending_quote_dl", None)
                        elif exists:
                            if fcol2.button("⬇️ 開く", key=f"prep_{rel}"):
                                st.session_state["pending_quote_dl"] = rel
                                st.rerun()

                        if fcol3.button("🗑️", key=f"delq_{rel}", disabled=not can_edit):
                            # ファイルとインデックスから削除
                            try:
                                if exists:
                                    os.remove(abs_path)
                            except Exception:
                                pass
                            q_index[pname] = [r for r in q_index.get(pname, []) if r != rel]
                            if not q_index[pname]:
                                del q_index[pname]
                            save_quotes_index(q_index)
                            if st.session_state.get("pending_quote_dl") == rel:
                                st.session_state.pop("pending_quote_dl", None)
                            st.rerun()
        else:
            st.caption("まだ見積書は添付されていません。")

    st.markdown("---")

    # ---- 印刷/共有用 注意書き ----
    with st.expander("ℹ️ 共有・印刷について"):
        st.markdown("""
        - ブラウザの印刷機能（Ctrl+P）でPDF保存・印刷が可能です。
        - 顧客共有時は、ブラウザのアドレスバーのURLをそのまま送付するか、PDFに変換してご利用ください。
        - 設定はサイドバーから変更でき、「保存」ボタンで次回起動時も維持されます。
        - BOM（部品構成表）はテーブル内で直接編集できます。行の追加・削除も可能です。
        - イメージ図はドラッグ&ドロップで追加できます。
        - 見積書PDFは「見積書(PDF)の添付・管理」から部品ごとに複数添付できます。URLが無い部品でも見積の根拠を残せます。
        """)

if __name__ == "__main__":
    main()
