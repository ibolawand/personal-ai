"""Desktop settings dialog, kept independent of the animated overlay."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QLabel, QLineEdit)


class SettingsDialog(QDialog):
    def __init__(self, aria, parent=None):
        super().__init__(parent)
        self.aria = aria
        self.setWindowTitle("Aria settings")
        self.setMinimumWidth(380)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        form = QFormLayout(self)
        values = aria.settings_snapshot()
        self.microphone = QComboBox()
        self.microphone.addItem("Typing / listen on request", "typing")
        self.microphone.addItem("Wake word and voice", "wake")
        self.microphone.setCurrentIndex(self.microphone.findData(values["microphone"]))
        form.addRow("Microphone mode", self.microphone)
        form.addRow(QLabel("Microphone mode takes effect after restarting Aria."))
        self.checks = {}
        for key, label in (("muted", "Mute spoken replies"), ("autonomous_chats", "Let Aria and Claude chat on their own"),
                           ("claude", "Use Claude for heavy tasks and duets")):
            box = QCheckBox(label)
            box.setChecked(values[key])
            self.checks[key] = box
            form.addRow(box)
        notice = QLabel("Claude receives task text online. Turning it off keeps those tasks local.")
        notice.setWordWrap(True)
        form.addRow(notice)
        self.quiet = QLineEdit(values["quiet_hours"])
        self.quiet.setPlaceholderText("22:30-08:30 (empty = off)")
        form.addRow("Quiet hours", self.quiet)
        form.addRow(QLabel("Pauses companion activity, posture nudges and autonomous chats."))
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.PlainText)
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self):
        values = {key: box.isChecked() for key, box in self.checks.items()}
        values.update(microphone=self.microphone.currentData(), quiet_hours=self.quiet.text().strip())
        try:
            self.aria.save_settings(values)
        except (ValueError, OSError) as e:
            self.error.setText(str(e))
            return
        self.accept()
