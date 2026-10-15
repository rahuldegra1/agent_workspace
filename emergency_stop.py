import os
import threading

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

try:
    from pynput.keyboard import GlobalHotKeys
except ImportError:  # pragma: no cover
    GlobalHotKeys = None


EMERGENCY_HOTKEY = "<ctrl>+<alt>+<shift>+q"
_listener = None
_listener_lock = threading.Lock()


def emergency_abort() -> None:
    _kill_descendants(os.getpid())
    os._exit(1)


def _kill_descendants(root_pid: int) -> None:
    if psutil is None:
        return
    try:
        descendants = psutil.Process(root_pid).children(recursive=True)
    except (psutil.Error, OSError):
        return
    for child in descendants:
        try:
            child.kill()
        except (psutil.Error, OSError):
            pass


def abort_process_tree(root_pid: int) -> None:
    _kill_descendants(root_pid)
    if psutil is not None:
        try:
            psutil.Process(root_pid).kill()
        except (psutil.Error, OSError):
            pass
    os._exit(1)


def start_emergency_stop() -> bool:
    global _listener
    if GlobalHotKeys is None:
        return False

    with _listener_lock:
        if _listener is not None and _listener.is_alive():
            return True
        try:
            listener = GlobalHotKeys({EMERGENCY_HOTKEY: emergency_abort})
            listener.daemon = True
            listener.start()
            _listener = listener
            return True
        except Exception:
            return False


def watch_process(root_pid: int) -> None:
    if GlobalHotKeys is None:
        raise RuntimeError("pynput is required for the emergency hotkey")
    listener = GlobalHotKeys({EMERGENCY_HOTKEY: lambda: abort_process_tree(root_pid)})
    listener.start()
    listener.join()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", type=int, required=True)
    watch_process(parser.parse_args().watch)