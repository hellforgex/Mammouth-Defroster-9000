import tkinter as tk
import pytest


@pytest.fixture(autouse=True)
def cleanup_tk_after_callbacks():
    """Ensure all pending Tk after callbacks are cancelled after each test."""
    yield
    try:
        root = getattr(tk, "_default_root", None)
        if root is not None:
            if hasattr(root, "cancel_scheduled_afters"):
                try:
                    root.cancel_scheduled_afters()
                except Exception:
                    pass
            if hasattr(root, "tk") and root.tk:
                for aid in list(root.tk.call("after", "info")):
                    try:
                        root.tk.call("after", "cancel", aid)
                    except Exception:
                        pass
    except Exception:
        pass
