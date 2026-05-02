"""Features page: run demos and view documentation."""

from __future__ import annotations

import streamlit as st

from atman.tui.features_registry import FEATURES, FeatureInfo
from atman.tui.repo_root import find_repo_root
from atman.web_dashboard.utils import demo_subprocess_env, python_script_cmd, run_command_sync

st.set_page_config(page_title="Features - Atman Dashboard", page_icon="🎯", layout="wide")

# Find repository root
try:
    repo_root = find_repo_root()
except FileNotFoundError:
    st.error("Repository root not found.")
    st.stop()
    raise SystemExit("Repository root not found") from None  # For type checker

st.title("🎯 Features")
st.markdown("Управление фичами проекта: запуск демо и просмотр документации")
st.divider()

# Feature selection
feature_options = {f.title: f for f in FEATURES}
selected_title = st.selectbox(
    "Выберите фичу:",
    options=list(feature_options.keys()),
    index=0,
)

if selected_title:
    feature: FeatureInfo = feature_options[selected_title]

    # Feature info
    st.markdown(f"### {feature.title}")
    st.markdown(f"**Slug:** `{feature.slug}`")
    st.markdown(f"**Описание:** {feature.summary}")

    with st.expander("📁 Связанные файлы", expanded=False):
        for path in feature.related_paths:
            st.code(path)

    st.divider()

    # Demo section
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🎬 Демонстрации")

        if feature.demos:
            demo_paced = st.button(
                "🎬 Запустить Demo (paced)",
                key="demo_paced",
                use_container_width=True,
            )
            demo_fast = st.button(
                "⚡ Запустить Demo (fast)",
                key="demo_fast",
                use_container_width=True,
            )

            # Run demo
            if demo_paced or demo_fast:
                paced = demo_paced
                demo_idx = 0 if paced else min(1, len(feature.demos) - 1)

                if demo_idx < len(feature.demos):
                    demo = feature.demos[demo_idx]
                    cmd = python_script_cmd(*demo.argv)
                    # Paced/fast must follow the clicked button (not only registry index;
                    # a single DemoCommand or mis-ordered env would otherwise be wrong).
                    env = demo_subprocess_env(demo.env, paced=paced)

                    st.markdown("#### Выполнение...")
                    st.code(" ".join(cmd))

                    with st.spinner("Запуск демонстрации..."):
                        exit_code, output = run_command_sync(cmd, repo_root, env)

                    if exit_code == 0:
                        st.success(f"✅ Демонстрация завершена успешно (exit {exit_code})")
                    else:
                        st.error(f"❌ Демонстрация завершилась с ошибкой (exit {exit_code})")

                    with st.expander("📋 Вывод команды", expanded=True):
                        st.code(output, language="text")
        else:
            st.info("Нет доступных демонстраций для этой фичи")

    with col2:
        st.markdown("### 📚 Документация")

        readme_lang = st.radio(
            "Выберите язык:",
            options=["English", "Русский"],
            horizontal=True,
            key="readme_lang",
        )

        readme_file = "README.md" if readme_lang == "English" else "README-ru.md"
        readme_path = repo_root / feature.doc_dir / readme_file

        if readme_path.exists():
            content = readme_path.read_text(encoding="utf-8", errors="replace")

            with st.container(height=600, border=True):
                st.markdown(content)
        else:
            st.warning(f"Файл `{readme_file}` не найден в `{feature.doc_dir}`")

    # Install dev dependencies
    st.divider()
    st.markdown("### 🔧 Установка dev-зависимостей")

    if st.button("📦 Установить dev-зависимости", use_container_width=True):
        import sys
        from shutil import which

        if which("uv"):
            cmd = ["uv", "pip", "install", "-e", ".[dev]"]
        else:
            cmd = [sys.executable, "-m", "pip", "install", "-e", ".[dev]"]

        st.code(" ".join(cmd))

        with st.spinner("Установка зависимостей..."):
            exit_code, output = run_command_sync(cmd, repo_root)

        if exit_code == 0:
            st.success("✅ Зависимости установлены успешно")
        else:
            st.error(f"❌ Ошибка установки (exit {exit_code})")

        with st.expander("📋 Вывод команды", expanded=False):
            st.code(output, language="text")
