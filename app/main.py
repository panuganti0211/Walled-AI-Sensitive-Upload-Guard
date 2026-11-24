"""Application entry point and lifecycle manager."""

import sys
from PySide6.QtWidgets import QApplication

from app.desktop.main_window import MainWindow


def create_app() -> QApplication:
    """Create or retrieve the QApplication instance."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setApplicationName("Walled AI Sensitive Upload Guard")
        app.setOrganizationName("WalledAI")
    return app


def main():
    """Main application routine."""
    app = create_app()
    window = MainWindow()
    window.show()

    # Support non-blocking headless / dry-run execution for CI/verification
    if "--dry-run" in sys.argv:
        print("Application initialized successfully in dry-run mode.")
        return 0

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
