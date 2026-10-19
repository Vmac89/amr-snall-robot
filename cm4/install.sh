#!/usr/bin/env bash
# Install Mission Control on the Raspberry Pi CM4 (Raspberry Pi OS).
# Dependencies, dialout for the UART, and a systemd unit.
# Does not flash the ESP32, does not edit the boot config, and does not
# arm poweroff. Confirm package names on the image you are using.
set -euo pipefail

if [[ "${EUID}" -eq 0 ]]; then
  echo "Run this as the login user. The script calls sudo itself." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_SRC="${ROOT}/cm4/server/amr-mission-control.service"
UNIT_DST="/etc/systemd/system/amr-mission-control.service"

echo "Repo: ${ROOT}"
sudo apt-get update
sudo apt-get install -y python3-flask python3-serial python3-pil

if apt-cache show python3-freenect >/dev/null 2>&1; then
  sudo apt-get install -y python3-freenect libfreenect-dev \
    || echo "freenect packages did not install. /video_feed stays on the placeholder."
else
  echo "python3-freenect is not in this apt cache. Kinect support stays optional."
fi

if ! id -nG "${USER}" | tr ' ' '\n' | grep -qx dialout; then
  sudo usermod -aG dialout "${USER}"
  echo "Added ${USER} to dialout. Log out and back in before opening the UART."
else
  echo "${USER} is already in dialout."
fi

# Raspberry Pi OS grants /dev/ttyAMA*, /dev/ttyS*, and /dev/ttyUSB* to dialout.
# This script does not add a udev rule, because the carrier's UART name is unset.

python3 - "${UNIT_SRC}" "${ROOT}" "${USER}" <<'PY'
import pathlib
import sys
src, root, user = sys.argv[1:]
text = pathlib.Path(src).read_text()
text = text.replace("User=amr", f"User={user}")
text = text.replace("/opt/amr-snall-robot", root)
pathlib.Path("/tmp/amr-mission-control.service").write_text(text)
PY
sudo cp /tmp/amr-mission-control.service "${UNIT_DST}"
rm -f /tmp/amr-mission-control.service
sudo systemctl daemon-reload
sudo systemctl enable amr-mission-control.service

cat <<EOF

Installed ${UNIT_DST}
  User=${USER}
  WorkingDirectory and ExecStart point at ${ROOT}
  AMR_ALLOW_POWEROFF stays 0
  AMR_SERIAL_PORT is still /dev/ttyAMA0 until you edit the unit

This script does not change the boot config. A wrong UART overlay can keep
the board from booting. On the carrier, confirm enable_uart=1 (and the
overlay that matches this board) in /boot/firmware/config.txt or
/boot/config.txt, then reboot.

This script does not create a virtualenv. Flask, pyserial, and Pillow are
the system packages, and the service runs /usr/bin/python3.
Do not look for ${ROOT}/cm4/server/.venv/bin/activate.

Mock run, from the repo, with the system interpreter:
  python3 ${ROOT}/cm4/server/server.py --mock-serial --host 0.0.0.0 --port 8080

Start the service now:
  sudo systemctl restart amr-mission-control.service

Bring-up checklist: ${ROOT}/docs/bring-up.md
EOF
