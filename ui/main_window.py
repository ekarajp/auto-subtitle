from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLocale, QSignalBlocker, Qt, QThread
from PySide6.QtGui import QAction, QColor, QFont, QFontDatabase, QFontMetrics, QImage, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.project_config import ProjectConfig, load_project_config, save_project_config
from core.audio_analysis import detect_silences
from core.preview_renderer import PreviewRenderError, render_accurate_preview_frame
from core.renderer import ensure_ffmpeg
from core.style_preset import (
    ALIGNMENTS,
    SAFE_AREA_MODES,
    STYLE_PRESETS,
    SubtitleStyle,
    auto_bottom_margin,
    auto_horizontal_margin,
    style_with_auto_size,
    style_with_overrides,
)
from core.subtitle_models import SubtitleCue, SubtitleDocument, SubtitleParseError
from core.subtitle_arranger import arrange_cues_for_readability
from core.subtitle_exporter import SubtitleExportError, export_subtitle_file
from core.subtitle_parser import SUPPORTED_FORMATS, detect_subtitle_format, parse_subtitle_file
from core.subtitle_timing import cleanup_subtitle_timings
from core.speech_sync import SpeechSyncOptions
from core.video_info import VideoInfo, VideoProbeError, probe_video
from core.subtitle_layout import wrap_subtitle_text
from ui.preview_widget import SubtitlePreviewWidget
from ui.render_worker import RenderWorker
from ui.speech_sync_worker import SpeechSyncWorker
from utils.timecode import format_timecode, parse_timecode, pretty_duration


ARABIC_DIGIT_LOCALE = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
PREFERRED_FONTS = [
    "Tahoma",
    "Arial",
    "Segoe UI",
    "Noto Sans Thai",
    "Leelawadee UI",
    "Cordia New",
    "Angsana New",
    "Georgia",
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Smart Subtitle")
        self.setMinimumSize(1080, 720)

        self.video_info: VideoInfo | None = None
        self.subtitle_doc: SubtitleDocument | None = None
        self.render_thread: QThread | None = None
        self.render_worker: RenderWorker | None = None
        self.speech_thread: QThread | None = None
        self.speech_worker: SpeechSyncWorker | None = None
        self._updating_table = False
        self._updating_text_editor = False
        self._updating_cue_style_controls = False
        self._selecting_from_playback = False
        self._restoring_history = False
        self._history: list[list[tuple[float, float, str, dict[str, object]]]] = []
        self._history_index = -1

        self._build_actions()
        self._build_ui()
        self._force_arabic_digit_locale()
        self._connect_style_signals()
        self._load_style_to_controls(SubtitleStyle())
        self._apply_light_stylesheet()

    def _build_actions(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        open_action = QAction("Open Project Config...", self)
        open_action.triggered.connect(self.load_project_config)
        file_menu.addAction(open_action)

        save_action = QAction("Save Project Config...", self)
        save_action.triggered.connect(self.save_project_config)
        file_menu.addAction(save_action)

        edit_menu = self.menuBar().addMenu("&Edit")

        undo_action = QAction("Undo", self)
        undo_action.setShortcuts(QKeySequence.keyBindings(QKeySequence.StandardKey.Undo))
        undo_action.triggered.connect(self.undo)
        edit_menu.addAction(undo_action)

        redo_action = QAction("Redo", self)
        redo_shortcuts = QKeySequence.keyBindings(QKeySequence.StandardKey.Redo)
        redo_shortcuts.append(QKeySequence("Ctrl+Shift+Z"))
        redo_action.setShortcuts(redo_shortcuts)
        redo_action.triggered.connect(self.redo)
        edit_menu.addAction(redo_action)

    def undo(self) -> None:
        focus = self.focusWidget()
        if isinstance(focus, QTextEdit) and focus.document().isUndoAvailable():
            focus.undo()
            return
        if isinstance(focus, QLineEdit) and focus.isUndoAvailable():
            focus.undo()
            return
        if self._history_index <= 0:
            self.log("Undo: nothing to undo.")
            return
        self._history_index -= 1
        self._restore_subtitle_snapshot(self._history[self._history_index])
        self.log("Undo subtitle edit.")

    def redo(self) -> None:
        focus = self.focusWidget()
        if isinstance(focus, QTextEdit) and focus.document().isRedoAvailable():
            focus.redo()
            return
        if isinstance(focus, QLineEdit) and focus.isRedoAvailable():
            focus.redo()
            return
        if self._history_index >= len(self._history) - 1:
            self.log("Redo: nothing to redo.")
            return
        self._history_index += 1
        self._restore_subtitle_snapshot(self._history[self._history_index])
        self.log("Redo subtitle edit.")

    def _push_history(self) -> None:
        if self._restoring_history or not self.subtitle_doc:
            return
        snapshot = self._subtitle_snapshot()
        if self._history_index >= 0 and self._history[self._history_index] == snapshot:
            return
        if self._history_index < len(self._history) - 1:
            self._history = self._history[: self._history_index + 1]
        self._history.append(snapshot)
        if len(self._history) > 100:
            self._history.pop(0)
        self._history_index = len(self._history) - 1

    def _subtitle_snapshot(self) -> list[tuple[float, float, str, dict[str, object]]]:
        if not self.subtitle_doc:
            return []
        return [
            (cue.start, cue.end, cue.text, dict(cue.style_overrides))
            for cue in self.subtitle_doc.cues
        ]

    def _restore_subtitle_snapshot(self, snapshot: list[tuple[float, float, str, dict[str, object]]]) -> None:
        self._restoring_history = True
        try:
            source_format = self.subtitle_doc.source_format if self.subtitle_doc else "edited"
            cues = [
                SubtitleCue(index + 1, start, end, text, style_overrides=overrides)
                for index, (start, end, text, overrides) in enumerate(snapshot)
            ]
            self.subtitle_doc = SubtitleDocument(cues=cues, source_format=source_format)
            self._populate_subtitle_table()
            self._refresh_preview_data()
            if cues:
                self.subtitle_table.selectRow(min(self.subtitle_table.currentRow(), len(cues) - 1) if self.subtitle_table.currentRow() >= 0 else 0)
            else:
                self.subtitle_text_editor.clear()
            self._update_summary()
        finally:
            self._restoring_history = False

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter, 1)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setMinimumWidth(560)
        left_content = QWidget()
        left_scroll.setWidget(left_content)
        left_layout = QVBoxLayout(left_content)

        left_layout.addWidget(self._build_video_group())
        left_layout.addWidget(self._build_subtitle_group())
        left_layout.addWidget(self._build_style_group())
        left_layout.addStretch(1)

        right_panel = QWidget()
        right_panel.setMinimumWidth(480)
        right_layout = QVBoxLayout(right_panel)
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.addWidget(self._build_preview_group())
        right_splitter.addWidget(self._build_output_group())
        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 2)
        right_splitter.setSizes([430, 260])
        right_layout.addWidget(right_splitter, 1)

        splitter.addWidget(left_scroll)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([580, 500])

    def _build_video_group(self) -> QGroupBox:
        group = QGroupBox("1. Video Input")
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        self.video_path_edit = QLineEdit()
        self.video_path_edit.setPlaceholderText("Choose a video file...")
        browse = QPushButton("Select Video")
        browse.clicked.connect(self.select_video)
        row.addWidget(self.video_path_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)

        info_grid = QGridLayout()
        self.video_labels: dict[str, QLabel] = {}
        labels = [
            ("width", "Width"),
            ("height", "Height"),
            ("fps", "FPS"),
            ("duration", "Duration"),
            ("aspect", "Aspect Ratio"),
            ("orientation", "Orientation"),
        ]
        for row_index, (key, label) in enumerate(labels):
            info_grid.addWidget(QLabel(f"{label}:"), row_index // 2, (row_index % 2) * 2)
            value = QLabel("-")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.video_labels[key] = value
            info_grid.addWidget(value, row_index // 2, (row_index % 2) * 2 + 1)
        layout.addLayout(info_grid)
        return group

    def _build_subtitle_group(self) -> QGroupBox:
        group = QGroupBox("2. Subtitle Input")
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        self.subtitle_path_edit = QLineEdit()
        self.subtitle_path_edit.setPlaceholderText("Choose TXT, SRT, VTT, CSV, or JSON...")
        browse = QPushButton("Select Subtitle")
        browse.clicked.connect(self.select_subtitle)
        row.addWidget(self.subtitle_path_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)

        options = QHBoxLayout()
        self.format_combo = QComboBox()
        self.format_combo.addItem("Auto Detect", "auto")
        for fmt in SUPPORTED_FORMATS:
            self.format_combo.addItem(fmt.upper(), fmt)

        self.txt_mode_combo = QComboBox()
        self.txt_mode_combo.addItem("TXT Auto", "auto")
        self.txt_mode_combo.addItem("TXT Plain: spread across video", "plain_auto")
        self.txt_mode_combo.addItem("TXT Plain: fixed duration", "plain_fixed")
        self.txt_mode_combo.addItem("TXT Timestamped", "timestamped")

        self.txt_duration_spin = QDoubleSpinBox()
        self.txt_duration_spin.setRange(0.1, 60.0)
        self.txt_duration_spin.setSingleStep(0.5)
        self.txt_duration_spin.setValue(3.0)
        self.txt_duration_spin.setSuffix(" sec")

        parse_button = QPushButton("Parse / Preview")
        parse_button.clicked.connect(self.parse_subtitles)

        options.addWidget(QLabel("Format"))
        options.addWidget(self.format_combo)
        options.addWidget(self.txt_mode_combo)
        layout.addLayout(options)

        parse_row = QHBoxLayout()
        parse_row.addWidget(QLabel("Line duration"))
        parse_row.addWidget(self.txt_duration_spin)
        parse_row.addWidget(parse_button)
        parse_row.addStretch(1)
        layout.addLayout(parse_row)

        timing_row = QHBoxLayout()
        self.hold_after_spin = QDoubleSpinBox()
        self.hold_after_spin.setRange(0.0, 3.0)
        self.hold_after_spin.setSingleStep(0.05)
        self.hold_after_spin.setDecimals(2)
        self.hold_after_spin.setValue(0.35)
        self.hold_after_spin.setSuffix(" sec")

        self.min_display_spin = QDoubleSpinBox()
        self.min_display_spin.setRange(0.2, 10.0)
        self.min_display_spin.setSingleStep(0.1)
        self.min_display_spin.setDecimals(1)
        self.min_display_spin.setValue(0.9)
        self.min_display_spin.setSuffix(" sec")

        self.max_display_spin = QDoubleSpinBox()
        self.max_display_spin.setRange(1.0, 20.0)
        self.max_display_spin.setSingleStep(0.5)
        self.max_display_spin.setDecimals(1)
        self.max_display_spin.setValue(6.0)
        self.max_display_spin.setSuffix(" sec")

        self.use_silence_detect_check = QCheckBox("Detect audio silence")
        self.use_silence_detect_check.setChecked(True)

        auto_timing_button = QPushButton("Auto Timing Cleanup")
        auto_timing_button.setToolTip(
            "Trim subtitle end times after speech pauses, and keep each cue inside min/max display duration."
        )
        auto_timing_button.clicked.connect(self.auto_cleanup_timings)
        timing_row.addWidget(self.use_silence_detect_check)
        timing_row.addWidget(QLabel("Hold after speech"))
        timing_row.addWidget(self.hold_after_spin)
        layout.addLayout(timing_row)

        timing_row_2 = QHBoxLayout()
        timing_row_2.addWidget(QLabel("Min"))
        timing_row_2.addWidget(self.min_display_spin)
        timing_row_2.addWidget(QLabel("Max"))
        timing_row_2.addWidget(self.max_display_spin)
        timing_row_2.addWidget(auto_timing_button)
        timing_row_2.addStretch(1)
        layout.addLayout(timing_row_2)

        speech_row = QHBoxLayout()
        self.speech_model_combo = QComboBox()
        self.speech_model_combo.addItems(
            [
                "large-v3",
                "large-v3-turbo",
                "large",
                "large-v2",
                "large-v1",
                "distil-large-v3",
                "distil-large-v2",
                "medium",
                "medium.en",
                "small",
                "small.en",
                "base",
                "base.en",
                "tiny",
                "tiny.en",
            ]
        )
        self.speech_model_combo.setCurrentText("large-v3")
        self.speech_language_combo = QComboBox()
        self.speech_language_combo.addItem("Auto language", "")
        self.speech_language_combo.addItem("Thai", "th")
        self.speech_language_combo.addItem("English", "en")
        self.speech_compute_combo = QComboBox()
        self.speech_compute_combo.addItems(["auto", "float16", "int8_float16", "int8", "float32"])
        self.speech_beam_spin = QSpinBox()
        self.speech_beam_spin.setRange(1, 10)
        self.speech_beam_spin.setValue(5)
        self.speech_sync_button = QPushButton("Auto Speech Sync")
        self.speech_sync_button.setToolTip(
            "Optional: uses faster-whisper to listen to video audio and generate synced subtitle cues."
        )
        self.speech_sync_button.clicked.connect(self.start_speech_sync)
        speech_row.addWidget(QLabel("Speech model"))
        speech_row.addWidget(self.speech_model_combo)
        speech_row.addWidget(self.speech_language_combo)
        speech_row.addWidget(QLabel("Compute"))
        speech_row.addWidget(self.speech_compute_combo)
        speech_row.addWidget(QLabel("Beam"))
        speech_row.addWidget(self.speech_beam_spin)
        speech_row.addWidget(self.speech_sync_button)
        speech_row.addStretch(1)
        layout.addLayout(speech_row)

        edit_row = QHBoxLayout()
        apply_button = QPushButton("Apply Edits")
        apply_button.clicked.connect(self.apply_table_edits)
        add_button = QPushButton("Add Subtitle")
        add_button.clicked.connect(self.add_subtitle_row)
        delete_button = QPushButton("Delete Selected")
        delete_button.clicked.connect(self.delete_selected_subtitles)
        preview_button = QPushButton("Preview Selected")
        preview_button.clicked.connect(self.preview_selected_subtitle)
        auto_arrange_button = QPushButton("Auto Arrange Text")
        auto_arrange_button.setToolTip(
            "Press this after changing Max width or Max lines to re-wrap every subtitle and check edge safety."
        )
        auto_arrange_button.clicked.connect(self.auto_arrange_subtitle_text)
        edit_row.addWidget(apply_button)
        edit_row.addWidget(add_button)
        edit_row.addWidget(delete_button)
        edit_row.addStretch(1)
        layout.addLayout(edit_row)

        edit_row_2 = QHBoxLayout()
        edit_row_2.addWidget(preview_button)
        edit_row_2.addWidget(auto_arrange_button)
        edit_row_2.addStretch(1)
        layout.addLayout(edit_row_2)

        self.subtitle_table = QTableWidget(0, 4)
        self.subtitle_table.setHorizontalHeaderLabels(["#", "Start", "End", "Text"])
        self.subtitle_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.subtitle_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.subtitle_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.subtitle_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.subtitle_table.verticalHeader().setVisible(False)
        self.subtitle_table.setMinimumHeight(220)
        self.subtitle_table.itemChanged.connect(self._subtitle_table_changed)
        self.subtitle_table.itemSelectionChanged.connect(self.preview_selected_subtitle)
        layout.addWidget(self.subtitle_table)

        text_editor_row = QVBoxLayout()
        text_editor_header = QHBoxLayout()
        text_editor_header.addWidget(QLabel("Selected subtitle text / line breaks"))
        apply_text_button = QPushButton("Apply Text")
        apply_text_button.clicked.connect(self.apply_text_editor_to_selected)
        text_editor_header.addStretch(1)
        text_editor_header.addWidget(apply_text_button)
        text_editor_row.addLayout(text_editor_header)

        self.subtitle_text_editor = QTextEdit()
        self.subtitle_text_editor.setPlaceholderText("Edit selected subtitle text here. Press Enter for a manual line break.")
        self.subtitle_text_editor.setMinimumHeight(80)
        self.subtitle_text_editor.textChanged.connect(self._subtitle_text_editor_changed)
        text_editor_row.addWidget(self.subtitle_text_editor)
        layout.addLayout(text_editor_row)

        cue_style_group = QGroupBox("Selected Subtitle Manual Style")
        cue_style_form = QFormLayout(cue_style_group)
        self.cue_style_override_check = QCheckBox("Use manual style for selected subtitle")
        cue_style_form.addRow(self.cue_style_override_check)

        self.cue_alignment_combo = QComboBox()
        for key, label in ALIGNMENTS.items():
            self.cue_alignment_combo.addItem(label, key)
        cue_style_form.addRow("Alignment", self.cue_alignment_combo)

        cue_position_row = QHBoxLayout()
        self.cue_text_position_combo = QComboBox()
        self.cue_text_position_combo.addItem("Auto", "auto")
        self.cue_text_position_combo.addItem("Custom", "custom")
        self.cue_custom_x_spin = QSpinBox()
        self.cue_custom_x_spin.setRange(0, 100)
        self.cue_custom_x_spin.setSuffix("% X")
        self.cue_custom_y_spin = QSpinBox()
        self.cue_custom_y_spin.setRange(0, 100)
        self.cue_custom_y_spin.setSuffix("% Y")
        cue_position_row.addWidget(self.cue_text_position_combo)
        cue_position_row.addWidget(self.cue_custom_x_spin)
        cue_position_row.addWidget(self.cue_custom_y_spin)
        cue_style_form.addRow("Position", cue_position_row)

        self.cue_font_size_spin = QSpinBox()
        self.cue_font_size_spin.setRange(8, 180)
        cue_style_form.addRow("Font size", self.cue_font_size_spin)

        self.cue_max_width_spin = QSpinBox()
        self.cue_max_width_spin.setRange(20, 100)
        self.cue_max_width_spin.setSuffix("%")
        cue_style_form.addRow("Max width", self.cue_max_width_spin)

        self.cue_alignment_reference_label = QLabel("Reference: bottom edge + center")
        cue_style_form.addRow("Alignment reference", self.cue_alignment_reference_label)

        self.cue_alignment_offset_mode_combo = QComboBox()
        self.cue_alignment_offset_mode_combo.addItem("Auto", "auto")
        self.cue_alignment_offset_mode_combo.addItem("Manual", "manual")
        cue_style_form.addRow("Offset mode", self.cue_alignment_offset_mode_combo)

        self.cue_horizontal_margin_spin = QSpinBox()
        self.cue_horizontal_margin_spin.setRange(0, 2000)
        self.cue_horizontal_margin_spin.setSuffix(" px")
        cue_style_form.addRow("Horizontal offset", self.cue_horizontal_margin_spin)

        self.cue_vertical_margin_spin = QSpinBox()
        self.cue_vertical_margin_spin.setRange(0, 2000)
        self.cue_vertical_margin_spin.setSuffix(" px")
        cue_style_form.addRow("Vertical offset", self.cue_vertical_margin_spin)

        self.cue_auto_alignment_offset_label = QLabel("Auto X: - | Auto Y: -")
        cue_style_form.addRow("Auto offset", self.cue_auto_alignment_offset_label)

        clear_cue_style_button = QPushButton("Clear Manual Style")
        clear_cue_style_button.clicked.connect(self.clear_selected_cue_style)
        cue_style_form.addRow(clear_cue_style_button)
        layout.addWidget(cue_style_group)
        return group

    def _build_style_group(self) -> QGroupBox:
        group = QGroupBox("3. Style Settings")
        layout = QVBoxLayout(group)

        preset_row = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(STYLE_PRESETS.keys())
        auto_size_button = QPushButton("Auto Size")
        auto_size_button.clicked.connect(self.apply_auto_size)
        preset_row.addWidget(QLabel("Preset"))
        preset_row.addWidget(self.preset_combo, 1)
        preset_row.addWidget(auto_size_button)
        layout.addLayout(preset_row)

        form = QFormLayout()
        self.font_combo = self._build_font_family_combo()
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 180)
        self.font_size_spin.setValue(48)
        form.addRow("Font family", self.font_combo)
        form.addRow("Font size", self.font_size_spin)

        color_row = QHBoxLayout()
        self.font_color_button = self._make_color_button("#FFFFFF")
        self.shadow_color_button = self._make_color_button("#000000")
        color_row.addWidget(QLabel("Text"))
        color_row.addWidget(self.font_color_button)
        color_row.addWidget(QLabel("Shadow"))
        color_row.addWidget(self.shadow_color_button)
        form.addRow("Colors", color_row)

        stroke_row = QHBoxLayout()
        self.stroke_check = QCheckBox("Enabled")
        self.stroke_check.setChecked(True)
        self.stroke_color_button = self._make_color_button("#000000")
        self.stroke_width_spin = QDoubleSpinBox()
        self.stroke_width_spin.setRange(0, 12)
        self.stroke_width_spin.setSingleStep(0.5)
        self.stroke_width_spin.setValue(3)
        stroke_row.addWidget(self.stroke_check)
        stroke_row.addWidget(QLabel("Color"))
        stroke_row.addWidget(self.stroke_color_button)
        stroke_row.addWidget(QLabel("Width"))
        stroke_row.addWidget(self.stroke_width_spin)
        form.addRow("Stroke", stroke_row)

        shadow_row = QHBoxLayout()
        self.shadow_check = QCheckBox("Enabled")
        self.shadow_check.setChecked(True)
        self.shadow_offset_spin = QDoubleSpinBox()
        self.shadow_offset_spin.setRange(0, 20)
        self.shadow_offset_spin.setSingleStep(0.5)
        self.shadow_offset_spin.setValue(2)
        self.shadow_blur_spin = QDoubleSpinBox()
        self.shadow_blur_spin.setRange(0, 8)
        self.shadow_blur_spin.setSingleStep(0.5)
        shadow_row.addWidget(self.shadow_check)
        shadow_row.addWidget(QLabel("Offset"))
        shadow_row.addWidget(self.shadow_offset_spin)
        shadow_row.addWidget(QLabel("Blur"))
        shadow_row.addWidget(self.shadow_blur_spin)
        form.addRow("Shadow", shadow_row)

        background_row = QHBoxLayout()
        self.background_check = QCheckBox("Box")
        self.background_color_button = self._make_color_button("#000000")
        self.background_opacity_spin = QSpinBox()
        self.background_opacity_spin.setRange(0, 100)
        self.background_opacity_spin.setValue(55)
        self.background_opacity_spin.setSuffix("%")
        background_row.addWidget(self.background_check)
        background_row.addWidget(self.background_color_button)
        background_row.addWidget(QLabel("Opacity"))
        background_row.addWidget(self.background_opacity_spin)
        form.addRow("Background", background_row)

        self.alignment_combo = QComboBox()
        for key, label in ALIGNMENTS.items():
            self.alignment_combo.addItem(label, key)
        form.addRow("Alignment", self.alignment_combo)

        self.alignment_reference_label = QLabel("Reference: bottom edge + center")
        form.addRow("Alignment reference", self.alignment_reference_label)

        self.alignment_offset_mode_combo = QComboBox()
        self.alignment_offset_mode_combo.addItem("Auto", "auto")
        self.alignment_offset_mode_combo.addItem("Manual", "manual")
        form.addRow("Offset mode", self.alignment_offset_mode_combo)

        self.safe_area_combo = QComboBox()
        for mode in SAFE_AREA_MODES:
            self.safe_area_combo.addItem(mode.title(), mode)
        form.addRow("Safe area preset", self.safe_area_combo)

        self.horizontal_margin_spin = QSpinBox()
        self.horizontal_margin_spin.setRange(0, 2000)
        self.horizontal_margin_spin.setSuffix(" px")
        self.horizontal_margin_spin.setToolTip("Manual distance from the left/right edge for left/right alignment.")
        form.addRow("Horizontal offset", self.horizontal_margin_spin)

        self.bottom_margin_spin = QSpinBox()
        self.bottom_margin_spin.setRange(0, 2000)
        self.bottom_margin_spin.setSuffix(" px")
        self.bottom_margin_spin.setToolTip("Manual distance from the top/bottom edge for top/bottom alignment.")
        form.addRow("Vertical offset", self.bottom_margin_spin)

        self.auto_alignment_offset_label = QLabel("Auto X: - | Auto Y: -")
        form.addRow("Auto offset", self.auto_alignment_offset_label)

        self.custom_safe_spin = QSpinBox()
        self.custom_safe_spin.setRange(1, 30)
        self.custom_safe_spin.setValue(8)
        self.custom_safe_spin.setSuffix("%")
        form.addRow("Custom safe area", self.custom_safe_spin)

        self.line_spacing_spin = QSpinBox()
        self.line_spacing_spin.setRange(0, 80)
        self.line_spacing_spin.setValue(4)
        self.line_spacing_spin.setSuffix(" px")
        form.addRow("Line spacing", self.line_spacing_spin)

        self.max_width_spin = QSpinBox()
        self.max_width_spin.setRange(20, 100)
        self.max_width_spin.setValue(88)
        self.max_width_spin.setSuffix("%")
        self.max_width_spin.setToolTip("How much of the video width subtitles may use. Higher values make each line longer.")
        form.addRow("Max width", self.max_width_spin)

        self.max_lines_spin = QSpinBox()
        self.max_lines_spin.setRange(1, 6)
        self.max_lines_spin.setValue(2)
        self.max_lines_spin.setToolTip("Default is 2 lines. Auto Arrange splits long subtitles into more cues instead of showing more lines.")
        form.addRow("Max lines", self.max_lines_spin)

        position_row = QHBoxLayout()
        self.text_position_combo = QComboBox()
        self.text_position_combo.addItem("Auto", "auto")
        self.text_position_combo.addItem("Custom", "custom")
        self.custom_x_spin = QSpinBox()
        self.custom_x_spin.setRange(0, 100)
        self.custom_x_spin.setValue(50)
        self.custom_x_spin.setSuffix("% X")
        self.custom_y_spin = QSpinBox()
        self.custom_y_spin.setRange(0, 100)
        self.custom_y_spin.setValue(84)
        self.custom_y_spin.setSuffix("% Y")
        position_row.addWidget(self.text_position_combo)
        position_row.addWidget(self.custom_x_spin)
        position_row.addWidget(self.custom_y_spin)
        form.addRow("Text position", position_row)

        layout.addLayout(form)
        return group

    def _build_preview_group(self) -> QGroupBox:
        group = QGroupBox("Preview")
        layout = QVBoxLayout(group)
        self.preview_widget = SubtitlePreviewWidget()
        self.preview_widget.activeCueChanged.connect(self.select_subtitle_from_playback)
        self.preview_widget.accuratePreviewRequested.connect(self.render_accurate_preview)
        layout.addWidget(self.preview_widget)

        self.summary_label = QLabel("Video: - | Subtitle count: 0")
        self.summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.summary_label)
        return group

    def _build_output_group(self) -> QGroupBox:
        group = QGroupBox("4. Output")
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("Choose output .mp4 path...")
        browse = QPushButton("Save As")
        browse.clicked.connect(self.select_output)
        row.addWidget(self.output_path_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(90)
        layout.addWidget(self.log_view)

        self.generate_button = QPushButton("Generate Subtitle Video")
        self.generate_button.clicked.connect(self.generate_video)
        self.generate_button.setMinimumHeight(42)
        self.export_subtitle_button = QPushButton("Export Edited Subtitle")
        self.export_subtitle_button.clicked.connect(self.export_edited_subtitle)
        self.export_subtitle_button.setMinimumHeight(36)
        layout.addWidget(self.export_subtitle_button)
        layout.addWidget(self.generate_button)
        return group

    def _connect_style_signals(self) -> None:
        widgets = [
            self.font_size_spin,
            self.stroke_width_spin,
            self.shadow_offset_spin,
            self.shadow_blur_spin,
            self.background_opacity_spin,
            self.horizontal_margin_spin,
            self.bottom_margin_spin,
            self.custom_safe_spin,
            self.line_spacing_spin,
            self.max_width_spin,
            self.max_lines_spin,
            self.custom_x_spin,
            self.custom_y_spin,
        ]
        for widget in widgets:
            widget.valueChanged.connect(self._update_preview_from_controls)
        for widget in [
            self.stroke_check,
            self.shadow_check,
            self.background_check,
        ]:
            widget.toggled.connect(self._update_preview_from_controls)
        for widget in [
            self.alignment_combo,
            self.alignment_offset_mode_combo,
            self.safe_area_combo,
            self.text_position_combo,
        ]:
            widget.currentIndexChanged.connect(self._update_preview_from_controls)
        self.font_combo.currentTextChanged.connect(self._update_preview_from_controls)
        self.preset_combo.currentTextChanged.connect(self.apply_preset)

        cue_widgets = [
            self.cue_font_size_spin,
            self.cue_max_width_spin,
            self.cue_custom_x_spin,
            self.cue_custom_y_spin,
            self.cue_horizontal_margin_spin,
            self.cue_vertical_margin_spin,
        ]
        for widget in cue_widgets:
            widget.valueChanged.connect(self._selected_cue_style_changed)
        self.cue_style_override_check.toggled.connect(self._selected_cue_style_changed)
        self.cue_alignment_combo.currentIndexChanged.connect(self._selected_cue_style_changed)
        self.cue_text_position_combo.currentIndexChanged.connect(self._selected_cue_style_changed)
        self.cue_alignment_offset_mode_combo.currentIndexChanged.connect(self._selected_cue_style_changed)

    def _force_arabic_digit_locale(self) -> None:
        self.setLocale(ARABIC_DIGIT_LOCALE)
        for widget_type in (QSpinBox, QDoubleSpinBox, QProgressBar):
            for widget in self.findChildren(widget_type):
                widget.setLocale(ARABIC_DIGIT_LOCALE)

    def _build_font_family_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(False)
        combo.setMaxVisibleItems(18)

        families = sorted(QFontDatabase.families(), key=str.casefold)
        ordered: list[str] = []
        for family in PREFERRED_FONTS:
            if family in families and family not in ordered:
                ordered.append(family)
        ordered.extend(family for family in families if family not in ordered)

        combo.addItems(ordered)
        return combo

    def _make_color_button(self, initial: str) -> QPushButton:
        button = QPushButton(initial)
        button.setProperty("color", initial)
        button.clicked.connect(lambda checked=False, b=button: self.choose_color(b))
        self._sync_color_button(button, initial)
        return button

    def choose_color(self, button: QPushButton) -> None:
        current = QColor(str(button.property("color")))
        color = QColorDialog.getColor(current, self, "Choose Color")
        if color.isValid():
            self._sync_color_button(button, color.name().upper())
            self._update_preview_from_controls()

    def _sync_color_button(self, button: QPushButton, color: str) -> None:
        button.setProperty("color", color)
        button.setText(color)
        button.setStyleSheet(
            f"QPushButton {{ background: {color}; color: {self._contrast_text(color)}; border: 1px solid #88929E; }}"
        )

    def select_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video",
            "",
            "Video Files (*.mp4 *.mov *.mkv *.avi *.webm *.m4v);;All Files (*.*)",
        )
        if not path:
            return
        self.video_path_edit.setText(path)
        self.load_video_info(path)

    def load_video_info(self, path: str) -> None:
        try:
            self.video_info = probe_video(path)
        except VideoProbeError as exc:
            self._show_error("Video Error", str(exc))
            return

        info = self.video_info
        self.video_labels["width"].setText(str(info.width))
        self.video_labels["height"].setText(str(info.height))
        self.video_labels["fps"].setText(f"{info.fps:.3f}")
        self.video_labels["duration"].setText(pretty_duration(info.duration))
        self.video_labels["aspect"].setText(info.aspect_ratio_label)
        self.video_labels["orientation"].setText(info.orientation)
        self.preview_widget.set_video_info(info)
        self.preview_widget.set_video_path(info.path)
        self._refresh_alignment_offset_ui()
        self._update_summary()

        if not self.output_path_edit.text().strip():
            output = info.path.with_name(f"{info.path.stem}_subtitled.mp4")
            self.output_path_edit.setText(str(output))
        self.log(f"Loaded video: {info.path}")

    def select_subtitle(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Subtitle",
            "",
            "Subtitle Files (*.srt *.vtt *.txt *.csv *.json);;All Files (*.*)",
        )
        if not path:
            return
        self.subtitle_path_edit.setText(path)
        detected = detect_subtitle_format(path)
        index = self.format_combo.findData(detected)
        if index >= 0:
            self.format_combo.setCurrentIndex(index)
        self.parse_subtitles()

    def select_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Choose Output Video",
            self.output_path_edit.text().strip() or "output_subtitled.mp4",
            "MP4 Video (*.mp4);;All Files (*.*)",
        )
        if path:
            if Path(path).suffix.lower() != ".mp4":
                path += ".mp4"
            if not self._confirm_overwrite(Path(path), "Output video"):
                return
            self.output_path_edit.setText(path)

    def _confirm_overwrite(self, path: Path, label: str) -> bool:
        if not path.exists():
            return True
        answer = QMessageBox.question(
            self,
            "Overwrite Existing File?",
            f"{label} already exists:\n{path}\n\nDo you want to overwrite this file?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def parse_subtitles(self) -> None:
        path = self.subtitle_path_edit.text().strip()
        if not path:
            self._show_error("Subtitle Error", "กรุณาเลือกไฟล์ subtitle ก่อน")
            return

        fmt = self.format_combo.currentData()
        duration = self.video_info.duration if self.video_info else None
        try:
            self.subtitle_doc = parse_subtitle_file(
                path,
                subtitle_format=fmt,
                video_duration=duration,
                txt_mode=str(self.txt_mode_combo.currentData()),
                txt_fixed_duration=float(self.txt_duration_spin.value()),
            )
        except SubtitleParseError as exc:
            self._show_error("Subtitle Parse Error", str(exc))
            return

        self._populate_subtitle_table()
        warnings = self.subtitle_doc.validate_against_duration(duration)
        for warning in warnings:
            self.log(f"Warning: {warning}")
        if self.subtitle_doc.cues:
            self.preview_widget.set_cues(self.subtitle_doc.cues)
            self.preview_widget.set_sample_cue(self.subtitle_doc.cues[0])
            self.subtitle_table.selectRow(0)
        self._update_summary()
        self._push_history()
        self.log(f"Parsed {len(self.subtitle_doc)} cues from {Path(path).name}")

    def _populate_subtitle_table(self) -> None:
        cues = self.subtitle_doc.cues if self.subtitle_doc else []
        self._updating_table = True
        self.subtitle_table.setRowCount(len(cues))
        for row, cue in enumerate(cues):
            self._set_subtitle_row(row, cue)
        self.subtitle_table.resizeColumnsToContents()
        self.subtitle_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._updating_table = False

    def _set_subtitle_row(self, row: int, cue: SubtitleCue) -> None:
        values = [cue.index, cue.start_label, cue.end_label, cue.text]
        for col, value in enumerate(values):
            editable = col != 0
            item = self._table_item(str(value), editable=editable)
            if col == 0:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.subtitle_table.setItem(row, col, item)

    def _table_item(self, value: str, *, editable: bool) -> QTableWidgetItem:
        item = QTableWidgetItem(value)
        if not editable:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def apply_table_edits(self) -> None:
        if self._sync_subtitles_from_table(show_errors=True):
            self._refresh_preview_data()
            self.log("Applied subtitle table edits.")

    def apply_text_editor_to_selected(self) -> None:
        row = self.subtitle_table.currentRow()
        if row < 0:
            self._show_error("Subtitle Text", "กรุณาเลือก subtitle ที่ต้องการแก้ก่อน")
            return
        self._set_table_text(row, 3, self.subtitle_text_editor.toPlainText().strip())
        self.apply_table_edits()
        self.preview_selected_subtitle()

    def add_subtitle_row(self) -> None:
        self._sync_subtitles_from_table(show_errors=False)
        cues = self.subtitle_doc.cues if self.subtitle_doc else []
        config = self._get_add_subtitle_config(cues)
        if config is None:
            return
        row, start, end, text = config

        self.subtitle_table.insertRow(row)
        cue = SubtitleCue(row + 1, start, end, text)
        self._set_subtitle_row(row, cue)
        self.subtitle_table.selectRow(row)
        self._sync_subtitles_from_table(show_errors=False)
        self._refresh_preview_data()
        self._update_summary()
        self.log(f"Added subtitle row {row + 1} ({format_timecode(start)} -> {format_timecode(end)}).")

    def _get_add_subtitle_config(
        self, cues: list[SubtitleCue]
    ) -> tuple[int, float, float, str] | None:
        selected_row = self.subtitle_table.currentRow()
        if selected_row < 0 or selected_row >= len(cues):
            selected_row = -1
        has_selection = selected_row >= 0

        dialog = QDialog(self)
        dialog.setWindowTitle("Add Subtitle")
        layout = QVBoxLayout(dialog)

        position_group = QGroupBox("Position")
        position_layout = QVBoxLayout(position_group)
        before_radio = QRadioButton("Before selected subtitle")
        after_radio = QRadioButton("After selected subtitle")
        end_radio = QRadioButton("At the end")
        before_radio.setEnabled(has_selection)
        after_radio.setEnabled(has_selection)
        if has_selection:
            after_radio.setChecked(True)
        else:
            end_radio.setChecked(True)
        position_layout.addWidget(before_radio)
        position_layout.addWidget(after_radio)
        position_layout.addWidget(end_radio)
        layout.addWidget(position_group)

        timing_group = QGroupBox("Timing")
        timing_layout = QFormLayout(timing_group)
        auto_time_radio = QRadioButton("Auto time")
        manual_time_radio = QRadioButton("Manual time")
        auto_time_radio.setChecked(True)
        timing_layout.addRow(auto_time_radio)
        timing_layout.addRow(manual_time_radio)

        start_spin = QDoubleSpinBox()
        start_spin.setRange(0, max(24 * 60 * 60, self.video_info.duration if self.video_info else 0))
        start_spin.setDecimals(3)
        start_spin.setSuffix(" sec")
        end_spin = QDoubleSpinBox()
        end_spin.setRange(0, max(24 * 60 * 60, self.video_info.duration if self.video_info else 0))
        end_spin.setDecimals(3)
        end_spin.setSuffix(" sec")

        auto_start, auto_end = self._auto_new_subtitle_time(cues, selected_row, after_radio.isChecked())
        start_spin.setValue(auto_start)
        end_spin.setValue(auto_end)
        timing_layout.addRow("Start", start_spin)
        timing_layout.addRow("End", end_spin)
        layout.addWidget(timing_group)

        text_edit = QTextEdit()
        text_edit.setPlaceholderText("New subtitle")
        text_edit.setPlainText("New subtitle")
        text_edit.setMinimumHeight(80)
        layout.addWidget(text_edit)

        def refresh_auto_time() -> None:
            if not auto_time_radio.isChecked():
                return
            insert_after = after_radio.isChecked() or end_radio.isChecked()
            start, end = self._auto_new_subtitle_time(cues, selected_row, insert_after, end_radio.isChecked())
            start_spin.setValue(start)
            end_spin.setValue(end)

        def sync_time_mode() -> None:
            manual = manual_time_radio.isChecked()
            start_spin.setEnabled(manual)
            end_spin.setEnabled(manual)
            refresh_auto_time()

        for radio in (before_radio, after_radio, end_radio, auto_time_radio):
            radio.toggled.connect(refresh_auto_time)
        manual_time_radio.toggled.connect(sync_time_mode)
        sync_time_mode()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        if before_radio.isChecked() and selected_row >= 0:
            row = selected_row
        elif after_radio.isChecked() and selected_row >= 0:
            row = selected_row + 1
        else:
            row = len(cues)

        start = float(start_spin.value())
        end = float(end_spin.value())
        if auto_time_radio.isChecked():
            insert_after = after_radio.isChecked() or end_radio.isChecked()
            start, end = self._auto_new_subtitle_time(cues, selected_row, insert_after, end_radio.isChecked())

        if end <= start:
            self._show_error("Add Subtitle", "End time must be greater than start time.")
            return None

        return row, start, end, text_edit.toPlainText().strip() or "New subtitle"

    def _auto_new_subtitle_time(
        self,
        cues: list[SubtitleCue],
        selected_row: int,
        insert_after: bool,
        force_end: bool = False,
    ) -> tuple[float, float]:
        duration = self.video_info.duration if self.video_info else 0.0
        default_len = 2.0
        gap = 0.04
        if not cues or force_end or selected_row < 0:
            start = (cues[-1].end + gap) if cues else 0.0
            end = start + default_len
            if duration > 0 and end > duration:
                start = max(0.0, duration - default_len)
                end = min(duration, end)
            return start, end if end > start else start + default_len

        selected = cues[min(selected_row, len(cues) - 1)]
        if insert_after:
            next_start = cues[selected_row + 1].start - gap if selected_row + 1 < len(cues) else duration
            start = selected.end + gap
            end = min(start + default_len, next_start if next_start > start else start + default_len)
        else:
            prev_end = (cues[selected_row - 1].end + gap) if selected_row > 0 else 0.0
            end = max(0.0, selected.start - gap)
            start = max(prev_end, end - default_len)
        if end <= start:
            end = start + default_len
        return start, end

    def delete_selected_subtitles(self) -> None:
        rows = sorted({index.row() for index in self.subtitle_table.selectedIndexes()}, reverse=True)
        if not rows:
            self._show_error("Delete Subtitle", "กรุณาเลือก subtitle ที่ต้องการลบก่อน")
            return
        for row in rows:
            self.subtitle_table.removeRow(row)
        self._renumber_table()
        self._sync_subtitles_from_table(show_errors=False)
        self._refresh_preview_data()
        self._update_summary()
        self.log(f"Deleted {len(rows)} subtitle row(s).")

    def preview_selected_subtitle(self) -> None:
        if self._updating_table:
            return
        row = self.subtitle_table.currentRow()
        if row < 0:
            return
        cue = self._cue_from_table_row(row, show_errors=False)
        if cue:
            self._load_selected_text_to_editor(cue.text)
            self._load_selected_style_to_controls(cue)
            if not self._selecting_from_playback:
                self.preview_widget.set_sample_cue(cue)

    def select_subtitle_from_playback(self, cue_index: int) -> None:
        if cue_index <= 0 or not self.subtitle_doc:
            return
        row = next((idx for idx, cue in enumerate(self.subtitle_doc.cues) if cue.index == cue_index), -1)
        if row < 0 or row == self.subtitle_table.currentRow():
            return
        cue = self.subtitle_doc.cues[row]
        self._selecting_from_playback = True
        with QSignalBlocker(self.subtitle_table):
            self.subtitle_table.selectRow(row)
        self._load_selected_text_to_editor(cue.text)
        self._load_selected_style_to_controls(cue)
        self._selecting_from_playback = False

    def render_accurate_preview(self, position_ms: int) -> None:
        if not self.video_info:
            self._show_error("Exact Preview", "Please select a video first.")
            return
        if not self.subtitle_doc:
            self.parse_subtitles()
        if not self.subtitle_doc:
            return
        if not self._sync_subtitles_from_table(show_errors=True):
            return

        position_seconds = max(0.0, position_ms / 1000.0)
        self.preview_widget.accurate_preview_button.setEnabled(False)
        self.log("Rendering exact preview frame with FFmpeg/libass...")
        try:
            png_bytes = render_accurate_preview_frame(
                video_info=self.video_info,
                cues=self.subtitle_doc.cues,
                style=self.current_style(),
                position_seconds=position_seconds,
            )
        except PreviewRenderError as exc:
            self._show_error("Exact Preview Error", str(exc))
            return
        except Exception as exc:
            self._show_error("Exact Preview Error", str(exc))
            return
        finally:
            self.preview_widget.accurate_preview_button.setEnabled(True)

        image = QImage.fromData(png_bytes, "PNG")
        if image.isNull():
            self._show_error("Exact Preview Error", "FFmpeg returned an unreadable preview frame.")
            return
        self.preview_widget.show_accurate_preview_image(image, position_ms)
        self.log("Exact preview frame rendered. This frame uses the same FFmpeg/libass renderer as export.")

    def auto_cleanup_timings(self) -> None:
        if not self.video_info:
            self._show_error("Auto Timing", "กรุณาเลือกวิดีโอก่อน เพื่อคำนวณเวลาจากขนาดและความยาววิดีโอ")
            return
        if not self._sync_subtitles_from_table(show_errors=True):
            return
        if not self.subtitle_doc or not self.subtitle_doc.cues:
            self._show_error("Auto Timing", "ยังไม่มี subtitle ให้ปรับเวลา")
            return

        silences = []
        if self.use_silence_detect_check.isChecked():
            try:
                silences = detect_silences(
                    self.video_info.path,
                    min_silence_duration=max(0.15, float(self.hold_after_spin.value())),
                )
                self.log(f"Detected {len(silences)} audio silence range(s).")
            except Exception as exc:
                self.log(f"Audio silence detection skipped: {exc}")

        cleaned = cleanup_subtitle_timings(
            self.subtitle_doc.cues,
            video_info=self.video_info,
            style=self.current_style(),
            silences=silences,
            hold_after_sentence=float(self.hold_after_spin.value()),
            min_duration=float(self.min_display_spin.value()),
            max_duration=float(self.max_display_spin.value()),
        )
        self.subtitle_doc = SubtitleDocument(cues=cleaned, source_format=self.subtitle_doc.source_format)
        self._populate_subtitle_table()
        if cleaned:
            self.preview_widget.set_cues(cleaned)
            self.preview_widget.set_sample_cue(cleaned[0])
        self._update_summary()
        self._push_history()
        self.log("Applied auto timing cleanup: trimmed subtitles that stayed on screen too long.")

    def start_speech_sync(self) -> None:
        if not self.video_info:
            self._show_error("Auto Speech Sync", "Please select a video first.")
            return
        if self.speech_thread is not None:
            self._show_error("Auto Speech Sync", "Speech sync is already running.")
            return

        options = SpeechSyncOptions(
            model_size=self.speech_model_combo.currentText(),
            language=str(self.speech_language_combo.currentData()) or None,
            compute_type=self.speech_compute_combo.currentText(),
            beam_size=int(self.speech_beam_spin.value()),
            best_of=int(self.speech_beam_spin.value()),
            pause_threshold=max(0.15, float(self.hold_after_spin.value())),
            hold_after_sentence=float(self.hold_after_spin.value()),
            min_duration=float(self.min_display_spin.value()),
            max_duration=min(float(self.max_display_spin.value()), 4.5),
            max_words_per_cue=10 if self.video_info.orientation == "portrait" else 12,
            target_chars_per_second=13.0 if self.video_info.orientation == "portrait" else 15.0,
        )
        self.progress_bar.setValue(0)
        self.speech_sync_button.setEnabled(False)
        self.log("Starting Auto Speech Sync. This may take a while the first time because the Whisper model may download.")

        self.speech_thread = QThread(self)
        self.speech_worker = SpeechSyncWorker(
            video_info=self.video_info,
            style=self.current_style(),
            options=options,
        )
        self.speech_worker.moveToThread(self.speech_thread)
        self.speech_thread.started.connect(self.speech_worker.run)
        self.speech_worker.progress.connect(self.progress_bar.setValue)
        self.speech_worker.log.connect(self.log)
        self.speech_worker.finished.connect(self._speech_sync_finished)
        self.speech_worker.failed.connect(self._speech_sync_failed)
        self.speech_worker.finished.connect(self.speech_thread.quit)
        self.speech_worker.failed.connect(self.speech_thread.quit)
        self.speech_thread.finished.connect(self.speech_worker.deleteLater)
        self.speech_thread.finished.connect(self._speech_sync_thread_finished)
        self.speech_thread.start()

    def _speech_sync_finished(self, cues: object) -> None:
        generated = list(cues) if isinstance(cues, list) else []
        if not generated:
            self._speech_sync_failed("Speech Sync finished but did not generate subtitle cues.")
            return
        self.subtitle_doc = SubtitleDocument(cues=generated, source_format="speech_sync")
        self._populate_subtitle_table()
        self._refresh_preview_data()
        self.subtitle_table.selectRow(0)
        self.preview_widget.set_sample_cue(generated[0])
        self._update_summary()
        self._push_history()
        self.progress_bar.setValue(100)
        self.log(f"Auto Speech Sync generated {len(generated)} subtitle cue(s). Review/edit before export.")

    def _speech_sync_failed(self, message: str) -> None:
        self.log(f"Auto Speech Sync failed: {message}")
        self._show_error("Auto Speech Sync", message)

    def _speech_sync_thread_finished(self) -> None:
        self.speech_sync_button.setEnabled(True)
        self.speech_thread = None
        self.speech_worker = None

    def auto_arrange_subtitle_text(self) -> None:
        if not self.video_info:
            self._show_error("Auto Arrange Text", "กรุณาเลือกวิดีโอก่อน เพื่อคำนวณจากขนาดวิดีโอจริง")
            return
        if not self._sync_subtitles_from_table(show_errors=True):
            return
        if not self.subtitle_doc or not self.subtitle_doc.cues:
            self._show_error("Auto Arrange Text", "ยังไม่มี subtitle ให้จัดข้อความ")
            return

        readability_notes = self._apply_auto_readability_settings()
        original_text = self._compact_cue_text(self.subtitle_doc.cues)
        before = len(self.subtitle_doc.cues)
        arranged, validation_notes, remaining_issues = self._auto_arrange_until_visible(self.subtitle_doc.cues)
        style = self.current_style()
        style.max_lines = max(1, int(self.max_lines_spin.value()))
        self.subtitle_doc = SubtitleDocument(cues=arranged, source_format=self.subtitle_doc.source_format)
        self._populate_subtitle_table()
        self._refresh_preview_data()
        if arranged:
            self.subtitle_table.selectRow(0)
            self.preview_widget.set_sample_cue(arranged[0])
        self._update_summary()
        self._push_history()
        self.log(
            f"Auto arranged text using max {style.max_lines} line(s): {before} cue(s) -> {len(arranged)} cue(s)."
        )
        for note in readability_notes:
            self.log(f"Auto readability: {note}")
        for note in validation_notes:
            self.log(f"Auto validation: {note}")
        if self._compact_cue_text(arranged) != original_text:
            self.log("Auto validation warning: text content changed during wrapping. Please review the subtitle table.")
        if remaining_issues:
            preview = "; ".join(remaining_issues[:3])
            self.log(f"Auto validation warning: {len(remaining_issues)} cue issue(s) still need review. {preview}")

    def _apply_auto_readability_settings(self) -> list[str]:
        notes: list[str] = []
        if not self.video_info:
            return notes

        if self.max_lines_spin.value() < 1:
            self.max_lines_spin.setValue(2)

        if self.max_width_spin.value() > 90:
            self.max_width_spin.setValue(90)
            notes.append("Max width was reduced to 90% to keep text inside the safe area.")

        max_font_size = max(28, round(min(self.video_info.width, self.video_info.height) * 0.085))
        if self.font_size_spin.value() > max_font_size:
            self.font_size_spin.setValue(max_font_size)
            notes.append(f"Font size was reduced to {max_font_size} for this video size.")

        max_stroke = max(1.0, self.font_size_spin.value() * 0.16)
        if self.stroke_check.isChecked() and self.stroke_width_spin.value() > max_stroke:
            self.stroke_width_spin.setValue(round(max_stroke, 1))
            notes.append("Stroke width was reduced so the outline does not swallow the letters.")

        if (
            not self.stroke_check.isChecked()
            and not self.background_check.isChecked()
            and not self.shadow_check.isChecked()
        ):
            self.stroke_check.setChecked(True)
            self.stroke_width_spin.setValue(max(2.0, round(self.font_size_spin.value() * 0.06, 1)))
            self._sync_color_button(self.stroke_color_button, "#000000")
            notes.append("Stroke was enabled because no outline/background/shadow was active.")

        if self.bottom_margin_spin.value() == 0 and self.safe_area_combo.currentData() != "auto":
            self._set_combo_data(self.safe_area_combo, "auto")
            notes.append("Safe area was set to Auto.")

        return notes

    def _auto_arrange_until_visible(
        self,
        cues: list[SubtitleCue],
    ) -> tuple[list[SubtitleCue], list[str], list[str]]:
        if not self.video_info:
            return cues, [], []

        notes: list[str] = []
        arranged: list[SubtitleCue] = []
        remaining_issues: list[str] = []
        max_lines = max(1, int(self.max_lines_spin.value()))
        min_font_size = 18
        font_note_added = False
        stroke_note_added = False

        for _attempt in range(80):
            style = self.current_style()
            style.max_lines = max_lines
            arranged = arrange_cues_for_readability(
                cues,
                video_info=self.video_info,
                style=style,
                max_lines=max_lines,
            )
            remaining_issues = self._subtitle_visibility_issues(arranged, style)
            if not remaining_issues:
                notes.append(f"Checked {len(arranged)} cue(s): no hidden text or edge overflow detected.")
                return arranged, notes, []

            font_value = int(self.font_size_spin.value())
            if font_value > min_font_size:
                new_size = max(min_font_size, font_value - 2)
                self.font_size_spin.setValue(new_size)
                if not font_note_added or new_size == min_font_size:
                    notes.append(f"Reduced font size to {new_size} while checking subtitle visibility.")
                    font_note_added = True
                continue

            if self.stroke_check.isChecked() and self.stroke_width_spin.value() > 0:
                new_stroke = max(0.0, float(self.stroke_width_spin.value()) - 0.5)
                self.stroke_width_spin.setValue(new_stroke)
                if not stroke_note_added:
                    notes.append("Reduced stroke width because outlines were taking too much text space.")
                    stroke_note_added = True
                continue

            break

        return arranged, notes, remaining_issues

    def _subtitle_visibility_issues(self, cues: list[SubtitleCue], style: SubtitleStyle) -> list[str]:
        if not self.video_info:
            return []

        issues: list[str] = []
        for cue in cues:
            cue_style = style_with_overrides(style, cue.style_overrides)
            font = QFont(cue_style.font_family)
            font.setPixelSize(max(1, int(cue_style.font_size)))
            metrics = QFontMetrics(font)
            safe_width = self.video_info.width * max(20, min(cue_style.max_width_percent, 100)) / 100
            decoration_width = 0.0
            if cue_style.stroke_enabled:
                decoration_width += max(0.0, cue_style.stroke_width) * 2
            if cue_style.shadow_enabled:
                decoration_width += max(0.0, cue_style.shadow_offset)
            max_lines = max(1, cue_style.max_lines)
            line_height = metrics.height() + max(0, cue_style.line_spacing)
            vertical_limit = max(1, self.video_info.height - self._subtitle_vertical_reserved_space(cue_style))
            lines = wrap_subtitle_text(cue.text, self.video_info, cue_style, limit_lines=False)
            if len(lines) > max_lines:
                issues.append(f"cue {cue.index}: {len(lines)} lines exceed max {max_lines}")
            widest = max((metrics.horizontalAdvance(line) for line in lines), default=0)
            if widest + decoration_width > safe_width:
                issues.append(f"cue {cue.index}: text width exceeds safe area")
            if line_height * len(lines) > vertical_limit:
                issues.append(f"cue {cue.index}: subtitle block is taller than the safe area")

        return issues

    def _subtitle_vertical_reserved_space(self, style: SubtitleStyle) -> int:
        if not self.video_info:
            return 0
        if style.alignment == "center" or style.text_position == "custom":
            return round(self.video_info.height * 0.08)
        if style.alignment == "top_center":
            return max(0, style.bottom_margin)
        from core.style_preset import effective_bottom_margin

        return effective_bottom_margin(self.video_info, style)

    def _compact_cue_text(self, cues: list[SubtitleCue]) -> str:
        return "".join("".join(cue.text.split()) for cue in cues)

    def _sync_subtitles_from_table(self, *, show_errors: bool) -> bool:
        cues: list[SubtitleCue] = []
        try:
            for row in range(self.subtitle_table.rowCount()):
                cue = self._cue_from_table_row(row, show_errors=True)
                if cue:
                    cue.index = len(cues) + 1
                    cues.append(cue)
        except SubtitleParseError as exc:
            if show_errors:
                self._show_error("Subtitle Table Error", str(exc))
            return False

        source_format = self.subtitle_doc.source_format if self.subtitle_doc else "edited"
        self.subtitle_doc = SubtitleDocument(cues=cues, source_format=source_format)
        self._renumber_table()
        self._update_summary()
        self._refresh_preview_data()
        self._push_history()
        return True

    def _subtitle_table_changed(self, item: QTableWidgetItem) -> None:
        del item
        if self._updating_table:
            return
        if self._sync_subtitles_from_table(show_errors=False):
            self._refresh_preview_data()
            self.preview_selected_subtitle()

    def _subtitle_text_editor_changed(self) -> None:
        if self._updating_text_editor:
            return
        row = self.subtitle_table.currentRow()
        if row < 0:
            return
        self._set_table_text(row, 3, self.subtitle_text_editor.toPlainText().rstrip("\n"))
        self._sync_subtitles_from_table(show_errors=False)
        self._refresh_preview_data()
        if self.subtitle_doc and 0 <= row < len(self.subtitle_doc.cues):
            self.preview_widget.set_sample_cue(self.subtitle_doc.cues[row])

    def _load_selected_style_to_controls(self, cue: SubtitleCue) -> None:
        base_style = self.current_style()
        style = style_with_overrides(base_style, cue.style_overrides)
        self._updating_cue_style_controls = True
        blockers = [
            QSignalBlocker(self.cue_style_override_check),
            QSignalBlocker(self.cue_alignment_combo),
            QSignalBlocker(self.cue_text_position_combo),
            QSignalBlocker(self.cue_custom_x_spin),
            QSignalBlocker(self.cue_custom_y_spin),
            QSignalBlocker(self.cue_font_size_spin),
            QSignalBlocker(self.cue_max_width_spin),
            QSignalBlocker(self.cue_alignment_offset_mode_combo),
            QSignalBlocker(self.cue_horizontal_margin_spin),
            QSignalBlocker(self.cue_vertical_margin_spin),
        ]
        self.cue_style_override_check.setChecked(bool(cue.style_overrides))
        self._set_combo_data(self.cue_alignment_combo, style.alignment)
        self._set_combo_data(self.cue_text_position_combo, style.text_position)
        self.cue_custom_x_spin.setValue(style.custom_x_percent)
        self.cue_custom_y_spin.setValue(style.custom_y_percent)
        self.cue_font_size_spin.setValue(style.font_size)
        self.cue_max_width_spin.setValue(style.max_width_percent)
        cue_offset_manual = style.horizontal_margin > 0 or style.bottom_margin > 0
        self._set_combo_data(self.cue_alignment_offset_mode_combo, "manual" if cue_offset_manual else "auto")
        self.cue_horizontal_margin_spin.setValue(style.horizontal_margin)
        self.cue_vertical_margin_spin.setValue(style.bottom_margin)
        self._set_cue_style_controls_enabled(True)
        del blockers
        self._updating_cue_style_controls = False
        self._refresh_cue_alignment_offset_ui(cue)

    def _selected_cue_style_changed(self, *args) -> None:
        del args
        if self._updating_cue_style_controls:
            return
        row = self.subtitle_table.currentRow()
        if row < 0:
            return
        if not self._sync_subtitles_from_table(show_errors=False):
            return
        if not self.subtitle_doc or row >= len(self.subtitle_doc.cues):
            return
        cue = self.subtitle_doc.cues[row]
        if not self.cue_style_override_check.isChecked():
            cue.style_overrides.clear()
            self._set_cue_style_controls_enabled(True)
        else:
            cue.style_overrides.update(
                {
                    "alignment": str(self.cue_alignment_combo.currentData()),
                    "text_position": str(self.cue_text_position_combo.currentData()),
                    "custom_x_percent": int(self.cue_custom_x_spin.value()),
                    "custom_y_percent": int(self.cue_custom_y_spin.value()),
                    "font_size": int(self.cue_font_size_spin.value()),
                    "max_width_percent": int(self.cue_max_width_spin.value()),
                    "horizontal_margin": 0
                    if str(self.cue_alignment_offset_mode_combo.currentData()) == "auto"
                    else int(self.cue_horizontal_margin_spin.value()),
                    "bottom_margin": 0
                    if str(self.cue_alignment_offset_mode_combo.currentData()) == "auto"
                    else int(self.cue_vertical_margin_spin.value()),
                }
            )
        self._refresh_cue_alignment_offset_ui(cue)
        self._refresh_preview_data()
        self.preview_widget.set_sample_cue(cue)
        self._push_history()

    def clear_selected_cue_style(self) -> None:
        row = self.subtitle_table.currentRow()
        if row < 0:
            self._show_error("Manual Style", "Please select a subtitle first.")
            return
        if not self._sync_subtitles_from_table(show_errors=False):
            return
        if not self.subtitle_doc or row >= len(self.subtitle_doc.cues):
            return
        self.subtitle_doc.cues[row].style_overrides.clear()
        self._load_selected_style_to_controls(self.subtitle_doc.cues[row])
        self._refresh_preview_data()
        self.preview_widget.set_sample_cue(self.subtitle_doc.cues[row])
        self._push_history()
        self.log(f"Cleared manual style for subtitle row {row + 1}.")

    def _set_cue_style_controls_enabled(self, enabled: bool) -> None:
        for widget in [
            self.cue_alignment_combo,
            self.cue_text_position_combo,
            self.cue_custom_x_spin,
            self.cue_custom_y_spin,
            self.cue_font_size_spin,
            self.cue_max_width_spin,
            self.cue_alignment_offset_mode_combo,
            self.cue_horizontal_margin_spin,
            self.cue_vertical_margin_spin,
        ]:
            widget.setEnabled(enabled)

    def _refresh_cue_alignment_offset_ui(self, cue: SubtitleCue) -> None:
        base_style = self.current_style()
        cue_style = style_with_overrides(base_style, cue.style_overrides)
        manual = str(self.cue_alignment_offset_mode_combo.currentData()) == "manual"
        for widget in (self.cue_horizontal_margin_spin, self.cue_vertical_margin_spin):
            widget.setEnabled(manual)
        self.cue_alignment_reference_label.setText(
            f"Reference: {self._alignment_reference_text(cue_style.alignment)}"
        )
        if self.video_info:
            auto_x = auto_horizontal_margin(self.video_info, cue_style)
            auto_y = auto_bottom_margin(self.video_info, cue_style)
            self.cue_auto_alignment_offset_label.setText(f"Auto X: {auto_x} px | Auto Y: {auto_y} px")
        else:
            self.cue_auto_alignment_offset_label.setText("Auto X: - | Auto Y: -")

    def _load_selected_text_to_editor(self, text: str) -> None:
        if self.subtitle_text_editor.toPlainText() == text:
            return
        self._updating_text_editor = True
        self.subtitle_text_editor.setPlainText(text)
        self._updating_text_editor = False

    def _set_table_text(self, row: int, col: int, text: str) -> None:
        self._updating_table = True
        item = self.subtitle_table.item(row, col)
        if item is None:
            item = self._table_item("", editable=True)
            self.subtitle_table.setItem(row, col, item)
        item.setText(text)
        self.subtitle_table.resizeRowToContents(row)
        self._updating_table = False

    def _refresh_preview_data(self) -> None:
        cues = self.subtitle_doc.cues if self.subtitle_doc else []
        self.preview_widget.set_cues(cues)
        self.preview_widget.set_style(self.current_style())

    def _cue_from_table_row(self, row: int, *, show_errors: bool) -> SubtitleCue | None:
        del show_errors
        start_text = self._table_text(row, 1)
        end_text = self._table_text(row, 2)
        text = self._table_text(row, 3).strip()
        if not start_text and not end_text and not text:
            return None
        try:
            start = parse_timecode(start_text)
            end = parse_timecode(end_text)
        except Exception as exc:
            raise SubtitleParseError(f"Row {row + 1}: timecode ไม่ถูกต้อง ({exc})") from exc
        try:
            overrides: dict[str, object] = {}
            if self.subtitle_doc and 0 <= row < len(self.subtitle_doc.cues):
                overrides = dict(self.subtitle_doc.cues[row].style_overrides)
            return SubtitleCue(row + 1, start, end, text, style_overrides=overrides)
        except SubtitleParseError as exc:
            raise SubtitleParseError(f"Row {row + 1}: {exc}") from exc

    def _table_text(self, row: int, col: int) -> str:
        item = self.subtitle_table.item(row, col)
        return item.text().strip() if item else ""

    def _renumber_table(self) -> None:
        self._updating_table = True
        for row in range(self.subtitle_table.rowCount()):
            item = self.subtitle_table.item(row, 0)
            if item is None:
                item = self._table_item("", editable=False)
                self.subtitle_table.setItem(row, 0, item)
            item.setText(str(row + 1))
        self._updating_table = False

    def current_style(self) -> SubtitleStyle:
        return SubtitleStyle(
            font_family=self.font_combo.currentText(),
            font_size=int(self.font_size_spin.value()),
            font_color=str(self.font_color_button.property("color")),
            stroke_enabled=self.stroke_check.isChecked(),
            stroke_color=str(self.stroke_color_button.property("color")),
            stroke_width=float(self.stroke_width_spin.value()),
            shadow_enabled=self.shadow_check.isChecked(),
            shadow_color=str(self.shadow_color_button.property("color")),
            shadow_offset=float(self.shadow_offset_spin.value()),
            shadow_blur=float(self.shadow_blur_spin.value()),
            background_enabled=self.background_check.isChecked(),
            background_color=str(self.background_color_button.property("color")),
            background_opacity=int(self.background_opacity_spin.value()),
            alignment=str(self.alignment_combo.currentData()),
            bottom_margin=0
            if str(self.alignment_offset_mode_combo.currentData()) == "auto"
            else int(self.bottom_margin_spin.value()),
            horizontal_margin=0
            if str(self.alignment_offset_mode_combo.currentData()) == "auto"
            else int(self.horizontal_margin_spin.value()),
            safe_area_mode=str(self.safe_area_combo.currentData()),
            custom_safe_area_percent=int(self.custom_safe_spin.value()),
            line_spacing=int(self.line_spacing_spin.value()),
            max_width_percent=int(self.max_width_spin.value()),
            max_lines=int(self.max_lines_spin.value()),
            text_position=str(self.text_position_combo.currentData()),
            custom_x_percent=int(self.custom_x_spin.value()),
            custom_y_percent=int(self.custom_y_spin.value()),
        )

    def _load_style_to_controls(self, style: SubtitleStyle) -> None:
        self._set_font_family(style.font_family)
        self.font_size_spin.setValue(style.font_size)
        self._sync_color_button(self.font_color_button, style.font_color)
        self.stroke_check.setChecked(style.stroke_enabled)
        self._sync_color_button(self.stroke_color_button, style.stroke_color)
        self.stroke_width_spin.setValue(style.stroke_width)
        self.shadow_check.setChecked(style.shadow_enabled)
        self._sync_color_button(self.shadow_color_button, style.shadow_color)
        self.shadow_offset_spin.setValue(style.shadow_offset)
        self.shadow_blur_spin.setValue(style.shadow_blur)
        self.background_check.setChecked(style.background_enabled)
        self._sync_color_button(self.background_color_button, style.background_color)
        self.background_opacity_spin.setValue(style.background_opacity)
        self._set_combo_data(self.alignment_combo, style.alignment)
        self._set_combo_data(
            self.alignment_offset_mode_combo,
            "manual" if style.bottom_margin > 0 or style.horizontal_margin > 0 else "auto",
        )
        self.horizontal_margin_spin.setValue(style.horizontal_margin)
        self.bottom_margin_spin.setValue(style.bottom_margin)
        self._set_combo_data(self.safe_area_combo, style.safe_area_mode)
        self.custom_safe_spin.setValue(style.custom_safe_area_percent)
        self.line_spacing_spin.setValue(style.line_spacing)
        self.max_width_spin.setValue(style.max_width_percent)
        self.max_lines_spin.setValue(style.max_lines)
        self._set_combo_data(self.text_position_combo, style.text_position)
        self.custom_x_spin.setValue(style.custom_x_percent)
        self.custom_y_spin.setValue(style.custom_y_percent)
        self._update_preview_from_controls()

    def apply_preset(self, preset_name: str) -> None:
        style = STYLE_PRESETS.get(preset_name)
        if style:
            self._load_style_to_controls(SubtitleStyle.from_dict(style.to_dict()))

    def apply_auto_size(self) -> None:
        if not self.video_info:
            self._show_error("Auto Size", "กรุณาเลือกวิดีโอก่อน เพื่อคำนวณ font size จาก resolution จริง")
            return
        style = style_with_auto_size(self.current_style(), self.video_info)
        self._load_style_to_controls(style)
        self.log("Applied automatic font size and safe margin from video resolution.")

    def generate_video(self) -> None:
        if not self.video_info:
            self._show_error("Export Error", "กรุณาเลือกวิดีโอก่อน")
            return
        if not self.subtitle_doc:
            self.parse_subtitles()
        if not self.subtitle_doc:
            return
        if not self._sync_subtitles_from_table(show_errors=True):
            return

        output_path = self.output_path_edit.text().strip()
        if not output_path:
            self._show_error("Export Error", "กรุณาเลือก output path")
            return

        if not self._confirm_overwrite(Path(output_path), "Output video"):
            return

        try:
            ensure_ffmpeg()
        except Exception as exc:
            self._show_error("FFmpeg Error", str(exc))
            return

        warnings = self.subtitle_doc.validate_against_duration(self.video_info.duration)
        if warnings:
            self.log("Subtitle timing warnings:")
            for warning in warnings:
                self.log(f"- {warning}")

        self.generate_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log("Preparing ASS subtitle and starting export...")

        self.render_thread = QThread(self)
        self.render_worker = RenderWorker(
            video_info=self.video_info,
            cues=self.subtitle_doc.cues,
            style=self.current_style(),
            output_path=output_path,
        )
        self.render_worker.moveToThread(self.render_thread)
        self.render_thread.started.connect(self.render_worker.run)
        self.render_worker.progress.connect(self.progress_bar.setValue)
        self.render_worker.log.connect(self.log)
        self.render_worker.finished.connect(self._render_finished)
        self.render_worker.failed.connect(self._render_failed)
        self.render_worker.finished.connect(self.render_thread.quit)
        self.render_worker.failed.connect(self.render_thread.quit)
        self.render_thread.finished.connect(self.render_worker.deleteLater)
        self.render_thread.finished.connect(self.render_thread.deleteLater)
        self.render_thread.start()

    def export_edited_subtitle(self) -> None:
        if not self.subtitle_doc:
            if self.subtitle_path_edit.text().strip():
                self.parse_subtitles()
        if not self.subtitle_doc:
            self._show_error("Export Subtitle", "ยังไม่มี subtitle ให้ export")
            return
        if not self._sync_subtitles_from_table(show_errors=True):
            return
        if not self.subtitle_doc or not self.subtitle_doc.cues:
            self._show_error("Export Subtitle", "ยังไม่มี subtitle ให้ export")
            return

        default_name = "edited_subtitle.srt"
        if self.video_info:
            default_name = f"{self.video_info.path.stem}_edited.srt"
        elif self.subtitle_path_edit.text().strip():
            source = Path(self.subtitle_path_edit.text().strip())
            default_name = f"{source.stem}_edited.srt"

        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Edited Subtitle",
            default_name,
            "SRT Subtitle (*.srt);;VTT Subtitle (*.vtt);;ASS Styled Subtitle (*.ass);;JSON Subtitle (*.json);;CSV Subtitle (*.csv);;Timestamped TXT (*.txt)",
        )
        if not path:
            return

        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(self._subtitle_suffix_from_filter(selected_filter))
        if not self._confirm_overwrite(target, "Subtitle file"):
            return

        try:
            export_subtitle_file(
                target,
                self.subtitle_doc.cues,
                video_info=self.video_info,
                style=self.current_style(),
            )
        except SubtitleExportError as exc:
            self._show_error("Export Subtitle Error", str(exc))
            return
        except Exception as exc:
            self._show_error("Export Subtitle Error", str(exc))
            return

        self.log(f"Exported edited subtitle: {target}")
        QMessageBox.information(self, "Subtitle Exported", f"บันทึก subtitle แล้ว:\n{target}")

    def _subtitle_suffix_from_filter(self, selected_filter: str) -> str:
        lowered = selected_filter.lower()
        if "*.vtt" in lowered:
            return ".vtt"
        if "*.ass" in lowered:
            return ".ass"
        if "*.json" in lowered:
            return ".json"
        if "*.csv" in lowered:
            return ".csv"
        if "*.txt" in lowered:
            return ".txt"
        return ".srt"

    def _render_finished(self, output_path: str) -> None:
        self.progress_bar.setValue(100)
        self.generate_button.setEnabled(True)
        self.log(f"Done: {output_path}")
        QMessageBox.information(self, "Export Finished", f"สร้างวิดีโอเสร็จแล้ว:\n{output_path}")

    def _render_failed(self, message: str) -> None:
        self.generate_button.setEnabled(True)
        self.log(f"Export failed: {message}")
        self._show_error("Export Failed", message)

    def save_project_config(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project Config",
            "smart_subtitle_project.json",
            "JSON Files (*.json);;All Files (*.*)",
        )
        if not path:
            return
        config = ProjectConfig(
            video_path=self.video_path_edit.text().strip(),
            subtitle_path=self.subtitle_path_edit.text().strip(),
            subtitle_format=str(self.format_combo.currentData()),
            txt_mode=str(self.txt_mode_combo.currentData()),
            txt_fixed_duration=float(self.txt_duration_spin.value()),
            hold_after_sentence=float(self.hold_after_spin.value()),
            min_display_duration=float(self.min_display_spin.value()),
            max_display_duration=float(self.max_display_spin.value()),
            use_silence_detection=self.use_silence_detect_check.isChecked(),
            output_path=self.output_path_edit.text().strip(),
            style=self.current_style(),
        )
        try:
            save_project_config(path, config)
            self.log(f"Saved project config: {path}")
        except Exception as exc:
            self._show_error("Save Config Error", str(exc))

    def load_project_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Project Config",
            "",
            "JSON Files (*.json);;All Files (*.*)",
        )
        if not path:
            return
        try:
            config = load_project_config(path)
        except Exception as exc:
            self._show_error("Load Config Error", str(exc))
            return

        self.video_path_edit.setText(config.video_path)
        self.subtitle_path_edit.setText(config.subtitle_path)
        self.output_path_edit.setText(config.output_path)
        self._set_combo_data(self.format_combo, config.subtitle_format)
        self._set_combo_data(self.txt_mode_combo, config.txt_mode)
        self.txt_duration_spin.setValue(config.txt_fixed_duration)
        self.hold_after_spin.setValue(config.hold_after_sentence)
        self.min_display_spin.setValue(config.min_display_duration)
        self.max_display_spin.setValue(config.max_display_duration)
        self.use_silence_detect_check.setChecked(config.use_silence_detection)
        self._load_style_to_controls(config.style)

        if config.video_path:
            self.load_video_info(config.video_path)
        if config.subtitle_path:
            self.parse_subtitles()
        self.log(f"Loaded project config: {path}")

    def _update_preview_from_controls(self, *args) -> None:
        del args
        self._refresh_alignment_offset_ui()
        self.preview_widget.set_style(self.current_style())
        self.preview_selected_subtitle()

    def _refresh_alignment_offset_ui(self) -> None:
        base_style = self.current_style_for_offset_display()
        manual = str(self.alignment_offset_mode_combo.currentData()) == "manual"
        self.horizontal_margin_spin.setEnabled(manual)
        self.bottom_margin_spin.setEnabled(manual)
        self.alignment_reference_label.setText(f"Reference: {self._alignment_reference_text(base_style.alignment)}")
        if self.video_info:
            auto_x = auto_horizontal_margin(self.video_info, base_style)
            auto_y = auto_bottom_margin(self.video_info, base_style)
            self.auto_alignment_offset_label.setText(f"Auto X: {auto_x} px | Auto Y: {auto_y} px")
        else:
            self.auto_alignment_offset_label.setText("Auto X: - | Auto Y: -")

        row = self.subtitle_table.currentRow()
        if self.subtitle_doc and 0 <= row < len(self.subtitle_doc.cues):
            self._refresh_cue_alignment_offset_ui(self.subtitle_doc.cues[row])

    def current_style_for_offset_display(self) -> SubtitleStyle:
        return SubtitleStyle(
            alignment=str(self.alignment_combo.currentData()),
            safe_area_mode=str(self.safe_area_combo.currentData()),
            custom_safe_area_percent=int(self.custom_safe_spin.value()),
            bottom_margin=int(self.bottom_margin_spin.value()),
            horizontal_margin=int(self.horizontal_margin_spin.value()),
        )

    def _alignment_reference_text(self, alignment: str) -> str:
        mapping = {
            "bottom_center": "bottom edge + horizontal center",
            "bottom_left": "bottom edge + left edge",
            "bottom_right": "bottom edge + right edge",
            "top_center": "top edge + horizontal center",
            "center": "video center",
        }
        return mapping.get(alignment, "selected alignment anchor")

    def _update_summary(self) -> None:
        video = "-"
        if self.video_info:
            video = (
                f"{self.video_info.path.name} | {self.video_info.width}x{self.video_info.height} | "
                f"{self.video_info.aspect_ratio_label} | {pretty_duration(self.video_info.duration)}"
            )
        count = len(self.subtitle_doc) if self.subtitle_doc else 0
        self.summary_label.setText(f"Video: {video} | Subtitle count: {count}")

    def _set_combo_data(self, combo: QComboBox, data: str) -> None:
        index = combo.findData(data)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _set_font_family(self, family: str) -> None:
        index = self.font_combo.findText(family, Qt.MatchFlag.MatchFixedString)
        if index < 0:
            self.font_combo.addItem(family)
            index = self.font_combo.count() - 1
        self.font_combo.setCurrentIndex(index)

    def _show_error(self, title: str, message: str) -> None:
        self.log(f"{title}: {message}")
        QMessageBox.critical(self, title, message)

    def log(self, message: str) -> None:
        self.log_view.append(message)
        self.statusBar().showMessage(message[:180], 7000)

    def _contrast_text(self, hex_color: str) -> str:
        color = QColor(hex_color)
        brightness = (color.red() * 299 + color.green() * 587 + color.blue() * 114) / 1000
        return "#111111" if brightness > 150 else "#FFFFFF"

    def _apply_light_stylesheet(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                font-family: Segoe UI, Tahoma, Arial;
                font-size: 10pt;
            }
            QGroupBox {
                border: 1px solid #C9D2DC;
                border-radius: 6px;
                margin-top: 10px;
                padding: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                color: #26323D;
                font-weight: 600;
            }
            QPushButton {
                border: 1px solid #8A98A8;
                border-radius: 6px;
                padding: 6px 10px;
                background: #FFFFFF;
            }
            QPushButton:hover {
                background: #E9F2FF;
            }
            QPushButton:disabled {
                color: #8A8F95;
                background: #ECEFF3;
            }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QTableWidget {
                border: 1px solid #B9C4D0;
                border-radius: 6px;
                padding: 4px;
                background: #FFFFFF;
            }
            QProgressBar {
                border: 1px solid #B9C4D0;
                border-radius: 6px;
                text-align: center;
                min-height: 20px;
            }
            QProgressBar::chunk {
                background: #2F7D5B;
                border-radius: 5px;
            }
            """
        )
