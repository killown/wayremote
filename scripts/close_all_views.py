"""
LABEL: Close All Windows
DESCRIPTION: This script will close all toplevel views.
"""

from wayfire.ipc import WayfireSocket
from wayfire.extra import stipc

sock = WayfireSocket()
stipc = stipc.Stipc(sock)

[
    sock.close_view(view["id"])
    for view in sock.list_views()
    if view["role"] == "toplevel"
]
