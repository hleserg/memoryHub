"""Docs page: browse project documentation."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from atman.tui.repo_root import find_repo_root

st.set_page_config(page_title="Docs - Atman Dashboard", page_icon="📚", layout="wide")

# Find repository root
try:
    repo_root = find_repo_root()
except FileNotFoundError:
    st.error("Repository root not found.")
    st.stop()

st.title("📚 Documentation")
st.markdown("Просмотр документации проекта")
st.divider()

# Documentation sections
DOC_SECTIONS = {
    "Architecture": "docs/architecture",
    "Development": "docs/development",
    "Features": "docs/features",
    "Ideas": "docs/ideas",
    "Research": "docs/research",
}

# Session state for navigation
if "doc_section" not in st.session_state:
    st.session_state["doc_section"] = "Architecture"
if "doc_path" not in st.session_state:
    st.session_state["doc_path"] = None

# Sidebar navigation
st.sidebar.markdown("## 📂 Навигация")

# Section selection
selected_section = st.sidebar.selectbox(
    "Раздел документации:",
    options=list(DOC_SECTIONS.keys()),
    index=list(DOC_SECTIONS.keys()).index(st.session_state["doc_section"]),
)

if selected_section != st.session_state["doc_section"]:
    st.session_state["doc_section"] = selected_section
    st.session_state["doc_path"] = None
    st.rerun()

# Get files in selected section
section_path = repo_root / DOC_SECTIONS[selected_section]

if not section_path.exists():
    st.error(f"Раздел `{DOC_SECTIONS[selected_section]}` не найден")
    st.stop()


def list_markdown_files(path: Path, prefix: str = "") -> list[tuple[str, Path]]:
    """Recursively list markdown files."""
    files: list[tuple[str, Path]] = []
    try:
        for item in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if item.name.startswith("."):
                continue
            if item.is_dir():
                files.extend(list_markdown_files(item, prefix + item.name + "/"))
            elif item.suffix.lower() in [".md", ".markdown"]:
                display_name = prefix + item.name
                files.append((display_name, item))
    except PermissionError:
        pass
    return files


markdown_files = list_markdown_files(section_path)

if markdown_files:
    # File selection in sidebar
    st.sidebar.markdown("### 📄 Файлы")
    file_options = {display: path for display, path in markdown_files}
    selected_file_display = st.sidebar.selectbox(
        "Выберите файл:",
        options=list(file_options.keys()),
        index=0,
    )

    selected_file = file_options[selected_file_display]

    # Store in session state
    st.session_state["doc_path"] = selected_file

    # Display document
    col1, col2 = st.columns([3, 1])

    with col1:
        st.markdown(f"### 📄 {selected_file.name}")

    with col2:
        # Language toggle for bilingual docs
        base_name = selected_file.stem
        if base_name.endswith("-ru"):
            en_file = selected_file.parent / (base_name[:-3] + ".md")
            if en_file.exists() and st.button("🇬🇧 English version"):
                st.session_state["doc_path"] = en_file
                st.rerun()
        else:
            ru_file = selected_file.parent / (base_name + "-ru.md")
            if ru_file.exists() and st.button("🇷🇺 Русская версия"):
                st.session_state["doc_path"] = ru_file
                st.rerun()

    st.markdown(f"**Путь:** `{selected_file.relative_to(repo_root)}`")
    st.divider()

    # Read and display content
    try:
        content = selected_file.read_text(encoding="utf-8", errors="replace")

        # Check if it's a markdown file
        if selected_file.suffix.lower() in [".md", ".markdown"]:
            with st.container(height=700, border=True):
                st.markdown(content)
        else:
            st.code(content, language="text")

    except Exception as e:
        st.error(f"Ошибка при чтении файла: {e}")

else:
    st.info(f"В разделе `{selected_section}` нет Markdown файлов")

# Quick links
st.sidebar.divider()
st.sidebar.markdown("### 🔗 Быстрые ссылки")

quick_links = {
    "README.md": repo_root / "README.md",
    "README-ru.md": repo_root / "README-ru.md",
    "MANIFEST.md": repo_root / "MANIFEST.md",
    "SYSTEM.md": repo_root / "docs/architecture/SYSTEM.md",
}

for link_name, link_path in quick_links.items():
    if link_path.exists() and st.sidebar.button(f"📌 {link_name}", use_container_width=True):
        st.session_state["doc_path"] = link_path
        # Determine section
        if "architecture" in str(link_path) or str(link_path.parent) == str(repo_root):
            st.session_state["doc_section"] = "Architecture"
        st.rerun()
