"""UI package for Desktop Intelligence."""


def __getattr__(name):
    if name == "MainWindow":
        from desktop_intelligence.ui.main_window import MainWindow
        return MainWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["MainWindow"]

