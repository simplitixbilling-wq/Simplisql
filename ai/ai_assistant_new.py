"""
AI Assistant Dialog for SimpliSQL – Local GGUF Edition
=======================================================
Runs models entirely in-process via llama-cpp-python.
No Ollama, no cloud APIs, no external services.

Models are auto-downloaded from HuggingFace on first use.
"""

import os
import json
import logging
import re
from datetime import datetime

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QComboBox, QCheckBox, QFrame, QTabWidget, QWidget,
    QListWidget, QListWidgetItem, QMessageBox, QApplication, QProgressBar,
    QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from ai.local_model import LocalModelClient, AVAILABLE_MODELS, DEFAULT_MODEL

logger = logging.getLogger(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Auto_Workflow", "ai_config.json")


def _load_ai_config() -> dict:
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_ai_config(cfg: dict):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def _strip_ai_diagnostics(response: str) -> str:
    if not response:
        return ""

    markers = [
        "\n\n---\n🔍 **Self-check correction:**",
        "\n\n---\n🔧 Issues detected:",
        "\n\n---\n🔎 Schema checks:",
    ]
    end = len(response)
    for marker in markers:
        idx = response.find(marker)
        if idx != -1:
            end = min(end, idx)
    return response[:end]


def _extract_sql_candidates_from_text(response: str) -> list:
    response = _strip_ai_diagnostics(response)
    candidates = []

    sql_blocks = re.findall(r"```sql\s*(.*?)```", response, re.DOTALL | re.IGNORECASE)
    candidates.extend([b.strip() for b in sql_blocks if b.strip()])

    if not candidates:
        generic_blocks = re.findall(r"```\s*(.*?)```", response, re.DOTALL)
        for block in generic_blocks:
            if re.search(r"\b(SELECT|WITH)\b", block, re.IGNORECASE):
                candidates.append(block.strip())

    if not candidates:
        lines = [ln.strip() for ln in response.splitlines() if ln.strip()]
        statement = []
        capture = False
        for ln in lines:
            up = ln.upper()
            if not capture and (up.startswith("SELECT") or up.startswith("WITH")):
                capture = True
            if capture:
                statement.append(ln)
                if ln.endswith(";"):
                    break
        if statement:
            candidates.append("\n".join(statement))

    return candidates


def _normalize_sql_text(sql: str) -> str:
    return re.sub(r"\s+", " ", (sql or "").strip().rstrip(";")).upper()


# Intent signals ---------------------------------------------------------
_PYTHON_SIGNALS = re.compile(
    r"\b("
    r"python|pandas|numpy|scipy|sklearn|scikit.learn|statsmodels|matplotlib|seaborn|plotly|"
    r"machine.learning|ml\b|deep.learning|neural.network|tensorflow|pytorch|keras|"
    r"plot|chart|histogram|heatmap|scatter.?plot|bar.?chart|line.?chart|"
    r"train|predict|fit|model|classifier|regressor|clustering|pca|feature.engineering|"
    r"correlation|covariance|outlier|anomaly|impute|normaliz|standardiz|"
    r"dataframe|series|ndarray|pivot.?table|melt|reshape|"
    r"read_csv|read_excel|to_csv|merge|concat|groupby|apply|lambda|"
    r"for.loop|list.comprehension|script|class|def |import "
    r")\b",
    re.IGNORECASE,
)

_SQL_SIGNALS = re.compile(
    r"\b(select|from|where|join|group\s+by|order\s+by|having|insert|update|delete|create\s+table|"
    r"with\s+\w+\s+as|count\(|sum\(|avg\(|max\(|min\(|duckdb|sql|query|table)\b",
    re.IGNORECASE,
)

# High-priority phrases that should always route to Python mode.
_PYTHON_PRIORITY_SIGNALS = re.compile(
    r"\b("
    r"predict|prediction|forecast|forecasting|time\s*series|"
    r"arima|sarima|prophet|lstm|"
    r"train\s+model|classification|regression|"
    r"feature\s+engineering|cross\s*validation|"
    r"anomaly\s+detection|clustering|"
    r"next\s+\d+\s*(day|days|week|weeks|month|months|year|years)"
    r")\b",
    re.IGNORECASE,
)


def _classify_intent(user_text: str) -> str:
    """Return 'python', 'sql', or 'auto' based on keyword heuristics."""
    if _PYTHON_PRIORITY_SIGNALS.search(user_text or ""):
        return "python"

    py_hits = len(_PYTHON_SIGNALS.findall(user_text))
    sql_hits = len(_SQL_SIGNALS.findall(user_text))
    if py_hits > sql_hits:
        return "python"
    if sql_hits > py_hits:
        return "sql"
    # Ambiguous prompts work better as SQL in SimpliSQL unless they include
    # high-priority Python analytics terms above.
    return "sql"


def _extract_python_candidates_from_text(response: str) -> list:
    """Extract Python code blocks from an AI response.

    Falls back to plain-text line scanning when the model omits code fences,
    which small local models often do.
    """
    candidates = []

    # 1. Explicit ```python ... ``` blocks
    py_blocks = re.findall(r"```python\s*(.*?)```", response, re.DOTALL | re.IGNORECASE)
    candidates.extend([b.strip() for b in py_blocks if b.strip()])

    # 2. Generic ``` ... ``` blocks that look like Python
    if not candidates:
        generic_blocks = re.findall(r"```\s*(.*?)```", response, re.DOTALL)
        for block in generic_blocks:
            if re.search(r"\b(import|def |for |pd\.|df\.|plt\.|np\.|result_df|result_sql|to_df|sql\(|load_relation)\b", block):
                candidates.append(block.strip())

    # 3. Plain-text fallback: collect consecutive lines that look like Python code
    #    (no fences at all — common with small local GGUF models)
    if not candidates:
        _PYTHON_LINE = re.compile(
            r"^\s*("
            r"(import |from \w)|"          # import statements
            r"(def |class )|"              # definitions
            r"(for |while |if |elif |else:|try:|except|with )|"  # control flow
            r"(result_df|result_sql|result_relation)\s*=|"       # SimpliSQL output vars
            r"(to_df|sql|load_relation|stream_df)\s*\(|"         # DuckDB helpers
            r"(pd\.|df\.|np\.|plt\.|sns\.|sklearn\.|sm\.|xgb\.|lgb\.|px\.)|"  # lib usage
            r"#"                           # comment line
            r")"
        )
        lines = response.splitlines()
        block_lines: list[str] = []
        collected_blocks: list[str] = []
        for line in lines:
            if _PYTHON_LINE.match(line) or (block_lines and line.strip() == ""):
                block_lines.append(line)
            else:
                if len(block_lines) >= 2:  # at least 2 Python-looking lines = a block
                    collected_blocks.append("\n".join(block_lines).strip())
                block_lines = []
        if len(block_lines) >= 2:
            collected_blocks.append("\n".join(block_lines).strip())
        # Keep only blocks that contain at least one "real" Python statement
        for blk in collected_blocks:
            if re.search(r"\b(result_df|result_sql|to_df|sql\(|load_relation|import |def |pd\.|df\.)\b", blk):
                candidates.append(blk)

    return candidates


# ── Background threads ────────────────────────────────────────────────

class ModelLoaderThread(QThread):
    """Download + load a model without freezing the UI."""
    progress = pyqtSignal(str)
    finished_ok = pyqtSignal()
    finished_err = pyqtSignal(str)

    def __init__(self, client: LocalModelClient, model_key: str):
        super().__init__()
        self.client = client
        self.model_key = model_key

    def run(self):
        try:
            ok = self.client.load_model(self.model_key, progress_callback=self.progress.emit)
            if ok:
                self.finished_ok.emit()
            else:
                self.finished_err.emit("Failed to load model.")
        except Exception as e:
            self.finished_err.emit(str(e))


class AIChatThread(QThread):
    """Generate a response in the background, then self-validate."""
    response_ready = pyqtSignal(str)
    token_ready = pyqtSignal(str)   # emitted per token during streaming
    error_occurred = pyqtSignal(str)

    def __init__(self, client: LocalModelClient, messages: list, user_request: str = ""):
        super().__init__()
        self.client = client
        self.messages = messages
        self.user_request = user_request

    def run(self):
        try:
            # Calculate max_tokens based on model's context length (use ~40% for output)
            ctx = getattr(self.client, 'context_length', 4096)
            main_max_tokens = max(512, min(2048, ctx // 2 - 256))

            # Pass 1: Stream the response token-by-token
            def _on_token(token: str):
                self.token_ready.emit(token)

            text = self.client.chat_streaming(
                self.messages,
                max_tokens=main_max_tokens,
                temperature=0.3,
                token_callback=_on_token,
            )
            if not text:
                self.error_occurred.emit("Model returned an empty response.")
                return

            # Check for DuckDB-specific syntax errors and auto-fix
            sql_candidates = _extract_sql_candidates_from_text(text)
            sql_text = "\n".join(sql_candidates)
            if sql_text:
                error_fixes = []
                text_upper = sql_text.upper()
                
                if "WHERE" in text_upper and "ROW_NUMBER()" in text_upper:
                    if "QUALIFY" not in text_upper:
                        error_fixes.append(
                            "⚠️ WHERE clause with window function detected. "
                            "DuckDB requires QUALIFY instead of WHERE."
                        )
                
                # Detect and auto-fix QUALIFY used without any window function
                has_qualify = "QUALIFY" in text_upper
                has_over = " OVER " in text_upper or " OVER(" in text_upper
                if has_qualify and not has_over:
                    # Extract SQL blocks and fix them
                    def fix_qualify(match):
                        sql = match.group(1)
                        # Remove QUALIFY clause (it's invalid without window function)
                        fixed = re.sub(
                            r'\s*QUALIFY\b[^;]*?(?=\s*(?:GROUP\s+BY|ORDER\s+BY|LIMIT|HAVING|;|$))',
                            '',
                            sql,
                            flags=re.IGNORECASE | re.DOTALL,
                        )
                        return f"```sql\n{fixed.strip()}\n```"
                    
                    # Try to fix SQL in code blocks
                    fixed_text = re.sub(
                        r'```sql\s*\n([\s\S]*?)\n```',
                        fix_qualify,
                        text,
                        flags=re.IGNORECASE,
                    )
                    if fixed_text != text:
                        text = fixed_text
                        error_fixes.append(
                            "🔧 Auto-fixed: Removed invalid QUALIFY clause (QUALIFY requires a window function like ROW_NUMBER() OVER (...))."
                        )
                    else:
                        error_fixes.append(
                            "⚠️ QUALIFY used without a window function. "
                            "QUALIFY only works with window functions (e.g. ROW_NUMBER() OVER (...)). "
                            "Use WHERE or HAVING for regular filters."
                        )
                
                if error_fixes:
                    text = text + "\n\n---\n🔧 Issues detected:\n" + "\n".join(error_fixes)

            self.response_ready.emit(text)
        except Exception as e:
            self.error_occurred.emit(str(e))


# ── Dialog ────────────────────────────────────────────────────────────

class AIAssistantDialog(QDialog):
    """AI Assistant dialog – fully local, no external services."""

    def __init__(self, parent_editor):
        super().__init__(parent_editor)
        self.parent_editor = parent_editor
        self.current_conversation = []
        self.setWindowTitle("🤖 AI Assistant (Local Model)")

        # Core client
        self.client = LocalModelClient()
        self._force_close = False
        self._chat_thread = None
        self._generation_cancelled = False
        self._last_answer_mode = "auto"

        # Load saved default model preference
        cfg = _load_ai_config()
        self.selected_model_key = cfg.get("default_model", DEFAULT_MODEL)

        # Window setup
        self.setMinimumSize(760, 520)
        screen = QApplication.primaryScreen().availableGeometry()
        width = min(1100, screen.width() - 80)
        height = min(760, screen.height() - 80)
        self.resize(width, height)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        # Center on parent or screen
        parent = self.parent()
        if parent is not None:
            parent_geo = parent.frameGeometry()
            self_geo = self.frameGeometry()
            self_geo.moveCenter(parent_geo.center())
            self.move(self_geo.topLeft())
        else:
            screen_geo = QApplication.primaryScreen().availableGeometry()
            self.move(
                screen_geo.center().x() - self.width() // 2,
                screen_geo.center().y() - self.height() // 2
            )

        self._build_ui()
        self._refresh_table_context_list()
        self._refresh_model_status()

        # Sync the chat tab combo to the saved default
        for i in range(self.model_combo.count()):
            if self.model_combo.itemData(i) == self.selected_model_key:
                self.model_combo.setCurrentIndex(i)
                break

        # Auto-load default model in background on startup
        if not self.client.is_loaded():
            self._auto_load_default()

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Tabs
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #ccc; }
            QTabBar::tab { padding: 12px 24px; font-size: 14px; font-weight: bold; }
            QTabBar::tab:selected { background-color: #4caf50; color: white; }
        """)

        self.tab_widget.addTab(self._chat_tab(), "💬 Chat")
        self.tab_widget.addTab(self._settings_tab(), "⚙️ Settings")
        layout.addWidget(self.tab_widget)

        # Hidden status label (used internally for state tracking, not shown)
        self.status_label = QLabel()
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        self.apply_theme()

    # ── Chat tab ──────────────────────────────────────────────────────

    def _chat_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(15, 15, 15, 15)
        lay.setSpacing(10)

        # Model row
        model_frame = QFrame()
        model_frame.setFrameShape(QFrame.Shape.StyledPanel)
        ml = QHBoxLayout(model_frame)
        ml.setSpacing(10)
        ml.addWidget(QLabel("<b>Model:</b>"))
        self.model_combo = QComboBox()
        for key, info in AVAILABLE_MODELS.items():
            self.model_combo.addItem(info["description"], key)
        self.model_combo.currentIndexChanged.connect(self._on_model_combo_changed)
        ml.addWidget(self.model_combo)

        self.load_btn = QPushButton("🔄 Reload Model")
        self.load_btn.clicked.connect(self._download_and_load)
        self.load_btn.setStyleSheet(
            "QPushButton{background:#4caf50;color:white;font-weight:bold;padding:7px 16px 9px 16px;border-radius:4px;border:1px solid #2e7d32;border-bottom:3px solid #2e7d32;}"
            "QPushButton:hover{background:#43a047;}"
            "QPushButton:pressed{background:#388e3c;padding:8px 16px 8px 16px;border-bottom:1px solid #2e7d32;}"
            "QPushButton:disabled{background:#a5d6a7;color:#e8f5e9;}"
        )
        ml.addWidget(self.load_btn)
        ml.addWidget(QLabel("|"))

        ml.addWidget(QLabel("Answer mode:"))
        self.answer_mode_combo = QComboBox()
        self.answer_mode_combo.addItem("🤖 Auto-detect", "auto")
        self.answer_mode_combo.addItem("🗃️ Force SQL", "sql")
        self.answer_mode_combo.addItem("🐍 Force Python", "python")
        self.answer_mode_combo.setToolTip(
            "Auto: AI detects SQL vs Python from your question.\n"
            "Force SQL: always generate SQL.\n"
            "Force Python: always generate Python using DuckDB helpers."
        )
        self.answer_mode_combo.setStyleSheet("padding:4px 8px; font-size:12px;")
        ml.addWidget(self.answer_mode_combo)

        self.auto_paste_check = QCheckBox("Auto-paste")
        self.auto_paste_check.setChecked(True)
        self.auto_paste_check.setToolTip(
            "When checked, SQL is pasted to the SQL notepad and Python to the Python notepad automatically."
        )
        ml.addWidget(self.auto_paste_check)
        ml.addStretch()
        lay.addWidget(model_frame)

        # Chat display
        lay.addWidget(QLabel("<b style='font-size:16px'>💬 Chat</b>"))
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setMinimumHeight(400)
        self.chat_display.setStyleSheet(
            "QTextEdit { background:#fff; color:#000; border:2px solid #ddd; "
            "border-radius:6px; padding:12px; font-size:14px; font-family:'Segoe UI',Arial; }"
        )
        lay.addWidget(self.chat_display, stretch=1)

        # Input row
        inp = QHBoxLayout()
        inp.setSpacing(10)
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Ask about SQL, data, or workflows…")
        self.user_input.setStyleSheet("font-size:13px; padding:8px; border:2px solid #ddd; border-radius:4px;")
        self.user_input.returnPressed.connect(self.send_message)
        inp.addWidget(self.user_input)

        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.send_message)
        send_btn.setStyleSheet(
            "QPushButton{background:#4caf50;color:white;font-weight:bold;padding:7px 16px 9px 16px;border-radius:4px;border:1px solid #2e7d32;border-bottom:3px solid #2e7d32;}"
            "QPushButton:hover{background:#43a047;}"
            "QPushButton:pressed{background:#388e3c;padding:8px 16px 8px 16px;border-bottom:1px solid #2e7d32;}"
            "QPushButton:disabled{background:#a5d6a7;color:#e8f5e9;}"
        )
        send_btn.setObjectName("send_btn")
        inp.addWidget(send_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._stop_generation)
        self.stop_btn.setStyleSheet(
            "QPushButton{background:#f44336;color:white;font-weight:bold;padding:7px 16px 9px 16px;border-radius:4px;border:1px solid #b71c1c;border-bottom:3px solid #b71c1c;}"
            "QPushButton:hover{background:#e53935;}"
            "QPushButton:pressed{background:#c62828;padding:8px 16px 8px 16px;border-bottom:1px solid #b71c1c;}"
            "QPushButton:disabled{background:#ef9a9a;color:#fff;}"
        )
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.setEnabled(False)
        inp.addWidget(self.stop_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_chat)
        clear_btn.setStyleSheet(
            "QPushButton{padding:7px 12px 9px 12px;border-radius:4px;background:#e0e0e0;color:#333;border:1px solid #9e9e9e;border-bottom:3px solid #9e9e9e;}"
            "QPushButton:hover{background:#bdbdbd;}"
            "QPushButton:pressed{background:#9e9e9e;padding:8px 12px 8px 12px;border-bottom:1px solid #9e9e9e;}"
            "QPushButton:disabled{background:#f5f5f5;color:#aaa;}"
        )
        clear_btn.setObjectName("clear_btn")
        inp.addWidget(clear_btn)

        copy_btn = QPushButton("📋 Copy Last SQL")
        copy_btn.clicked.connect(self._copy_last_sql_to_editor)
        copy_btn.setStyleSheet(
            "QPushButton{padding:7px 12px 9px 12px;border-radius:4px;background:#e0e0e0;color:#333;border:1px solid #9e9e9e;border-bottom:3px solid #9e9e9e;}"
            "QPushButton:hover{background:#bdbdbd;}"
            "QPushButton:pressed{background:#9e9e9e;padding:8px 12px 8px 12px;border-bottom:1px solid #9e9e9e;}"
            "QPushButton:disabled{background:#f5f5f5;color:#aaa;}"
        )
        copy_btn.setObjectName("copy_btn")
        inp.addWidget(copy_btn)

        py_btn = QPushButton("🐍 Copy Last Python")
        py_btn.clicked.connect(self._copy_last_python_to_notepad)
        py_btn.setStyleSheet(
            "QPushButton{padding:7px 12px 9px 12px;border-radius:4px;background:#e8f5e9;color:#2e7d32;border:1px solid #81c784;border-bottom:3px solid #4caf50;}"
            "QPushButton:hover{background:#c8e6c9;}"
            "QPushButton:pressed{background:#a5d6a7;padding:8px 12px 8px 12px;border-bottom:1px solid #4caf50;}"
            "QPushButton:disabled{background:#f5f5f5;color:#aaa;}"
        )
        py_btn.setObjectName("py_btn")
        inp.addWidget(py_btn)

        lay.addLayout(inp)

        return w

    # ── Settings tab ──────────────────────────────────────────────────

    def _settings_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        lay.addWidget(QLabel("<b style='font-size:18px'>⚙️ Settings</b>"))

        # Model info
        mf = QFrame()
        mf.setFrameShape(QFrame.Shape.StyledPanel)
        ml = QVBoxLayout(mf)
        ml.addWidget(QLabel("<b>Local Model Engine</b>"))
        self.model_info_label = QLabel("Status: checking…")
        ml.addWidget(self.model_info_label)

        self.model_list_widget = QListWidget()
        self.model_list_widget.setMaximumHeight(90)
        ml.addWidget(self.model_list_widget)
        lay.addWidget(mf)

        # Context options
        cf = QFrame()
        cf.setFrameShape(QFrame.Shape.StyledPanel)
        cl = QVBoxLayout(cf)
        cl.addWidget(QLabel("<b>Context Options</b>"))
        self.context_query_check = QCheckBox("Include current SQL query as context")
        cl.addWidget(self.context_query_check)

        cl.addWidget(QLabel("<b>Tables To Include In AI Analysis</b>"))
        self.table_context_list = QListWidget()
        self.table_context_list.setMaximumHeight(140)
        cl.addWidget(self.table_context_list)

        table_btn_row = QHBoxLayout()
        refresh_tables_btn = QPushButton("Refresh")
        refresh_tables_btn.clicked.connect(self._refresh_table_context_list)
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(lambda: self._set_all_table_checks(Qt.CheckState.Checked))
        clear_all_btn = QPushButton("Clear All")
        clear_all_btn.clicked.connect(lambda: self._set_all_table_checks(Qt.CheckState.Unchecked))
        apply_tables_btn = QPushButton("Apply Selection")
        apply_tables_btn.clicked.connect(self._sync_selected_tables_to_parent)
        table_btn_row.addWidget(refresh_tables_btn)
        table_btn_row.addWidget(select_all_btn)
        table_btn_row.addWidget(clear_all_btn)
        table_btn_row.addWidget(apply_tables_btn)
        table_btn_row.addStretch()
        cl.addLayout(table_btn_row)
        lay.addWidget(cf)

        # Default model selector
        df = QFrame()
        df.setFrameShape(QFrame.Shape.StyledPanel)
        dl = QVBoxLayout(df)
        dl.addWidget(QLabel("<b>Default Model (auto-loads on app start)</b>"))
        self.default_model_combo = QComboBox()
        self._refresh_default_model_combo()
        save_default_btn = QPushButton("💾 Save as Default")
        save_default_btn.setStyleSheet(
            "QPushButton{background:#2196F3;color:white;font-weight:bold;padding:7px 16px 9px 16px;border-radius:4px;border:1px solid #0d47a1;border-bottom:3px solid #0d47a1;}"
            "QPushButton:hover{background:#1e88e5;}"
            "QPushButton:pressed{background:#1565c0;padding:8px 16px 8px 16px;border-bottom:1px solid #0d47a1;}"
        )
        save_default_btn.clicked.connect(self._save_default_model)
        drow = QHBoxLayout()
        drow.addWidget(self.default_model_combo)
        drow.addWidget(save_default_btn)
        dl.addLayout(drow)
        lay.addWidget(df)

        note = QLabel(
            "<i>Models are downloaded from HuggingFace and stored locally.<br>"
            "No external service needs to be running. Everything runs in-process.</i>"
        )
        note.setStyleSheet("color:#888;")
        note.setWordWrap(True)
        lay.addWidget(note)

        # ── Milestone 3: Library Status panel ─────────────────────────
        lf = QFrame()
        lf.setFrameShape(QFrame.Shape.StyledPanel)
        ll = QVBoxLayout(lf)
        lib_header = QHBoxLayout()
        lib_header.addWidget(QLabel("<b>Python Notepad – Available DS/ML Libraries</b>"))
        refresh_libs_btn = QPushButton("🔄 Refresh")
        refresh_libs_btn.setStyleSheet("padding:4px 10px; font-size:12px;")
        refresh_libs_btn.clicked.connect(self._refresh_library_status)
        lib_header.addWidget(refresh_libs_btn)
        lib_header.addStretch()
        ll.addLayout(lib_header)
        self.lib_status_list = QListWidget()
        self.lib_status_list.setMaximumHeight(130)
        self.lib_status_list.setStyleSheet("font-size:12px;")
        ll.addWidget(self.lib_status_list)
        install_row = QHBoxLayout()
        self.lib_install_input = QLineEdit()
        self.lib_install_input.setPlaceholderText("package-name (e.g. xgboost)")
        self.lib_install_input.setStyleSheet("padding:5px; font-size:12px;")
        install_btn = QPushButton("⬇ pip install")
        install_btn.setStyleSheet(
            "QPushButton{background:#2196F3;color:white;font-weight:bold;padding:6px 14px;"
            "border-radius:4px;border:1px solid #0d47a1;border-bottom:3px solid #0d47a1;}"
            "QPushButton:hover{background:#1e88e5;}"
            "QPushButton:pressed{background:#1565c0;}"
        )
        install_btn.clicked.connect(self._pip_install_package)
        install_row.addWidget(self.lib_install_input)
        install_row.addWidget(install_btn)
        ll.addLayout(install_row)
        lay.addWidget(lf)

        lay.addStretch()
        scroll.setWidget(w)
        self._refresh_library_status()
        return scroll

    # ── Library status (Milestone 3) ─────────────────────────────────

    def _refresh_library_status(self):
        """Populate the library status list widget."""
        if not hasattr(self, 'lib_status_list'):
            return
        from core.python_execution_manager import get_ds_library_status
        self.lib_status_list.clear()
        for entry in get_ds_library_status():
            if entry["available"]:
                icon = "✅"
                text = f"{icon}  {entry['label']}  ({entry['alias']})  v{entry['version']}"
                color = "#1b5e20"
            else:
                icon = "❌"
                text = f"{icon}  {entry['label']}  ({entry['alias']})  — not installed  [pip install {entry['pip_name']}]"
                color = "#b71c1c"
            item = QListWidgetItem(text)
            item.setForeground(__import__('PyQt6.QtGui', fromlist=['QColor']).QColor(color))
            self.lib_status_list.addItem(item)

    def _pip_install_package(self):
        """Run pip install for the entered package name."""
        if not hasattr(self, 'lib_install_input'):
            return
        package = self.lib_install_input.text().strip()
        if not package:
            QMessageBox.warning(self, "No Package", "Enter a package name to install.")
            return
        # Validate package name: only allow safe pypi names
        import re as _re
        if not _re.match(r'^[A-Za-z0-9_.\-]+$', package):
            QMessageBox.warning(self, "Invalid Package Name",
                                "Package name contains invalid characters.")
            return
        import subprocess, sys
        self.lib_status_list.clear()
        self.lib_status_list.addItem(f"⏳ Installing {package}…")
        QApplication.processEvents()
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", package],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                QMessageBox.information(self, "Installed",
                                        f"✅ {package} installed successfully.\n\nRestart SimpliSQL to use it in scripts.")
            else:
                QMessageBox.warning(self, "Install Failed",
                                    f"pip install {package} failed:\n\n{result.stderr[-800:]}")
        except subprocess.TimeoutExpired:
            QMessageBox.warning(self, "Timeout", "pip install timed out after 120s.")
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))
        finally:
            self.lib_install_input.clear()
            self._refresh_library_status()

    # ── Theme ─────────────────────────────────────────────────────────

    def apply_theme(self):
        if hasattr(self.parent_editor, 'current_theme') and self.parent_editor.current_theme == 'dark':
            self.setStyleSheet("""
                QDialog { background-color: #2b2b2b; color: #ffffff; }
                QLabel { color: #ffffff; }
                QLineEdit { background-color: #3c3c3c; color: #ffffff; border: 1px solid #555; padding: 5px; }
                QTextEdit { background-color: #3c3c3c; color: #ffffff; border: 1px solid #555; }
                QComboBox { background-color: #3c3c3c; color: #ffffff; border: 1px solid #555; padding: 5px; }
                QPushButton { background-color: #4caf50; color: white; border: none; padding: 8px 15px; border-radius: 4px; }
                QPushButton:hover { background-color: #45a049; }
                QFrame { border: 1px solid #555; background-color: #333; }
                QListWidget { background-color: #3c3c3c; color: #ffffff; border: 1px solid #555; }
            """)

    # ── Model management ──────────────────────────────────────────────

    def _refresh_model_status(self):
        models = self.client.list_available_models()

        # Refresh the combo box with all models (registered + custom)
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for m in models:
            self.model_combo.addItem(m["description"], m["key"])
        # Sync combo to currently loaded model
        if self.client.is_loaded():
            for i in range(self.model_combo.count()):
                if self.model_combo.itemData(i) == self.client.model_name:
                    self.model_combo.setCurrentIndex(i)
                    break
        elif self.selected_model_key:
            for i in range(self.model_combo.count()):
                if self.model_combo.itemData(i) == self.selected_model_key:
                    self.model_combo.setCurrentIndex(i)
                    break
        self.model_combo.blockSignals(False)

        self.model_list_widget.clear()
        for m in models:
            tag = "✅ downloaded" if m["downloaded"] else "⬇️ not downloaded"
            self.model_list_widget.addItem(f"{m['description']}  [{tag}]")

        # Keep the default-model combo in Settings tab in sync too
        self._refresh_default_model_combo()

        if self.client.is_loaded():
            model_name = self.client.model_name
            info = AVAILABLE_MODELS.get(model_name, {})
            desc = info.get("description", "")
            if not desc:
                for m in self.client.list_available_models():
                    if m["key"] == model_name:
                        desc = m["description"]
                        break
            if not desc:
                desc = model_name.replace("custom:", "").replace("-", " ").replace("_", " ").replace(".gguf", "")
            self.status_label.setText(f"✅ Model loaded: {desc}")
            self.model_info_label.setText(f"Loaded: {desc}")
            self.load_btn.setText("🔄 Reload Model")
            self._add_welcome_message()
        else:
            self.status_label.setText("⚠️ No model loaded – click 'Download & Load Model'")
            self.model_info_label.setText("No model loaded")
            self.chat_display.setHtml(
                "<div style='padding:12px;background:#fff3e0;border-radius:4px;color:#e65100;'>"
                "<b>⚠️ No model loaded</b><br>"
                "Click <b>Download &amp; Load Model</b> above to get started.<br>"
                "The model will be downloaded once from HuggingFace (~0.7-1.6 GB) and cached locally.<br><br>"
                "<b>No external application needed</b> – the model runs directly inside SimpliSQL."
                "</div>"
            )

    def _on_model_combo_changed(self):
        self.selected_model_key = self.model_combo.currentData() or DEFAULT_MODEL

    def _auto_load_default(self):
        """Auto-load the default model in background on startup."""
        key = self.selected_model_key
        # Validate that the key exists (could be custom or registered)
        if key not in AVAILABLE_MODELS and not key.startswith("custom:"):
            key = DEFAULT_MODEL
            self.selected_model_key = key
        desc = AVAILABLE_MODELS.get(key, {}).get("description", key)
        self._model_load_start_time = datetime.now()
        self.status_label.setText(f"⏳ Loading model into memory...")
        self.load_btn.setEnabled(False)
        QApplication.processEvents()

        # Disable chat input during loading
        self.user_input.setEnabled(False)
        self.user_input.setPlaceholderText("⏳ Loading model... Please wait.")
        send_btn = self.findChild(QPushButton, "send_btn")
        if send_btn:
            send_btn.setEnabled(False)
        clear_btn = self.findChild(QPushButton, "clear_btn")
        if clear_btn:
            clear_btn.setEnabled(False)
        copy_btn = self.findChild(QPushButton, "copy_btn")
        if copy_btn:
            copy_btn.setEnabled(False)

        # Show loading message in chat
        self.chat_display.append(
            f"<div style='margin:8px 0;padding:10px;background:#fff3e0;"
            f"border-left:3px solid #ff9800;border-radius:4px;'>"
            f"<b style='color:#e65100;'>⏳ Loading Model:</b><br>"
            f"<div style='color:#000;margin-top:4px;'>Auto-loading {desc}... This may take a few minutes.</div></div>"
        )
        sb = self.chat_display.verticalScrollBar()
        sb.setValue(sb.maximum())

        self._loader = ModelLoaderThread(self.client, key)
        self._loader.progress.connect(lambda msg: self.status_label.setText(f"⏳ {msg}"))
        self._loader.progress.connect(self._update_loading_progress)
        self._loader.finished_ok.connect(self._on_model_loaded)
        self._loader.finished_err.connect(self._on_model_load_error)
        self._loader.start()

    def _download_and_load(self):
        """Only reload if user selected a different model, or force reload."""
        key = self.selected_model_key
        if not key:
            key = DEFAULT_MODEL
            self.selected_model_key = key
        # If same model is already loaded, do nothing
        if self.client.is_loaded() and self.client.model_name == key:
            self.status_label.setText(f"✅ Model already loaded")
            return

        # Unload current model before loading new one
        if self.client.is_loaded():
            self.client.unload_model()

        desc = AVAILABLE_MODELS.get(key, {}).get("description", key)
        self._model_load_start_time = datetime.now()
        self.load_btn.setEnabled(False)
        self.status_label.setText(f"⏳ Preparing {desc}…")
        QApplication.processEvents()

        # Disable chat input during loading
        self.user_input.setEnabled(False)
        self.user_input.setPlaceholderText("⏳ Loading model... Please wait.")
        send_btn = self.findChild(QPushButton, "send_btn")  # Assuming we set object name
        if send_btn:
            send_btn.setEnabled(False)
        clear_btn = self.findChild(QPushButton, "clear_btn")
        if clear_btn:
            clear_btn.setEnabled(False)
        copy_btn = self.findChild(QPushButton, "copy_btn")
        if copy_btn:
            copy_btn.setEnabled(False)

        # Show loading message in chat
        self.chat_display.append(
            f"<div style='margin:8px 0;padding:10px;background:#fff3e0;"
            f"border-left:3px solid #ff9800;border-radius:4px;'>"
            f"<b style='color:#e65100;'>⏳ Loading Model:</b><br>"
            f"<div style='color:#000;margin-top:4px;'>Preparing {desc}... This may take a few minutes.</div></div>"
        )
        sb = self.chat_display.verticalScrollBar()
        sb.setValue(sb.maximum())

        self._loader = ModelLoaderThread(self.client, key)
        self._loader.progress.connect(lambda msg: self.status_label.setText(f"⏳ {msg}"))
        self._loader.progress.connect(self._update_loading_progress)
        self._loader.finished_ok.connect(self._on_model_loaded)
        self._loader.finished_err.connect(self._on_model_load_error)
        self._loader.start()

    def _update_loading_progress(self, msg):
        """Update the loading message in chat with current progress."""
        # Replace the last loading message
        html = self.chat_display.toHtml()
        # Find and replace the loading div
        if "⏳ Loading Model:" in html:
            new_msg = (
                f"<div style='margin:8px 0;padding:10px;background:#fff3e0;"
                f"border-left:3px solid #ff9800;border-radius:4px;'>"
                f"<b style='color:#e65100;'>⏳ Loading Model:</b><br>"
                f"<div style='color:#000;margin-top:4px;'>{msg}</div></div>"
            )
            # Simple replacement - replace the entire loading div
            start = html.find("<div style='margin:8px 0;padding:10px;background:#fff3e0;")
            if start != -1:
                end = html.find("</div>", start) + 6
                html = html[:start] + new_msg + html[end:]
                self.chat_display.setHtml(html)
                sb = self.chat_display.verticalScrollBar()
                sb.setValue(sb.maximum())

    def _on_model_loaded(self):
        self.load_btn.setEnabled(True)
        self._refresh_model_status()

        load_elapsed = (datetime.now() - getattr(self, '_model_load_start_time', datetime.now())).total_seconds()
        load_time_text = f"{load_elapsed:.1f}s"

        # Keep timing visible in status areas after refresh.
        current_status = self.status_label.text() or ""
        if current_status.startswith("✅ Model loaded:"):
            self.status_label.setText(f"{current_status} ({load_time_text})")
        current_info = self.model_info_label.text() or ""
        if current_info.startswith("Loaded:"):
            self.model_info_label.setText(f"{current_info} ({load_time_text})")

        # Re-enable chat input
        self.user_input.setEnabled(True)
        self.user_input.setPlaceholderText("Ask about SQL, data, or workflows…")
        send_btn = self.findChild(QPushButton, "send_btn")
        if send_btn:
            send_btn.setEnabled(True)
        clear_btn = self.findChild(QPushButton, "clear_btn")
        if clear_btn:
            clear_btn.setEnabled(True)
        copy_btn = self.findChild(QPushButton, "copy_btn")
        if copy_btn:
            copy_btn.setEnabled(True)

        # Show success message in chat
        desc = AVAILABLE_MODELS.get(self.selected_model_key, {}).get("description", self.selected_model_key)
        self.chat_display.append(
            f"<div style='margin:8px 0;padding:10px;background:#e8f5e8;"
            f"border-left:3px solid #4caf50;border-radius:4px;'>"
            f"<b style='color:#2e7d32;'>✅ Model Loaded:</b><br>"
            f"<div style='color:#000;margin-top:4px;'>{desc} is ready in <b>{load_time_text}</b>! You can now ask questions.</div></div>"
        )
        sb = self.chat_display.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_model_load_error(self, error):
        self.load_btn.setEnabled(True)
        self.status_label.setText(f"❌ Error: {error}")
        QMessageBox.warning(self, "Error", f"Failed to load model:\n{error}")

        # Re-enable chat input
        self.user_input.setEnabled(True)
        self.user_input.setPlaceholderText("Ask about SQL, data, or workflows…")
        send_btn = self.findChild(QPushButton, "send_btn")
        if send_btn:
            send_btn.setEnabled(True)
        clear_btn = self.findChild(QPushButton, "clear_btn")
        if clear_btn:
            clear_btn.setEnabled(True)
        copy_btn = self.findChild(QPushButton, "copy_btn")
        if copy_btn:
            copy_btn.setEnabled(True)

        # Show error message in chat
        self.chat_display.append(
            f"<div style='margin:8px 0;padding:10px;background:#ffebee;"
            f"border-left:3px solid #f44336;border-radius:4px;'>"
            f"<b style='color:#c62828;'>❌ Model Load Failed:</b><br>"
            f"<div style='color:#000;margin-top:4px;'>{error}</div></div>"
        )
        sb = self.chat_display.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _refresh_default_model_combo(self):
        """Populate the default-model combo with all registered + custom models."""
        self.default_model_combo.blockSignals(True)
        self.default_model_combo.clear()
        for m in self.client.list_available_models():
            self.default_model_combo.addItem(m["description"], m["key"])
        # Restore saved selection
        cfg = _load_ai_config()
        saved = cfg.get("default_model", DEFAULT_MODEL)
        for i in range(self.default_model_combo.count()):
            if self.default_model_combo.itemData(i) == saved:
                self.default_model_combo.setCurrentIndex(i)
                break
        self.default_model_combo.blockSignals(False)

    def _save_default_model(self):
        """Save the selected default model to config."""
        key = self.default_model_combo.currentData()
        if key:
            cfg = _load_ai_config()
            cfg["default_model"] = key
            _save_ai_config(cfg)
            desc = self.default_model_combo.currentText()
            self.status_label.setText(f"💾 Default model saved: {desc}")
            self.selected_model_key = key
            # Update main combo to match
            for i in range(self.model_combo.count()):
                if self.model_combo.itemData(i) == key:
                    self.model_combo.setCurrentIndex(i)
                    break

    def _refresh_table_context_list(self):
        if not hasattr(self, "table_context_list"):
            return

        self.table_context_list.clear()
        editor_tables = list(getattr(self.parent_editor, "uploaded_display_names", []) or [])
        selected = set(getattr(self.parent_editor, "selected_tables_for_ai", []) or editor_tables)

        if not editor_tables:
            self.table_context_list.addItem("No uploaded tables available")
            item = self.table_context_list.item(0)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            return

        for table_name in editor_tables:
            item = QListWidgetItem(table_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if table_name in selected else Qt.CheckState.Unchecked)
            self.table_context_list.addItem(item)

    def _set_all_table_checks(self, state):
        if not hasattr(self, "table_context_list"):
            return
        for i in range(self.table_context_list.count()):
            item = self.table_context_list.item(i)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(state)
        self._sync_selected_tables_to_parent()

    def _get_selected_tables_for_ai(self):
        editor_tables = list(getattr(self.parent_editor, "uploaded_display_names", []) or [])
        if not hasattr(self, "table_context_list") or self.table_context_list.count() == 0:
            return editor_tables

        selected = []
        for i in range(self.table_context_list.count()):
            item = self.table_context_list.item(i)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable and item.checkState() == Qt.CheckState.Checked:
                selected.append(item.text())

        # If user clears all, fall back to all so the assistant remains usable.
        return selected if selected else editor_tables

    def _sync_selected_tables_to_parent(self):
        if self.parent_editor is None:
            return
        self.parent_editor.selected_tables_for_ai = self._get_selected_tables_for_ai()

    def _estimate_tokens(self, text: str) -> int:
        # Fast heuristic: most LLM tokenizers are roughly 3-4 chars/token on mixed text.
        return max(1, len(text) // 4)

    def _get_model_context_limit(self) -> int:
        key = self.client.model_name or self.selected_model_key or DEFAULT_MODEL
        return int(AVAILABLE_MODELS.get(key, {}).get("context_length", 4096))

    def _estimate_messages_tokens(self, messages: list) -> int:
        total = 0
        for msg in messages:
            total += self._estimate_tokens(msg.get("content", "")) + 20
        return total

    def _extract_sql_candidates(self, response: str) -> list:
        return _extract_sql_candidates_from_text(response)

    def _schema_validate_response(self, response: str) -> list:
        warnings = []
        editor = self.parent_editor
        if not hasattr(editor, "conn"):
            return warnings

        sql_candidates = self._extract_sql_candidates(response)
        if not sql_candidates:
            return warnings

        selected_tables = set(t.lower() for t in (getattr(editor, "selected_tables_for_ai", []) or []))
        uploaded_tables = set(t.lower() for t in (getattr(editor, "uploaded_display_names", []) or []))
        display_names = list(getattr(editor, "uploaded_display_names", []) or [])
        uploaded_files = list(getattr(editor, "uploaded_files", []) or [])
        doc_dir = getattr(editor, "doc_dir", "")

        table_sources = {}
        for idx, dname in enumerate(display_names):
            if idx < len(uploaded_files) and uploaded_files[idx]:
                table_sources[dname.lower()] = uploaded_files[idx].replace("\\", "/")
            elif doc_dir:
                table_sources[dname.lower()] = os.path.join(doc_dir, f"{dname}.parquet").replace("\\", "/")

        for tname in selected_tables:
            if tname not in table_sources and doc_dir:
                table_sources[tname] = os.path.join(doc_dir, f"{tname}.parquet").replace("\\", "/")

        for sql in sql_candidates:
            stmt = sql.strip().rstrip(";")
            if not stmt:
                continue

            refs = re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", stmt, re.IGNORECASE)
            for table_ref in refs:
                table_l = table_ref.lower()
                if selected_tables and table_l in uploaded_tables and table_l not in selected_tables:
                    warnings.append(
                        f"⚠️ Table '{table_ref}' is referenced but not selected in AI table settings."
                    )

            # Binder-level validation catches wrong table/column names without running the query.
            # Must resolve bare table names → read_parquet() since tables aren't registered in DuckDB.
            if stmt.upper().startswith("SELECT") or stmt.upper().startswith("WITH"):
                try:
                    explain_stmt = stmt
                    for dname, ppath in table_sources.items():
                        # Only replace table names that appear directly after FROM or JOIN,
                        # never inside function call arguments (fixes read_parquet inside STRFTIME etc.)
                        pattern = r'(?i)(?<=(FROM|JOIN)\s)' + re.escape(dname) + r'\b'
                        explain_stmt = re.sub(
                            r'(?i)(\bFROM\s+|\bJOIN\s+)' + re.escape(dname) + r'\b',
                            lambda m, p=ppath: m.group(1) + f"read_parquet('{p}')",
                            explain_stmt,
                            flags=re.IGNORECASE,
                        )
                    editor.conn.execute(f"EXPLAIN {explain_stmt}")
                except Exception as e:
                    err_msg = str(e)
                    # Auto-fix: if QUALIFY is present without any window function, strip it
                    qual_upper = stmt.upper()
                    has_qualify = "QUALIFY" in qual_upper
                    has_over = " OVER " in qual_upper or " OVER(" in qual_upper
                    if has_qualify and not has_over:
                        try:
                            # Strip the QUALIFY clause (no window function = always wrong usage)
                            fixed_stmt = re.sub(
                                r'\s*QUALIFY\b.*?(?=\s*(?:GROUP\s+BY|ORDER\s+BY|LIMIT|HAVING)\b|\s*;?\s*$)',
                                '',
                                stmt,
                                flags=re.IGNORECASE | re.DOTALL,
                            ).strip()
                            # Re-resolve table names for EXPLAIN
                            fixed_explain = fixed_stmt
                            for dname2, pp2 in table_sources.items():
                                fixed_explain = re.sub(
                                    r'(?i)(\bFROM\s+|\bJOIN\s+)' + re.escape(dname2) + r'\b',
                                    lambda m, p=pp2: m.group(1) + f"read_parquet('{p}')",
                                    fixed_explain,
                                    flags=re.IGNORECASE,
                                )
                            editor.conn.execute(f"EXPLAIN {fixed_explain}")
                            warnings.append(
                                "⚠️ Invalid QUALIFY removed (QUALIFY requires a window function like "
                                "ROW_NUMBER() OVER (...)). Auto-corrected SQL:\n"
                                f"```sql\n{fixed_stmt}\n```"
                            )
                        except Exception:
                            warnings.append(f"⚠️ Schema validation: {err_msg}")
                    else:
                        warnings.append(f"⚠️ Schema validation: {err_msg}")

        # Deduplicate while preserving order
        dedup = []
        seen = set()
        for w in warnings:
            if w not in seen:
                dedup.append(w)
                seen.add(w)
        return dedup

    # ── Chat logic ────────────────────────────────────────────────────

    def _add_welcome_message(self):
        model_name = self.client.model_name
        desc = AVAILABLE_MODELS.get(model_name, {}).get("description", "")
        if not desc:
            # Custom / directly-placed model — find it in the full list
            for m in self.client.list_available_models():
                if m["key"] == model_name:
                    desc = m["description"]
                    break
        if not desc:
            # Last resort: derive a readable name from the key/filename
            desc = model_name.replace("custom:", "").replace("-", " ").replace("_", " ").replace(".gguf", "")
        self.chat_display.setHtml(
            "<div style='padding:12px;background:#e8f5e9;border-radius:4px;color:#1b5e20;'>"
            f"<b>🤖 Welcome to SimpliSQL AI Assistant</b><br>"
            f"Powered by local model: <b>{desc}</b><br><br>"
            "<i>You can ask me to:</i><br>"
            "• Generate SQL queries (simple or complex)<br>"
            "• Use subqueries, CTEs, window functions<br>"
            "• Explain SQL syntax and DuckDB features<br>"
            "• Optimize queries and suggest improvements<br>"
            "• Help with data analysis and workflows<br><br>"
            "<b>Note:</b> I can generate ANY valid DuckDB SQL query - don't hesitate to ask for complex operations!<br><br>"
            "All processing happens locally – no data leaves your machine."
            "</div>"
        )

    def send_message(self):
        if self._chat_thread is not None and self._chat_thread.isRunning():
            QMessageBox.information(self, "Generation In Progress", "Please wait for the current response or click Stop.")
            return

        user_text = self.user_input.text().strip()
        if not user_text:
            return

        if not self.client.is_loaded():
            QMessageBox.warning(self, "No Model",
                                "Please download and load a model first (click the button above).")
            return

        self.chat_display.append(
            f"<div style='margin:8px 0;padding:10px;background:#e3f2fd;"
            f"border-left:3px solid #2196F3;border-radius:4px;'>"
            f"<b>You:</b><br><div style='color:#000;margin-top:4px;'>"
            f"{user_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')}</div></div>"
        )
        self.user_input.clear()
        self.chat_display.append(
            "<div style='margin:6px 0;font-style:italic;color:#888;'>⏳ Thinking…</div>"
        )
        QApplication.processEvents()

        self._sync_selected_tables_to_parent()

        # ── Intent routing (Milestone 2) ──────────────────────────────
        mode_key = "auto"
        if hasattr(self, 'answer_mode_combo'):
            mode_key = self.answer_mode_combo.currentData() or "auto"
        if mode_key == "auto":
            mode_key = _classify_intent(user_text)
        self._last_answer_mode = mode_key  # used by _on_ai_response for auto-paste

        if mode_key == "python":
            system_prompt = self._build_python_system_prompt()
        else:
            system_prompt = self._build_system_prompt()

        messages = [{"role": "system", "content": system_prompt}]
        for turn in self.current_conversation[-6:]:
            messages.append({"role": "user", "content": turn["user"]})
            messages.append({"role": "assistant", "content": turn["ai"]})
        messages.append({"role": "user", "content": user_text})

        # Guardrail: trim history if the composed request is too large for the selected model.
        context_limit = self._get_model_context_limit()
        target_prompt_budget = max(1024, context_limit - 600)
        while len(messages) > 2 and self._estimate_messages_tokens(messages) > target_prompt_budget:
            # Remove oldest user/assistant turn pair but keep system + latest user.
            if len(messages) > 4:
                del messages[1:3]
            else:
                break

        if self._estimate_messages_tokens(messages) > target_prompt_budget:
            self.chat_display.append(
                "<div style='margin:8px 0;padding:10px;background:#fff8e1;"
                "border-left:3px solid #ffb300;border-radius:4px;'>"
                "<b style='color:#8d6e00;'>⚠️ Large prompt detected:</b><br>"
                "<div style='color:#000;margin-top:4px;'>"
                "Context was reduced to fit model limits. Consider selecting fewer tables in Settings."
                "</div></div>"
            )

        self._current_user_text = user_text
        self._generation_cancelled = False
        self._response_start_time = datetime.now()
        self._streaming_buffer = []          # accumulates streamed tokens
        self._streaming_block_inserted = False
        self._chat_thread = AIChatThread(self.client, messages, user_request=user_text)
        self._chat_thread.token_ready.connect(self._on_token_ready)
        self._chat_thread.response_ready.connect(self._on_ai_response)
        self._chat_thread.error_occurred.connect(self._on_ai_error)
        self._set_generation_controls(True)
        self._chat_thread.start()

    def _set_generation_controls(self, is_generating: bool):
        send_btn = self.findChild(QPushButton, "send_btn")
        if send_btn:
            send_btn.setEnabled(not is_generating)
        if hasattr(self, "stop_btn") and self.stop_btn:
            self.stop_btn.setEnabled(is_generating)

    def _stop_generation(self):
        if self._chat_thread is None or not self._chat_thread.isRunning():
            return

        self._generation_cancelled = True
        self._chat_thread.requestInterruption()
        # Best-effort immediate stop; if generation is inside a blocking model call,
        # we still ignore any late response in _on_ai_response.
        self._chat_thread.terminate()
        self._chat_thread.wait(300)

        html = self.chat_display.toHtml()
        html = html.replace("⏳ Thinking…", "")
        self.chat_display.setHtml(html)
        self.chat_display.append(
            "<div style='margin:8px 0;padding:10px;background:#fff8e1;"
            "border-left:3px solid #ffb300;border-radius:4px;'>"
            "<b style='color:#8d6e00;'>⏹️ Generation stopped.</b></div>"
        )
        self._set_generation_controls(False)

    def _on_token_ready(self, token: str):
        """Called for each streamed token – appends incrementally without full repaint."""
        if self._generation_cancelled:
            return

        self._streaming_buffer.append(token)

        if not self._streaming_block_inserted:
            # Remove the ⏳ Thinking… placeholder (one-time setHtml is acceptable here)
            html = self.chat_display.toHtml()
            html = html.replace("⏳ Thinking…", "")
            self.chat_display.setHtml(html)

            # Insert the AI header block using cursor (no full repaint)
            cursor = self.chat_display.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertHtml(
                "<div style='margin:8px 0;padding:10px;background:#f1f8e9;"
                "border-left:3px solid #8bc34a;border-radius:4px;'>"
                "<b style='color:#558b2f;'>AI:</b><br></div>"
            )
            # Move to end and remember this position as our write anchor
            cursor.movePosition(cursor.MoveOperation.End)
            self._stream_cursor_pos = cursor.position()
            self.chat_display.setTextCursor(cursor)
            self._streaming_block_inserted = True

        # Append only the new token text at the stored position (no setHtml)
        cursor = self.chat_display.textCursor()
        cursor.setPosition(self._stream_cursor_pos)
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(token)
        self._stream_cursor_pos = cursor.position()
        self.chat_display.setTextCursor(cursor)

        sb = self.chat_display.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_ai_response(self, response):
        self._set_generation_controls(False)

        if self._generation_cancelled:
            self._generation_cancelled = False
            self._chat_thread = None
            return

        schema_warnings = self._schema_validate_response(response)
        if schema_warnings:
            response = response + "\n\n---\n🔎 Schema checks:\n" + "\n".join(schema_warnings)

        # The streaming tokens were already rendered incrementally via _on_token_ready.
        # Only do a full render if streaming never started (fallback) or if the response
        # was modified after streaming (e.g. schema warnings appended).
        streamed_text = "".join(self._streaming_buffer)
        html = self.chat_display.toHtml()
        html = html.replace("⏳ Thinking…", "")
        self.chat_display.setHtml(html)

        if not self._streaming_block_inserted:
            # Streaming never fired — render the full response now
            safe = response.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
            self.chat_display.append(
                f"<div style='margin:8px 0;padding:10px;background:#f1f8e9;"
                f"border-left:3px solid #8bc34a;border-radius:4px;'>"
                f"<b style='color:#558b2f;'>AI:</b><br>"
                f"<div style='color:#000;margin-top:4px;white-space:pre-wrap;word-break:break-word;'>"
                f"{safe}</div>"
                f"</div>"
            )
        elif response != streamed_text:
            # Response was modified after streaming (schema warnings etc.) — append only the extra
            extra = response[len(streamed_text):].strip()
            if extra:
                safe_extra = extra.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
                self.chat_display.append(
                    f"<div style='margin:4px 0 8px 0;padding:8px;background:#fff8e1;"
                    f"border-left:3px solid #ffb300;border-radius:4px;color:#555;font-size:0.95em;'>"
                    f"{safe_extra}</div>"
                )
        
        sb = self.chat_display.verticalScrollBar()
        sb.setValue(sb.maximum())

        # Show response time
        elapsed = (datetime.now() - getattr(self, '_response_start_time', datetime.now())).total_seconds()
        self.chat_display.append(
            f"<div style='margin:0 0 6px 0;color:#999;font-size:0.85em;text-align:right;'>⏱ {elapsed:.1f}s</div>"
        )
        sb.setValue(sb.maximum())

        self.current_conversation.append({
            "user": getattr(self, '_current_user_text', ''),
            "ai": response,
            "timestamp": datetime.now().isoformat(),
        })

        # ── Auto-paste (Milestone 2) ──────────────────────────────────
        auto_paste = getattr(self, 'auto_paste_check', None)
        if auto_paste and auto_paste.isChecked():
            last_mode = getattr(self, '_last_answer_mode', 'auto')
            editor = self.parent_editor
            if last_mode == "python":
                py_candidates = self._extract_python_candidates(response)
                if py_candidates:
                    code = py_candidates[-1].strip()
                    if code and hasattr(editor, 'switch_notepad_mode'):
                        editor.switch_notepad_mode("python")
                        editor.sql_text.setPlainText(code)
                        self.chat_display.append(
                            "<div style='margin:4px 0 6px 0;padding:6px 10px;background:#e8f5e9;"
                            "border-left:3px solid #4caf50;border-radius:4px;color:#2e7d32;font-size:0.9em;'>"
                            "🐍 Python script auto-pasted to <b>Python Notepad</b>.</div>"
                        )
            elif last_mode == "sql":
                sql_candidates = self._extract_sql_candidates(response)
                if sql_candidates:
                    sql = sql_candidates[-1].strip()
                    if sql:
                        if hasattr(editor, 'switch_notepad_mode'):
                            editor.switch_notepad_mode("sql")
                        editor.sql_text.setPlainText(sql)
                        self.chat_display.append(
                            "<div style='margin:4px 0 6px 0;padding:6px 10px;background:#e3f2fd;"
                            "border-left:3px solid #2196F3;border-radius:4px;color:#0d47a1;font-size:0.9em;'>"
                            "🗃️ SQL query auto-pasted to <b>SQL Notepad</b>.</div>"
                        )
                else:
                    py_candidates = self._extract_python_candidates(response)
                    if py_candidates:
                        code = py_candidates[-1].strip()
                        if code and hasattr(editor, 'switch_notepad_mode'):
                            editor.switch_notepad_mode("python")
                            editor.sql_text.setPlainText(code)
                            self.chat_display.append(
                                "<div style='margin:4px 0 6px 0;padding:6px 10px;background:#fff8e1;"
                                "border-left:3px solid #ffb300;border-radius:4px;color:#8d6e00;font-size:0.9em;'>"
                                "↪ SQL not suitable. Python fallback auto-pasted to <b>Python Notepad</b>.</div>"
                            )

        self._chat_thread = None

    def _on_ai_error(self, error):
        self._set_generation_controls(False)
        html = self.chat_display.toHtml()
        html = html.replace("⏳ Thinking…", "")
        self.chat_display.setHtml(html)

        self.chat_display.append(
            f"<div style='margin:8px 0;padding:10px;background:#ffebee;"
            f"border-left:3px solid #f44336;border-radius:4px;'>"
            f"<b style='color:#c62828;'>Error:</b><br>"
            f"<div style='color:#000;margin-top:4px;'>{error}</div></div>"
        )
        self._chat_thread = None

    def _copy_last_sql_to_editor(self):
        """Extract the last SQL query from the chat and copy it to the main SQL editor."""
        text = self.chat_display.toPlainText()
        
        # Use the same extraction logic as schema validation for consistency
        sql_candidates = self._extract_sql_candidates(text)
        
        if sql_candidates:
            # Use the last SQL candidate (most recent)
            sql = sql_candidates[-1].strip()
            if sql:
                self.parent_editor.sql_text.setPlainText(sql)
                QMessageBox.information(self, "Copied", "SQL query copied to the main editor.")
                return
        
        # Fallback: try to find SQL in last AI response only
        lines = text.split('\n')
        ai_start = -1
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip().startswith('AI:'):
                ai_start = i
                break
        
        if ai_start == -1:
            QMessageBox.information(self, "No SQL Found", "No AI response found in the chat.")
            return
        
        # Extract SQL from the AI response section only
        ai_response = '\n'.join(lines[ai_start + 1:])
        ai_sql = self._extract_sql_candidates(ai_response)
        
        if ai_sql:
            sql = ai_sql[-1].strip()
            if sql:
                self.parent_editor.sql_text.setPlainText(sql)
                QMessageBox.information(self, "Copied", "SQL query copied to the main editor.")
                return
        
        QMessageBox.information(self, "No SQL Found", "No SQL code block found in the last AI response.")

    def _extract_python_candidates(self, response: str) -> list:
        return _extract_python_candidates_from_text(response)

    def _copy_last_python_to_notepad(self):
        """Extract last Python block from chat and paste it to the Python notepad."""
        text = self.chat_display.toPlainText()
        candidates = self._extract_python_candidates(text)
        if candidates:
            code = candidates[-1].strip()
            if code:
                editor = self.parent_editor
                # Switch to Python mode first
                if hasattr(editor, 'switch_notepad_mode'):
                    editor.switch_notepad_mode("python")
                editor.sql_text.setPlainText(code)
                QMessageBox.information(self, "Copied", "Python script copied to the Python notepad.")
                return
        QMessageBox.information(self, "No Python Found", "No Python code block found in the last AI response.")

    def _extract_query_paths(self, query: str) -> list:
        """Extract file paths mentioned in the query."""
        import re
        paths = []
        
        # Pattern for read_parquet('path'), read_csv_auto('path'), etc.
        pattern1 = r"read_\w+\('([^']+)'\)"
        for match in re.finditer(pattern1, query, re.IGNORECASE):
            path = match.group(1)
            if path and path.replace('\\', '/'):
                paths.append(path.replace('\\', '/'))
        
        # Pattern for FROM 'path' or SELECT * FROM 'path'
        pattern2 = r"FROM\s+'([^']+)'"
        for match in re.finditer(pattern2, query, re.IGNORECASE):
            path = match.group(1)
            if path:
                paths.append(path.replace('\\', '/'))
        
        return list(set(paths))  # Remove duplicates

    def _get_sample_from_paths(self, paths: list) -> list:
        """Get sample data from specific file paths."""
        samples = []
        editor = self.parent_editor
        
        if not hasattr(editor, 'conn'):
            return samples
        
        for path in paths:
            try:
                # Try to read and get sample from the file
                if path.endswith('.parquet'):
                    query = f"SELECT * FROM read_parquet('{path}') LIMIT 3"
                elif path.endswith('.csv'):
                    query = f"SELECT * FROM read_csv_auto('{path}') LIMIT 3"
                elif path.endswith('.json'):
                    query = f"SELECT * FROM read_json_auto('{path}') LIMIT 3"
                else:
                    # Try auto-detection
                    query = f"SELECT * FROM '{path}' LIMIT 3"
                
                rows = editor.conn.execute(query).fetchall()
                if rows:
                    # Get column names
                    col_query = f"DESCRIBE SELECT * FROM read_parquet('{path}')" if path.endswith('.parquet') else query.replace('LIMIT 3', 'LIMIT 0')
                    try:
                        cols = editor.conn.execute(col_query).fetchall()
                        col_names = [c[0] for c in cols]
                    except:
                        col_names = [f"col_{i}" for i in range(len(rows[0]))]
                    
                    sample_lines = [", ".join(col_names)]
                    for r in rows:
                        sample_lines.append(", ".join(str(v) for v in r))
                    samples.append(f"Sample data from '{path}':\n" + "\n".join(sample_lines))
            except Exception:
                pass
        
        return samples

    def _build_python_system_prompt(self) -> str:
        """Build a Python-focused system prompt that knows about DuckDB-first helpers."""
        editor = self.parent_editor
        selected_tables = self._get_selected_tables_for_ai()
        display_to_path = {}
        schema_lines = []

        if hasattr(editor, 'conn') and hasattr(editor, 'uploaded_display_names'):
            if hasattr(editor, 'uploaded_files') and editor.uploaded_files:
                for i, fpath in enumerate(editor.uploaded_files):
                    if i < len(editor.uploaded_display_names):
                        display_to_path[editor.uploaded_display_names[i]] = fpath

            def _parquet_source(tname):
                fpath = display_to_path.get(tname)
                if not fpath:
                    doc_dir = getattr(editor, 'doc_dir', '')
                    fpath = os.path.join(doc_dir, f"{tname}.parquet")
                return f"read_parquet('{fpath.replace(chr(92), '/')}')"

            for table_name in selected_tables:
                source = _parquet_source(table_name)
                try:
                    cols = editor.conn.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()
                    col_list = ", ".join(f"{c[0]} ({c[1]})" for c in cols)
                    schema_lines.append(f"  {table_name}: {col_list}")
                except Exception:
                    schema_lines.append(f"  {table_name}: (schema unavailable)")

        parts = []
        parts.append(
            "You are a Python data analysis assistant for SimpliSQL.\n"
            "The user runs Python scripts in a DuckDB-first sandbox. ALWAYS prefer DuckDB operations over\n"
            "loading full tables into pandas memory. Write concise, runnable Python scripts.\n\n"
            "AVAILABLE RUNTIME CONTEXT (already injected — never re-import or re-connect):\n"
            "  import pandas as pd          # pandas available\n"
            "  import numpy as np           # numpy available\n"
            "  import duckdb                # duckdb available\n"
            "  import matplotlib.pyplot as plt  # matplotlib available\n"
            "  conn  — live DuckDB connection with all uploaded tables readable via DuckDB\n"
            "  df    — current result DataFrame from last SQL query (may be None)\n\n"
            "DUCKDB-FIRST HELPER FUNCTIONS (available in scope, do not re-define them):\n"
            "  load_relation(table_name: str) -> duckdb.DuckDBPyRelation\n"
            "      Returns a lazy DuckDB relation for an uploaded table (no eager fetch).\n"
            "      Example: rel = load_relation('sales')\n\n"
            "  sql(query_str: str) -> duckdb.DuckDBPyRelation\n"
            "      Runs any DuckDB SQL and returns a lazy relation.\n"
            "      Example: rel = sql('SELECT region, SUM(amount) total FROM sales GROUP BY 1')\n\n"
            "  to_df(obj, limit=None) -> pd.DataFrame\n"
            "      Converts a DuckDB relation (or existing DataFrame) to pandas.\n"
            "      Shows a warning if > 1,000,000 rows; pass limit= to cap.\n"
            "      Example: df = to_df(rel, limit=100_000)\n\n"
            "  stream_df(query: str, chunk_size: int = 100_000) -> Generator[pd.DataFrame]\n"
            "      Yields pandas chunks for very large result sets.\n"
            "      Example: for chunk in stream_df('SELECT * FROM huge_table'): process(chunk)\n\n"
            "  read_path(path: str, sheet=0, **kwargs) -> pd.DataFrame\n"
            "      Read any file from disk. Auto-detects: csv, tsv, xlsx, json, xml, parquet, pkl.\n"
            "      Example: df = read_path(r'C:/data/sales.csv')\n"
            "               df = read_path(r'C:/data/report.xlsx', sheet='Q1')\n\n"
            "  read_zip(zip_path: str, inner_file=None, sheet=0, **kwargs) -> pd.DataFrame\n"
            "      Read a file inside a zip. Auto-picks first file if inner_file omitted.\n"
            "      Example: df = read_zip(r'C:/data/archive.zip', 'sales.csv')\n\n"
            "  save_result(df, path: str, sheet_name='Sheet1', index=False, **kwargs) -> str\n"
            "      Save DataFrame to any path. Format from extension: xlsx, csv, json, xml, parquet.\n"
            "      Creates parent dirs automatically. Returns absolute path written.\n"
            "      Example: save_result(result_df, r'C:/output/report.xlsx')\n\n"
            "OUTPUT VARIABLES (set these to render results in the UI):\n"
            "  result_df       — assign a DataFrame to display it in the results pane\n"
            "  result_relation — assign a DuckDB relation (auto-converted to DataFrame for display)\n"
            "  result_sql      — assign a SQL string to run and display\n\n"
            "RULES:\n"
            "- For uploaded tables: use load_relation() or sql() — NOT pd.read_parquet()/pd.read_csv().\n"
            "- For external disk files: use read_path() or read_zip().\n"
            "- For saving: use save_result() — handles format detection and directory creation.\n"
            "- NEVER call conn.execute(...).fetchdf() for large tables — use to_df() with a limit.\n"
            "- For plotting, use matplotlib or plotly; always call plt.tight_layout(); plt.show().\n"
            "- Assign result_df at the end so results appear in the UI.\n"
            "- Always write complete, runnable code — no pseudo-code or ellipsis."
        )

        # ── Milestone 3: advertise available DS/ML libraries ──────────
        try:
            from core.python_execution_manager import get_ds_library_status
            statuses = get_ds_library_status()
            available = [f"  {e['alias']} ({e['label']} v{e['version']})" for e in statuses if e["available"]]
            missing   = [f"  {e['label']} [pip install {e['pip_name']}]" for e in statuses if not e["available"]]
            lib_lines = []
            if available:
                lib_lines.append("Pre-injected (ready to use without import):\n" + "\n".join(available))
            if missing:
                lib_lines.append("Not installed (tell user to install via Settings > pip install):\n" + "\n".join(missing))
            if lib_lines:
                parts.append("DS/ML LIBRARIES IN SCOPE:\n" + "\n\n".join(lib_lines))
            # Also note sklearn sub-modules
            if any(e["alias"] == "sklearn" and e["available"] for e in statuses):
                parts.append(
                    "SCIKIT-LEARN SUB-MODULES (also pre-injected):\n"
                    "  linear_model, ensemble, tree, preprocessing,\n"
                    "  model_selection, metrics, decomposition, cluster, pipeline"
                )
        except Exception:
            pass

        if schema_lines:
            parts.append("AVAILABLE TABLES (use exact names with load_relation() or sql()):\n" + "\n".join(schema_lines))
        else:
            parts.append("No tables loaded yet. Tell the user to upload a file first.")

        return "\n\n".join(parts)

    def _build_system_prompt(self) -> str:
        """Build a compact, schema-aware system prompt for the AI model."""

        # ── 1. Gather table schema & mappings FIRST (most important data) ──
        schema_lines = []
        sample_parts = []
        table_mapping_lines = []
        editor = self.parent_editor
        selected_tables = self._get_selected_tables_for_ai()
        display_to_path = {}

        if hasattr(editor, 'conn') and hasattr(editor, 'uploaded_display_names'):
            # Build display-name → file-path lookup
            if hasattr(editor, 'uploaded_files') and editor.uploaded_files:
                for i, fpath in enumerate(editor.uploaded_files):
                    if i < len(editor.uploaded_display_names):
                        display_to_path[editor.uploaded_display_names[i]] = fpath

            # Helper: resolve a display name to a read_parquet() source expression.
            # Tables are NOT registered in DuckDB; they're parquet files on disk.
            def _parquet_source(tname):
                fpath = display_to_path.get(tname)
                if not fpath:
                    doc_dir = getattr(editor, 'doc_dir', '')
                    fpath = os.path.join(doc_dir, f"{tname}.parquet")
                return f"read_parquet('{fpath.replace(chr(92), '/')}')"

            for table_name in selected_tables:
                source = _parquet_source(table_name)
                # Schema
                try:
                    cols = editor.conn.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()
                    col_list = ", ".join(f"{c[0]} ({c[1]})" for c in cols)
                    schema_lines.append(f"  {table_name}: {col_list}")
                except Exception:
                    schema_lines.append(f"  {table_name}: (schema unavailable)")

                # File mapping
                fpath = display_to_path.get(table_name)
                if fpath:
                    table_mapping_lines.append(f"  {table_name} -> {fpath.replace(chr(92), '/')}")

                # Sample rows (max 3 per table, compact CSV format)
                try:
                    col_names = [d[0] for d in editor.conn.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()]
                    rows = editor.conn.execute(f"SELECT * FROM {source} LIMIT 3").fetchall()
                    if rows:
                        header = ", ".join(col_names)
                        data_lines = [", ".join(str(v) for v in r) for r in rows]
                        sample_parts.append(f"{table_name}:\n  {header}\n  " + "\n  ".join(data_lines))
                except Exception:
                    pass

        # ── 2. Build compact system prompt ──
        parts = []

        # Core identity + critical rules (kept tight)
        parts.append(
            "You are a DuckDB SQL assistant for SimpliSQL.\n"
            "RULES:\n"
            "- ONLY use tables/columns listed below. Never invent names.\n"
            "- Use DuckDB syntax.\n"
            "- For date/time questions, ALWAYS use DuckDB date/time functions and INTERVAL syntax.\n"
            "- Prefer explicit casting for mixed text/date columns: TRY_CAST(col AS DATE) or TRY_CAST(col AS TIMESTAMP).\n"
            "- 'total'/'sum' requests MUST use SUM() aggregate. 'count' uses COUNT(). 'average' uses AVG().\n"
            "- When grouping, all non-aggregated columns MUST appear in GROUP BY.\n"
            "- QUALIFY is ONLY for filtering window function results (e.g. ROW_NUMBER() OVER (...)). NEVER use QUALIFY without a window function (OVER keyword). For normal filters use WHERE or HAVING.\n"
            "- QUALIFY must come AFTER GROUP BY and HAVING (clause order: FROM→WHERE→GROUP BY→HAVING→QUALIFY→ORDER BY).\n"
            "- Use simple table names in queries, not file paths or read_parquet().\n"
            "- If a table is not listed, tell the user to upload it.\n"
            "- If the request is not feasible in pure SQL (forecasting/prediction/ML), DO NOT refuse. Return Python using SimpliSQL helpers (load_relation/sql/to_df/stream_df) and set result_df.\n"
            "- 'last'/'first' = ordering (ROW_NUMBER, arg_max), NOT MAX/MIN.\n"
            "- 'all X last Y' = PARTITION BY X ORDER BY ... DESC with ROW_NUMBER()=1.\n"
            "- DuckDB can query files directly: SELECT * FROM 'path/file.csv'\n"
            "GROUPING SIGNALS:\n"
            "- 'each X', 'per X', 'for every X', 'by X level' = needs GROUP BY X or PARTITION BY X.\n"
            "- 'last/first per group' = use ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...) with QUALIFY or subquery.\n"
            "- LIMIT N limits total rows, NOT rows per group. For N per group, use window functions."
        )

        # Table schemas (essential - AI needs this to write correct queries)
        if schema_lines:
            parts.append("TABLES:\n" + "\n".join(schema_lines))
        else:
            parts.append("No tables loaded. User can query files by path.")

        # Table-to-file mapping (single unified section, not duplicated)
        if table_mapping_lines:
            parts.append("TABLE PATHS:\n" + "\n".join(table_mapping_lines))

        # Sample data (budget-controlled)
        context_limit = self._get_model_context_limit()
        prompt_budget = max(1200, context_limit - 700)

        if sample_parts:
            sample_block = "SAMPLES (3 rows each):\n" + "\n".join(sample_parts)
            candidate = "\n\n".join(parts) + "\n\n" + sample_block
            if self._estimate_tokens(candidate) <= prompt_budget:
                parts.append(sample_block)

        # DuckDB-specific cheat sheet (only differences from standard SQL)
        parts.append(
            "DUCKDB QUICK REFERENCE:\n"
            "- QUALIFY: ONLY for window function results. Example: QUALIFY ROW_NUMBER() OVER (PARTITION BY x ORDER BY y DESC) = 1\n"
            "  DO NOT use QUALIFY for plain column filters — use WHERE or HAVING instead.\n"
            "- arg_max(val, order), arg_min(val, order): value at max/min of order col\n"
            "- DATE/TIME (DuckDB):\n"
            "  date_trunc('month', ts_col), extract('year' FROM ts_col), strftime(ts_col, '%Y-%m')\n"
            "  current_date, current_timestamp, now()\n"
            "  date_diff('day', start_date, end_date), date_add(date_col, INTERVAL 7 DAY), date_sub('day', start_date, end_date)\n"
            "  date_col >= current_date - INTERVAL 30 DAY\n"
            "- Avoid non-DuckDB dialect functions: DATE_FORMAT(), TIMESTAMPDIFF(), GETDATE(), TO_CHAR(), ILIKE ANY\n"
            "- TRY_CAST(x AS type): safe cast returning NULL on error\n"
            "- SELECT * EXCLUDE (col), SELECT * REPLACE (expr AS col)\n"
            "- PIVOT / UNPIVOT, FILTER clause for conditional aggregation\n"
            "- read_parquet(), read_csv_auto(), read_json_auto() for file queries\n"
            "- FILE_BASENAME(p), FILE_DIRNAME(p), FILE_NAME_NO_EXT(p), FILE_EXTENSION(p)"
        )

        base = "\n\n".join(parts)

        # Schema budget guardrail: trim if still too large
        if self._estimate_tokens(base) > prompt_budget and schema_lines:
            # Keep as many schemas as fit
            trimmed = []
            for line in schema_lines:
                trial = base.replace("\n".join(schema_lines), "\n".join(trimmed + [line]))
                if self._estimate_tokens(trial) > prompt_budget:
                    break
                trimmed.append(line)
            if not trimmed:
                trimmed = [schema_lines[0]]
            omitted = len(schema_lines) - len(trimmed)
            if omitted > 0:
                trimmed.append(f"  ... {omitted} more tables omitted (select fewer in Settings)")
            base = base.replace("\n".join(schema_lines), "\n".join(trimmed))

        # Include current editor query if checkbox is on
        if self.context_query_check.isChecked():
            query = editor.sql_text.toPlainText().strip()
            if query:
                base += f"\n\nCURRENT QUERY:\n{query}"
                query_paths = self._extract_query_paths(query)
                if query_paths:
                    samples = self._get_sample_from_paths(query_paths)
                    if samples:
                        base += "\n" + "\n".join(samples)

        return base

    def clear_chat(self):
        reply = QMessageBox.question(self, "Clear Chat", "Clear chat history?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.chat_display.clear()
            self.current_conversation.clear()
            if self.client.is_loaded():
                self._add_welcome_message()

    def closeEvent(self, event):
        if self._force_close:
            event.accept()
        else:
            event.ignore()
            self.hide()
