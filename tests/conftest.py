"""Shared pytest fixtures for the aram_picker test suite."""

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """Single QApplication shared by all test modules.

    qfluentwidgets keeps a global QConfig tied to the QApplication; letting
    each module create (and garbage-collect) its own app leaves dangling
    C++ references and crashes later modules with RuntimeError.
    """
    return QApplication.instance() or QApplication([])
