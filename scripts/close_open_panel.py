"""
LABEL: Toggle Waypanel
DESCRIPTION: This script toggles the Waypanel (Wayland panel) state - closes it if running,
             or opens it if not running. Executes non-blocking for immediate script completion.
"""

import subprocess


def is_waypanel_running():
    """Check if waypanel process is currently running"""
    try:
        # Use pgrep for more reliable process checking
        subprocess.run(
            ["pgrep", "-x", "waypanel"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def toggle_waypanel():
    """Toggle waypanel state (start if stopped, stop if running)"""
    if is_waypanel_running():
        # Kill existing waypanel
        subprocess.Popen(["pkill", "-x", "waypanel"])
    else:
        # Launch new waypanel (non-blocking)
        subprocess.Popen(["waypanel"])


if __name__ == "__main__":
    toggle_waypanel()
