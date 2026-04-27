#!/usr/bin/env python

# Copyright 2026 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""ROS2Camera — frames from a `sensor_msgs/Image` topic.

Subscribes to a ROS 2 image topic and exposes the latest frame as a numpy array,
matching lerobot's `Camera` abstract contract. Compatible with any ROS 2 driver,
including simulators bridged via `ros_gz_bridge`.

This file is a port of the original PR #866 (by Yadunund) to the current upstream
camera layout (`src/lerobot/cameras/<backend>/`). Key differences from PR #866:

- Implements the upstream `Camera.async_read(timeout_ms)` contract (return latest
  unconsumed frame, raise `TimeoutError` on stale buffer).
- `find_cameras()` shells out to `ros2 topic list -t` and filters for
  `sensor_msgs/msg/Image` topics (was missing in PR #866).
- Uses `ColorMode` and `Cv2Rotation` enums from upstream `configs.py`.
- Uses `check_if_already_connected` / `check_if_not_connected` decorators.
- Uses `DeviceNotConnectedError` from `lerobot.utils.errors`.
- Drops the buggy `if __name__ == "__main__"` driver block from PR #866.

Class-level singletons for `rclpy_node`, `spin_thread`, and `cv_bridge` are kept
(same design as PR #866): many `ROS2Camera` instances share one rclpy context and
one background spin thread so that multiple image topics are pumped by a single
node. The first instance initializes rclpy; the last one to `disconnect()` tears
it down.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from typing import TYPE_CHECKING, Any, ClassVar

import cv2
import numpy as np
from numpy.typing import NDArray

from lerobot.utils.decorators import (
    check_if_already_connected,
    check_if_not_connected,
)
from lerobot.utils.errors import DeviceNotConnectedError
from lerobot.utils.import_utils import (
    _rclpy_available,
    require_package,
)

from ..camera import Camera
from ..configs import ColorMode, Cv2Rotation
from .configuration_ros2 import ROS2CameraConfig

if TYPE_CHECKING or _rclpy_available:
    import rclpy  # type: ignore
    import rclpy.node  # type: ignore
    import rclpy.subscription  # type: ignore
    from sensor_msgs.msg import Image as ImageMsg  # type: ignore
else:
    rclpy = None  # type: ignore
    ImageMsg = None  # type: ignore


# Mapping from ROS 2 sensor_msgs/Image encoding → (numpy dtype, channels, is_rgb_order).
# Covers the encodings lerobot users are likely to hit. See
# https://docs.ros.org/en/jazzy/p/sensor_msgs/msg/Image.html and
# sensor_msgs/image_encodings.hpp for the full list.
_ENCODING_TABLE: dict[str, tuple[str, int, bool]] = {
    # 8-bit color
    "rgb8": ("uint8", 3, True),
    "bgr8": ("uint8", 3, False),
    "rgba8": ("uint8", 4, True),
    "bgra8": ("uint8", 4, False),
    # 16-bit color
    "rgb16": ("uint16", 3, True),
    "bgr16": ("uint16", 3, False),
    # grayscale
    "mono8": ("uint8", 1, True),
    "mono16": ("uint16", 1, True),
    # depth-style
    "16uc1": ("uint16", 1, True),
    "32fc1": ("float32", 1, True),
}


def _image_msg_to_ndarray(msg: Any, requested_encoding: str) -> NDArray[Any]:
    """Decode a `sensor_msgs/Image` message to a numpy array without cv_bridge.

    cv_bridge's conda binaries are compiled against numpy 1.x and break on
    numpy>=2. This function replaces it with a pure-numpy reshape based on
    the encoding metadata, which works under any numpy ABI.

    `requested_encoding == "passthrough"` uses `msg.encoding`; otherwise the
    caller-requested encoding is used for layout (mismatch logs a warning
    but still reshapes to the caller's expected channel count).
    """
    effective_encoding = msg.encoding if requested_encoding == "passthrough" else requested_encoding
    effective_encoding = (effective_encoding or "").lower()

    if effective_encoding not in _ENCODING_TABLE:
        raise ValueError(
            f"Unsupported sensor_msgs/Image encoding '{effective_encoding}'. "
            f"Supported: {sorted(_ENCODING_TABLE)}."
        )
    dtype_str, channels, _ = _ENCODING_TABLE[effective_encoding]

    buf = np.frombuffer(msg.data, dtype=np.dtype(dtype_str))
    if channels == 1:
        arr = buf.reshape(msg.height, msg.width)
    else:
        arr = buf.reshape(msg.height, msg.width, channels)
    return arr

logger = logging.getLogger(__name__)


_CV2_ROTATION_TO_FLAG: dict[Cv2Rotation, int | None] = {
    Cv2Rotation.NO_ROTATION: None,
    Cv2Rotation.ROTATE_90: cv2.ROTATE_90_CLOCKWISE,
    Cv2Rotation.ROTATE_180: cv2.ROTATE_180,
    Cv2Rotation.ROTATE_270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}


class _ROS2CameraTopic:
    """Bundles a subscription with its latest message + arrival timestamp.

    Access is protected by a per-topic lock so `read()` / `async_read()` never
    tear a message mid-write from the spin thread.
    """

    def __init__(self, subscription: Any, config: ROS2CameraConfig) -> None:
        self.subscription = subscription
        self.config = config
        self.lock = threading.Lock()
        self.latest_msg: Any | None = None
        self.last_received_time: float = 0.0
        self.last_consumed_time: float = 0.0

    def update(self, msg: Any) -> None:
        with self.lock:
            self.latest_msg = msg
            self.last_received_time = time.perf_counter()

    @property
    def has_message(self) -> bool:
        return self.latest_msg is not None


class ROS2Camera(Camera):
    """Reads frames from a ROS 2 `sensor_msgs/Image` topic.

    Multiple `ROS2Camera` instances share a single `rclpy_node` and background
    spin thread. The first instance initializes rclpy; the last to disconnect
    tears everything down.

    Example:
        ```python
        from lerobot.cameras.ros2 import ROS2Camera, ROS2CameraConfig

        cfg = ROS2CameraConfig(topic="/wrist_camera", fps=30, width=1280, height=720)
        cam = ROS2Camera(cfg)
        cam.connect()
        frame = cam.read()   # (H, W, 3) uint8
        cam.disconnect()
        ```
    """

    # Class-level singletons shared across all ROS2Camera instances.
    _rclpy_initialized: ClassVar[bool] = False
    _rclpy_node: ClassVar[Any | None] = None
    _spin_thread: ClassVar[threading.Thread | None] = None
    _stop_event: ClassVar[threading.Event | None] = None
    _subscriptions: ClassVar[dict[str, _ROS2CameraTopic]] = {}
    _class_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, config: ROS2CameraConfig) -> None:
        require_package("rclpy", extra="ros2", import_name="rclpy")

        super().__init__(config)

        if config.mock:
            raise NotImplementedError(
                "ROS2CameraConfig(mock=True) is not implemented yet."
            )

        self.config = config
        self.topic: str = config.topic
        self.encoding: str = config.encoding
        self.color_mode: ColorMode = config.color_mode
        self.rotation: Cv2Rotation = config.rotation
        self._connected = False

        self._ensure_rclpy_started()

    def __str__(self) -> str:
        return f"ROS2Camera({self.topic})"

    # ------------------------------------------------------------------ rclpy

    @classmethod
    def _ensure_rclpy_started(cls) -> None:
        with cls._class_lock:
            if not cls._rclpy_initialized:
                rclpy.init()
                cls._rclpy_initialized = True
            if cls._rclpy_node is None:
                cls._rclpy_node = rclpy.create_node("lerobot_ros2_camera_node")
                cls._stop_event = threading.Event()
            if cls._spin_thread is None or not cls._spin_thread.is_alive():
                assert cls._stop_event is not None
                cls._stop_event.clear()
                cls._spin_thread = threading.Thread(
                    target=cls._spin_loop, daemon=True, name="lerobot_ros2_camera_spin"
                )
                cls._spin_thread.start()

    @classmethod
    def _spin_loop(cls) -> None:
        assert cls._rclpy_node is not None
        assert cls._stop_event is not None
        while rclpy.ok() and not cls._stop_event.is_set():
            rclpy.spin_once(cls._rclpy_node, timeout_sec=0.05)

    @classmethod
    def _maybe_shutdown_rclpy(cls) -> None:
        """Tear down shared rclpy resources if no subscriptions remain."""
        with cls._class_lock:
            if cls._subscriptions:
                return
            if cls._stop_event is not None:
                cls._stop_event.set()
            if cls._spin_thread is not None and cls._spin_thread.is_alive():
                cls._spin_thread.join(timeout=1.0)
                cls._spin_thread = None
            if cls._rclpy_node is not None:
                try:
                    cls._rclpy_node.destroy_node()
                except Exception:  # nosec B110 — best-effort cleanup
                    pass
                cls._rclpy_node = None
            if cls._rclpy_initialized:
                try:
                    rclpy.shutdown()
                except Exception:  # nosec B110
                    pass
                cls._rclpy_initialized = False
            cls._stop_event = None

    # --------------------------------------------------------------- contract

    @property
    def is_connected(self) -> bool:
        return (
            self._connected
            and self.topic in type(self)._subscriptions
            and type(self)._rclpy_node is not None
        )

    @staticmethod
    def find_cameras() -> list[dict[str, Any]]:
        """List ROS 2 `sensor_msgs/msg/Image` topics currently on the graph.

        Requires the `ros2 topic` CLI on PATH. Returns `[]` (with a warning)
        if the CLI is missing or times out — callers should treat absence as
        "no discovery available", not an error.
        """
        if shutil.which("ros2") is None:
            logger.warning("`ros2` CLI not found on PATH; cannot discover ROS2 cameras.")
            return []

        try:
            result = subprocess.run(
                ["ros2", "topic", "list", "-t"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("`ros2 topic list -t` failed: %s", exc)
            return []

        if result.returncode != 0:
            logger.warning("`ros2 topic list -t` returned %d: %s", result.returncode, result.stderr.strip())
            return []

        cameras: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            if "[sensor_msgs/msg/Image]" in line:
                topic = line.split(" ", 1)[0]
                cameras.append({"topic": topic, "type": "sensor_msgs/msg/Image"})
        return cameras

    @check_if_already_connected
    def connect(self, warmup: bool = True) -> None:
        self._ensure_rclpy_started()
        cls = type(self)

        assert cls._rclpy_node is not None
        sub = cls._rclpy_node.create_subscription(ImageMsg, self.topic, self._on_message, 10)
        cls._subscriptions[self.topic] = _ROS2CameraTopic(sub, self.config)
        self._connected = True

        logger.info("%s: subscribed.", self)

        if warmup:
            deadline = time.perf_counter() + self.config.warmup_s
            while not cls._subscriptions[self.topic].has_message:
                if time.perf_counter() >= deadline:
                    self._drop_subscription(final=False)
                    raise ConnectionError(
                        f"{self}: no message received on '{self.topic}' "
                        f"within warmup_s={self.config.warmup_s}s."
                    )
                time.sleep(0.05)

            # Populate width/height from the first message so downstream
            # consumers see the real image size.
            with cls._subscriptions[self.topic].lock:
                first_msg = cls._subscriptions[self.topic].latest_msg
            if first_msg is not None:
                self.width = int(first_msg.width)
                self.height = int(first_msg.height)

            logger.info("%s: first frame received (%dx%d).", self, self.width, self.height)

    def _on_message(self, msg: Any) -> None:
        # Runs on the background spin thread.
        cls = type(self)
        topic_entry = cls._subscriptions.get(self.topic)
        if topic_entry is None:
            return
        topic_entry.update(msg)

    # ------------------------------------------------------------------ read

    def _msg_to_ndarray(self, msg: Any) -> NDArray[np.uint8]:
        img = _image_msg_to_ndarray(msg, self.config.encoding)

        # Drop alpha for 4-channel sources (RGBA/BGRA). lerobot's dataset
        # schema is 3-channel; doing the strip here is cheap (single
        # contiguous slice) and avoids forcing publishers — including
        # GPU-pinned viewport buffers in Isaac Sim — to do the strip in
        # render-thread callbacks where it kills frame rate.
        if img.ndim == 3 and img.shape[2] == 4:
            msg_encoding = (msg.encoding or "").lower()
            if msg_encoding in {"rgba8", "rgba16"}:
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
            elif msg_encoding in {"bgra8", "bgra16"}:
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            else:
                img = img[:, :, :3]

        # Normalize color ordering to the requested color_mode.
        if img.ndim == 3 and img.shape[2] == 3:
            msg_encoding = (msg.encoding or "").lower()
            if msg_encoding in {"rgb8", "rgb16", "rgba8", "rgba16"} and self.color_mode == ColorMode.BGR:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            elif msg_encoding in {"bgr8", "bgr16", "bgra8", "bgra16"} and self.color_mode == ColorMode.RGB:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        rot_flag = _CV2_ROTATION_TO_FLAG.get(self.rotation)
        if rot_flag is not None:
            img = cv2.rotate(img, rot_flag)

        if img.ndim == 2:
            img = img[:, :, np.newaxis]

        return img

    @check_if_not_connected
    def read(self) -> NDArray[np.uint8]:
        cls = type(self)
        entry = cls._subscriptions.get(self.topic)
        if entry is None:
            raise DeviceNotConnectedError(f"{self}: subscription dropped.")

        with entry.lock:
            msg = entry.latest_msg
            entry.last_consumed_time = entry.last_received_time

        if msg is None:
            raise DeviceNotConnectedError(f"{self}: no frame received yet.")

        return self._msg_to_ndarray(msg)

    @check_if_not_connected
    def async_read(self, timeout_ms: float = 200.0) -> NDArray[np.uint8]:
        """Return the most recent unconsumed frame.

        Blocks up to `timeout_ms` waiting for a fresh frame if the buffer
        currently holds one already consumed by a previous `async_read` call,
        or nothing at all. Raises `TimeoutError` on timeout.
        """
        cls = type(self)
        entry = cls._subscriptions.get(self.topic)
        if entry is None:
            raise DeviceNotConnectedError(f"{self}: subscription dropped.")

        deadline = time.perf_counter() + (timeout_ms / 1000.0)
        while True:
            with entry.lock:
                has_fresh = entry.latest_msg is not None and (
                    entry.last_received_time > entry.last_consumed_time
                )
                if has_fresh:
                    msg = entry.latest_msg
                    entry.last_consumed_time = entry.last_received_time
                    break

            if time.perf_counter() >= deadline:
                raise TimeoutError(
                    f"{self}: no new frame on '{self.topic}' within {timeout_ms:.0f}ms."
                )
            time.sleep(0.005)

        return self._msg_to_ndarray(msg)

    # -------------------------------------------------------------- teardown

    def _drop_subscription(self, final: bool) -> None:
        cls = type(self)
        entry = cls._subscriptions.pop(self.topic, None)
        if entry is not None and cls._rclpy_node is not None:
            try:
                cls._rclpy_node.destroy_subscription(entry.subscription)
            except Exception:  # nosec B110
                pass
        self._connected = False
        if final:
            cls._maybe_shutdown_rclpy()

    def disconnect(self) -> None:
        if not self._connected:
            return
        self._drop_subscription(final=True)
        logger.info("%s: disconnected.", self)
