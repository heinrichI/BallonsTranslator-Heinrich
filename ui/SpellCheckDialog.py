import sys
from qtpy.QtWidgets import (
    QApplication, QDialog, QLabel, QLineEdit, QPushButton, QTextEdit,
    QGroupBox, QListWidget, QHBoxLayout, QVBoxLayout, QSizePolicy, QWidget
)
from qtpy.QtGui import QPixmap, QImage, QFont, QTextCursor, QTextCharFormat, QColor, QTextDocument
from qtpy.QtCore import Qt

from utils.logger import logger as LOGGER

class SpellCheckDialog(QDialog):
    # Skip = 1001
    SkipAll = 1002
    # SkipWithRegistry = 1003
    ReplaceAll = 1004
    EditAllText = 1005

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle("Word Editor Window")
        self.setMinimumSize(800, 600)
        self.setup_ui()

    def setText(self, allText: str, word: str, img: QImage, suggestions):
        self.text_edit.setPlainText(allText)

        self.before_word = word
        self.word_line_edit.setText(word)
        pixmap = QPixmap().fromImage(img)
        self.image_label.setPixmap(pixmap)
        self.image_label.setScaledContents(False)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.suggestions_list.addItems(suggestions)

        # Highlight the word in the text_edit
        self.highlight_one_word(word, QColor(Qt.blue), QColor(Qt.yellow))

    def highlight_one_word(self, word: str, color: QColor, bgcolor: QColor):
        """
        Highlights exactly one occurrence of `word` in the QTextEdit
        (whole-word, case-sensitive), then stops.
        """
        # 1) prepare your QTextCharFormat
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        fmt.setBackground(bgcolor)

        # 2) start at top of document
        doc = self.text_edit.document()
        start_cursor = QTextCursor(doc)
        start_cursor.movePosition(QTextCursor.Start)

        # 3) search for the whole word, case-sensitive
        flags = QTextDocument.FindWholeWords | QTextDocument.FindCaseSensitively
        found_cursor = doc.find(word, start_cursor, flags)

        # 4) if we found it, apply the format
        if not found_cursor.isNull():
            found_cursor.mergeCharFormat(fmt)
        else:
            LOGGER.debug(f"No occurrence of `{word}` found.")

    def highlight_word(self, word: str, color: QColor, bgcolor: QColor):
        """Highlights all occurrences of a word in the text edit with the given color and background color."""
        # Create a format for highlighting
        format = QTextCharFormat()
        format.setForeground(color)  # Font color
        format.setBackground(bgcolor)  # Background color

        # Find and highlight all occurrences of the word
        cursor = QTextCursor(self.text_edit.document())
        cursor.movePosition(QTextCursor.Start)  # Move cursor to the start of the document
        while not cursor.atEnd():
            cursor = self.text_edit.document().find(word, cursor)  # Find the word
            if cursor.isNull():  # If no more occurrences are found
                LOGGER.debug(f'no more occurrences are found for highlight {word}')
                break
            cursor.mergeCharFormat(format)  # Apply the highlight format
            cursor.movePosition(QTextCursor.NextCharacter)  # Move past the found word to continue searching

    def setup_ui(self):
        main_layout = QVBoxLayout(self)

        # 1. Upper part: Display an image.
        self.image_label = QLabel(self)
        self.image_label.setMinimumHeight(150)  # Set the minimum height here
        # Replace "path/to/your/image.png" with the path to your image file.
        # pixmap = QPixmap("path/to/your/image.png")
        # if pixmap.isNull():
        #     # If the image is not found, show a placeholder text.
        #     self.image_label.setText("Image not found")
        #     self.image_label.setAlignment(Qt.AlignCenter)
        #     # Optionally, give it a fixed height.
        #     self.image_label.setMinimumHeight(150)
        # else:
        #     self.image_label.setPixmap(pixmap)
        #     self.image_label.setScaledContents(True)
        #     self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_layout.addWidget(self.image_label)

        # 2. Second row: A long block of text on the left and a button to the right.
        text_row_layout = QHBoxLayout()
        self.text_edit = QTextEdit(self)
        # self.text_edit.setReadOnly(True)
        # self.text_edit.setPlainText(
        #     "Lorem ipsum dolor sit amet, consectetur adipiscing elit. \n"
        #     "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n"
        #     "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat."
        # )
        self.all_text_button = QPushButton("Edit all text", self)
        # Give the text area more space than the button.
        text_row_layout.addWidget(self.text_edit, stretch=3)
        text_row_layout.addWidget(self.all_text_button, stretch=1)
        main_layout.addLayout(text_row_layout)
        self.all_text_button.clicked.connect(self.all_text_edited)

        # 3. Third row: Two groups side by side.
        groups_layout = QHBoxLayout()

        # 3.a Left group: "Word not on"
        self.group_word_not_on = QGroupBox("Word not on", self)
        word_group_layout = QVBoxLayout(self.group_word_not_on)
        # Word editing field at the top.
        self.word_line_edit = QLineEdit(self.group_word_not_on)
        self.word_line_edit.setPlaceholderText("Edit word here...")
        word_group_layout.addWidget(self.word_line_edit)
        # Row of buttons.
        word_buttons_layout = QHBoxLayout()
        self.replace_all_btn = QPushButton("Replace All", self.group_word_not_on)
        # self.replace_btn = QPushButton("Replace", self.group_word_not_on)
        # self.skip_btn = QPushButton("Skip", self.group_word_not_on)
        self.skip_all_btn = QPushButton("Skip All", self.group_word_not_on)
        # self.add_btn = QPushButton("Add (case)", self.group_word_not_on)  # "Add a name taking into account the case"
        word_buttons_layout.addWidget(self.replace_all_btn)
        # word_buttons_layout.addWidget(self.replace_btn)
        # word_buttons_layout.addWidget(self.skip_btn)
        word_buttons_layout.addWidget(self.skip_all_btn)
        # word_buttons_layout.addWidget(self.add_btn)
        word_group_layout.addLayout(word_buttons_layout)
        groups_layout.addWidget(self.group_word_not_on)

        # 3.b Right group: "Suggested word options"
        self.group_suggested = QGroupBox("Suggested word options", self)
        suggested_layout = QVBoxLayout(self.group_suggested)
        # List field for suggested words.
        self.suggestions_list = QListWidget(self.group_suggested)
        # For demonstration, add some list items.
        # self.suggestions_list.addItems(["Suggestion 1", "Suggestion 2", "Suggestion 3"])
        suggested_layout.addWidget(self.suggestions_list)
        # Row of buttons: Apply and Remember.
        suggestions_buttons_layout = QHBoxLayout()
        self.apply_btn = QPushButton("Apply", self.group_suggested)
        self.replace_suggested_btn = QPushButton("Replace all", self.group_suggested)
        suggestions_buttons_layout.addWidget(self.apply_btn)
        suggestions_buttons_layout.addWidget(self.replace_suggested_btn)
        suggested_layout.addLayout(suggestions_buttons_layout)
        groups_layout.addWidget(self.group_suggested)
        self.suggestions_list.itemSelectionChanged.connect(self.update_buttons_state)
        self.update_buttons_state()  # Ensure buttons are disabled initially
        # Apply a custom style to make disabled buttons more distinguishable
        btn_style = """
        QPushButton {
            padding: 5px;
            font-weight: bold;
        }
        QPushButton:disabled {
            background-color: #cccccc;
            color: #666666;
            border: 1px solid #999999;
        }
        """
        self.apply_btn.setStyleSheet(btn_style)
        self.replace_suggested_btn.setStyleSheet(btn_style)

        main_layout.addLayout(groups_layout)

        # 4. Bottom: Abort button.
        self.abort_btn = QPushButton("Abort", self)
        self.abort_btn.clicked.connect(self.reject)
        main_layout.addWidget(self.abort_btn, alignment=Qt.AlignRight)

        # Connect buttons to actions
        # self.text_button.clicked.connect(self.accept)  # Just accept with no specific state
        self.replace_all_btn.clicked.connect(self.replace_all)
        # self.change_btn.clicked.connect(self.change)
        # self.skip_btn.clicked.connect(self.skip)
        self.skip_all_btn.clicked.connect(self.skip_all)
        self.abort_btn.clicked.connect(self.reject)

        # Initialize state
        self.state = None

    def update_buttons_state(self):
        has_selection = bool(self.suggestions_list.selectedItems())
        self.apply_btn.setEnabled(has_selection)
        self.replace_suggested_btn.setEnabled(has_selection)

    def skip(self):
        self.state = SpellCheckDialog.Skip
        self.accept()

    def skip_all(self):
        self.state = SpellCheckDialog.SkipAll
        self.accept()

    def replace_all(self):
        self.state = SpellCheckDialog.ReplaceAll
        self.accept()

    def all_text_edited(self):
        self.state = SpellCheckDialog.EditAllText
        self.accept()

    # def change(self):
    #     self.state = "Change"
    #     self.accept()
