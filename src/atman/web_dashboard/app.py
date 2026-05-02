"""Main Streamlit dashboard application."""

from __future__ import annotations

import streamlit as st

from atman.tui.repo_root import find_repo_root

# Page configuration
st.set_page_config(
    page_title="Atman Dev Dashboard",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Find repository root
try:
    repo_root = find_repo_root()
except FileNotFoundError:
    st.error("Repository root not found. Please run from within the Atman repository.")
    st.stop()
    raise SystemExit("Repository root not found") from None  # For type checker

# Custom CSS for better UI
st.markdown(
    """
    <style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 1rem;
    }
    .section-header {
        font-size: 1.5rem;
        font-weight: bold;
        margin-top: 1.5rem;
        margin-bottom: 1rem;
    }
    .info-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #f0f2f6;
        margin-bottom: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Main header
st.markdown('<div class="main-header">🧠 Atman Dev Dashboard</div>', unsafe_allow_html=True)
st.markdown("**Web-интерфейс для работы с проектом Atman**")
st.divider()

# Welcome message
st.markdown(
    """
    ### Добро пожаловать в веб-дашборд Atman!

    Этот дашборд предоставляет удобный браузерный интерфейс для:

    - 🎯 **Features** — запуск демонстраций фичей и просмотр документации
    - 🧪 **Tests** — запуск тестов и анализ результатов
    - 📚 **Docs** — навигация по документации проекта

    Выберите страницу в боковом меню слева.
    """
)

# Repository info
st.markdown("### 📂 Информация о репозитории")
col1, col2 = st.columns(2)

with col1:
    st.markdown(
        f"""
        <div class="info-box">
        <strong>Корень репозитория:</strong><br>
        <code>{repo_root}</code>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col2:
    features_count = 2  # factual-memory, experience-store
    st.markdown(
        f"""
        <div class="info-box">
        <strong>Зарегистрировано фичей:</strong><br>
        {features_count}
        </div>
        """,
        unsafe_allow_html=True,
    )

# Quick actions
st.markdown("### ⚡ Быстрые действия")

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("🎯 Перейти к Features", use_container_width=True):
        st.switch_page("pages/1_Features.py")

with col2:
    if st.button("🧪 Перейти к Tests", use_container_width=True):
        st.switch_page("pages/2_Tests.py")

with col3:
    if st.button("📚 Перейти к Docs", use_container_width=True):
        st.switch_page("pages/3_Docs.py")

# Footer
st.divider()
st.markdown(
    """
    <div style="text-align: center; color: #666; font-size: 0.9rem; margin-top: 2rem;">
    Atman — Психологический слой для AI-агента | Web Dashboard v0.1.0
    </div>
    """,
    unsafe_allow_html=True,
)
