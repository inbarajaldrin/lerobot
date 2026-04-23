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

from dataclasses import dataclass

from ..configs import CameraConfig, ColorMode, Cv2Rotation

__all__ = ["ROS2CameraConfig", "ColorMode", "Cv2Rotation"]


@CameraConfig.register_subclass("ros2")
@dataclass
class ROS2CameraConfig(CameraConfig):
    """Configuration for a camera exposed over a ROS 2 image topic.

    Any ROS 2 camera driver that publishes `sensor_msgs/Image` is compatible —
    on-host, over the network, or bridged from a simulator such as Gazebo via
    `ros_gz_bridge`. The subscriber runs in the background; `read()` returns
    the latest cached frame.

    Only `topic` is strictly required. `fps`/`width`/`height`/`encoding` are
    metadata hints used by downstream components (the publishing driver is
    the authority on actual frame rate and size — the first received frame
    updates `width` and `height` to the real values).

    Examples:
        Subscribe to an RGB camera stream:
        ```python
        ROS2CameraConfig(topic="/camera/color/image_raw", fps=30, width=640, height=480)
        ```

        Subscribe to a Gazebo sim camera bridged by `ros_gz_bridge`:
        ```python
        ROS2CameraConfig(topic="/wrist_camera", fps=30, width=1280, height=720, encoding="bgr8")
        ```

    Args:
        topic: ROS 2 image topic to subscribe to (required).
        encoding: Image encoding expected for `cv_bridge.imgmsg_to_cv2`.
            Default `"passthrough"` preserves the publisher's encoding.
        color_mode: Final color mode of frames returned by `read()`. If the
            underlying image is RGB and `color_mode=BGR`, channels are swapped.
        rotation: One of `Cv2Rotation.{NO_ROTATION, ROTATE_90, ROTATE_180, ROTATE_270}`.
        warmup_s: Seconds to wait for the first message when `connect(warmup=True)`.
        mock: Reserved for a future mock backend. Currently raises `NotImplementedError`.
    """

    topic: str = ""
    encoding: str = "passthrough"
    color_mode: ColorMode = ColorMode.RGB
    rotation: Cv2Rotation = Cv2Rotation.NO_ROTATION
    warmup_s: float = 5.0
    mock: bool = False

    def __post_init__(self) -> None:
        if not self.topic:
            raise ValueError("`topic` is required for ROS2CameraConfig.")

        self.color_mode = ColorMode(self.color_mode)
        self.rotation = Cv2Rotation(self.rotation)

        if self.warmup_s <= 0:
            raise ValueError(
                f"`warmup_s` must be positive, but {self.warmup_s} is provided."
            )
