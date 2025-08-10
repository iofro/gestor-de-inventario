import os
import sys
import pytest
from PyQt5.QtWidgets import QApplication

@pytest.fixture(scope="session")
def qt_app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return QApplication.instance() or QApplication(sys.argv)
