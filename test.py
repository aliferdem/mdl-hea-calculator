import sys
from PySide6.QtWidgets import QApplication, QWidget, QFrame, QVBoxLayout
from PySide6.QtCore import Qt
from ctypes import windll

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Custom Title Bar Color")
        self.setWindowFlags(Qt.Window)  # Keep the default title bar

        # Use windll to change title bar color
        user32 = windll.user32
        user32.SetSysColor(17, 0x007BFF)  # Change title bar color to blue

        # Create main content area
        self.content_area = QFrame()
        self.content_area.setStyleSheet("background-color: #F0F0F0;")

        # Layout
        layout = QVBoxLayout()
        layout.addWidget(self.content_area)

        self.setLayout(layout)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())