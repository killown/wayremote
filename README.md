# Wayfire Remote Control

A **remote control app** for Wayfire compositor using IPC (Inter-Process Communication). This app is designed to act as a **TV remote**, allowing you to control your Wayfire-based system from a web interface. It supports cursor movement, keyboard input, volume control, and launching popular streaming apps directly on your system.

---

## ✨ Features

- **Remote Cursor Control**: Move the cursor using touch or mouse input.
- **Keyboard Input**: Activate an on-screen keyboard for text input.
- **Volume Control**: Adjust system volume directly from the remote.
- **Streaming App Launcher**: Open popular streaming apps like Netflix, Max, Crunchyroll, and more directly in Firefox.
- **WebSocket Communication**: Real-time communication between the web interface and the Wayfire compositor.
- **Responsive Design**: Works seamlessly on both desktop and mobile devices.
- **Customizable Speed**: Adjust cursor movement speed with a slider.

---

## 🛠️ Technologies Used

- **Backend**: Python (Quart framework for WebSocket and HTTP server)
- **Frontend**: HTML, CSS (Bootstrap), JavaScript
- **Wayfire IPC**: Inter-process communication with Wayfire compositor
- **Volume Control**: Uses `pactl` or `amixer` for system volume adjustment.

---

## 🚀 Getting Started

### Prerequisites

- Python 3.7+
- Wayfire compositor
- Microsoft-Edge (for opening streaming apps)
- `wayfire.ipc` library (for IPC communication)
- `pactl` or `amixer` (for volume control)

### Usage

1. Clone the repository:
   ```bash
   git clone https://github.com/killown/wayremote.git
   cd wayremote
   python wayremote.py
   firefox localhost:5000
   
<img src="https://github.com/user-attachments/assets/0f13a527-9753-4a04-b786-e7eb95c485f7" style="width:25%; max-width:300px;" alt="Image 1">
<img src="https://github.com/user-attachments/assets/d1d3cff0-2018-4e61-97fe-bb976a2eb6fe" style="width:25%; max-width:300px;" alt="Image 2">




