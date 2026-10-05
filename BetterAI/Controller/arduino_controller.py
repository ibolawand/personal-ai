"""
Fault-tolerant Arduino/WS2812B controller for Aria.

Matches your real Arduino sketch's protocol exactly:
- 9600 baud (Serial.begin(9600) in the sketch)
- Line-based text commands terminated with '\\n'
  (sketch reads with Serial.readStringUntil('\\n'))
- Recognized commands: MOOD:<name>, RGB:<r>,<g>,<b>, EFFECT:<name>,
  STARTUP, BRIGHT:<0-255>, OFF, SLEEP

Method surface matches what Aria.py calls:
  send_command(cmd: str = None), stop_talking(), off(), close(),
  startup_animation(), sleep_mode()

Design goals:
- Aria must start and run fully even if the Arduino is not connected,
  not connected yet, or gets unplugged mid-session.
- Every method below is always safe to call — no exceptions — it just
  no-ops (with a debug log) when there's no hardware.
- A background watchdog thread keeps trying to (re)connect without
  blocking the main app or requiring a restart.
"""

import glob
import logging
import platform
import threading
import time
from typing import Optional

import serial
from serial import SerialException

logger = logging.getLogger("aria.arduino")

BAUDRATE = 9600  # must match Serial.begin(9600) in the sketch


class ArduinoLEDController:
    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: int = BAUDRATE,
        retry_interval: float = 5.0,
        handshake_timeout: float = 2.0,
    ):
        self._port = port
        self._baudrate = baudrate
        self._retry_interval = retry_interval
        self._handshake_timeout = handshake_timeout

        self._serial: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._connected = False

        # Synchronous first attempt so is_connected is accurate right
        # away, but this can never raise even if it fails.
        self._try_connect(log_failure_as_warning=True)

        self._watchdog = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog.start()

    # ---------- public API used by Aria.py ----------

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    def send_command(self, command: Optional[str] = None) -> bool:
        """
        Send a raw text command (without the trailing newline — added
        here). Aria.py calls this with no argument in speak() right
        before talking starts, so it defaults to switching the LED
        effect to "talking".
        """
        cmd = command if command is not None else "EFFECT:talking"
        return self._write(cmd)

    def stop_talking(self) -> bool:
        return self._write("EFFECT:breathe")

    def off(self) -> bool:
        return self._write("OFF")

    def startup_animation(self) -> bool:
        return self._write("STARTUP")

    def sleep_mode(self) -> bool:
        return self._write("SLEEP")

    def set_mood(self, mood: str) -> bool:
        """Not currently called from Aria.py but matches the sketch's MOOD: command."""
        return self._write(f"MOOD:{mood}")

    def set_rgb(self, r: int, g: int, b: int) -> bool:
        """Not currently called from Aria.py but matches the sketch's RGB: command."""
        return self._write(f"RGB:{r},{g},{b}")

    def set_brightness(self, value: int) -> bool:
        """Not currently called from Aria.py but matches the sketch's BRIGHT: command."""
        return self._write(f"BRIGHT:{max(0, min(255, value))}")

    def close(self):
        """Alias for shutdown() — Aria.py calls .close() in its cleanup paths."""
        self.shutdown()

    def shutdown(self):
        self._stop_event.set()
        self._watchdog.join(timeout=self._retry_interval + 1)
        with self._lock:
            if self._serial is not None:
                try:
                    self._serial.close()
                except Exception:
                    pass
            self._serial = None
            self._connected = False

    # ---------- internals ----------

    def _write(self, cmd: str) -> bool:
        with self._lock:
            if not self._connected or self._serial is None:
                logger.debug("Skipped (no Arduino connected): %r", cmd)
                return False
            try:
                self._serial.write((cmd + "\n").encode("utf-8"))
                return True
            except (SerialException, OSError) as e:
                logger.warning("Lost Arduino connection during write: %s", e)
                self._mark_disconnected()
                return False

    def _candidate_ports(self):
        if self._port:
            return [self._port]
        system = platform.system()
        if system == "Linux":
            return sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
        if system == "Darwin":
            return sorted(glob.glob("/dev/tty.usbserial*") + glob.glob("/dev/tty.usbmodem*"))
        if system == "Windows":
            return [f"COM{i}" for i in range(1, 21)]
        return []

    def _try_connect(self, log_failure_as_warning: bool = False) -> bool:
        for candidate in self._candidate_ports():
            try:
                ser = serial.Serial(candidate, self._baudrate, timeout=1)
                time.sleep(self._handshake_timeout)  # let the board reset/boot
                with self._lock:
                    self._serial = ser
                    self._connected = True
                logger.info("Arduino connected on %s", candidate)
                return True
            except (SerialException, OSError) as e:
                logger.debug("Arduino not found on %s: %s", candidate, e)
                continue

        with self._lock:
            self._connected = False
            self._serial = None

        msg = "No Arduino found — running in no-hardware mode (LEDs disabled)."
        if log_failure_as_warning:
            logger.warning(msg)
        else:
            logger.debug(msg)
        return False

    def _mark_disconnected(self):
        with self._lock:
            if self._serial is not None:
                try:
                    self._serial.close()
                except Exception:
                    pass
            self._serial = None
            self._connected = False
        logger.warning("Arduino marked disconnected — will keep retrying in background.")

    def _watchdog_loop(self):
        while not self._stop_event.is_set():
            if not self.is_connected:
                self._try_connect()
            self._stop_event.wait(self._retry_interval)