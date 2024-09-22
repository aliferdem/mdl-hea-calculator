from PySide6.QtWidgets import QApplication, QScrollArea, QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

class FadeEffectWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background-color: rgba(0, 0, 0, 150);")  # Semi-transparent black

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

        # Create a scroll area
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)

        # Create a content widget
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)

        # Add multiple labels for scrolling
        for i in range(30):
            content_layout.addWidget(QLabel(f"Item {i + 1}"))

        self.scroll_area.setWidget(content_widget)
        layout.addWidget(self.scroll_area)

        # Create the fade effect widget and set its size
        self.fade_effect_widget = FadeEffectWidget()
        self.fade_effect_widget.setFixedHeight(50)  # Adjust height as needed
        layout.addWidget(self.fade_effect_widget)

        self.setLayout(layout)
        self.resize(400, 300)

        # Adjust the fade effect position
        self.fade_effect_widget.raise_()  # Bring it to the front

if __name__ == "__main__":
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()
