# Coding Conventions

**Analysis Date:** 2026-04-23

## Naming Patterns

**Files:**
- Lowercase with underscores (snake_case): `opencv.py`, `intelrealsense.py`, `ros2.py`
- Config files end with `_config.py`: `configs.py` for config dataclasses
- Test files follow `test_<module>.py` pattern: `test_cameras.py`, `test_datasets.py`
- Private/internal modules prefixed with underscore: `_find_cameras()`, `_check_component_availability()`

**Functions:**
- snake_case: `find_cameras()`, `save_images_from_cameras()`, `async_read()`, `busy_wait()`
- Return type annotations standard: `-> list[dict]`, `-> np.ndarray`, `-> str`
- Private/internal functions prefixed with underscore

**Variables:**
- snake_case: `camera_index`, `serial_number`, `color_mode`, `is_connected`
- Constants UPPERCASE: `MAX_OPENCV_INDEX = 60`, `SERIAL_NUMBER_INDEX = 1`
- Booleans use clear names: `mock`, `is_connected`, `raise_when_empty`

**Types:**
- Configuration dataclasses end in `Config`: `CameraConfig`, `OpenCVCameraConfig`, `IntelRealSenseCameraConfig`, `ROS2CameraConfig`
- Implementation classes match config without suffix: `OpenCVCamera`, `IntelRealSenseCamera`, `ROS2Camera`
- Abstract base uses `abc.ABC` with `@abc.abstractmethod` decorator
- Device classes inherit from abstract config base via `draccus.ChoiceRegistry`

## Code Style

**Formatting:**
- Tool: ruff (format + lint)
- Line length: 110 characters (configured in `pyproject.toml`)
- Target version: Python 3.10+
- Format applied via pre-commit hook on every commit

**Linting:**
- Tool: ruff
- Selected rules: `E4`, `E7`, `E9`, `F`, `I`, `N`, `B`, `C4`, `SIM` (style, imports, naming, bugbear, comprehensions, simplifications)
- Pre-commit hook: `ruff check --fix` (auto-fixes many issues)
- Format check: `ruff format --diff` (validates formatting without modifying)

**Pre-commit hooks applied:**
- Code style: ruff check, ruff format
- General: trailing whitespace, YAML/TOML validation, merge conflict detection
- Security: gitleaks (detect secrets), bandit (security issues), zizmor (GitHub Actions)
- Typo checking: typos crate-ci (custom word list in `pyproject.toml`)

## Import Organization

**Order:**
1. Standard library (`os`, `time`, `threading`, `pathlib`)
2. Third-party packages (`numpy`, `PIL`, `torch`, `rclpy`, `draccus`)
3. Local imports (relative or absolute from `lerobot.*`)
4. Conditional/conditional imports within functions (for mock/optional deps)

**Path Aliases:**
- Absolute imports preferred: `from lerobot.common.robot_devices.cameras.configs import ...`
- No short aliases in codebase, full paths maintained for clarity
- Mock imports handled conditionally: `import tests.cameras.mock_cv2 as cv2` when `mock=True`

**Example from `intelrealsense.py`:**
```python
import logging
import traceback
from pathlib import Path
from threading import Thread

import numpy as np
from PIL import Image

from lerobot.common.robot_devices.cameras.configs import IntelRealSenseCameraConfig
from lerobot.common.robot_devices.utils import (
    RobotDeviceAlreadyConnectedError,
    RobotDeviceNotConnectedError,
    busy_wait,
)
from lerobot.common.utils.utils import capture_timestamp_utc
```

## Error Handling

**Custom Exceptions:**
- Defined in `lerobot/common/robot_devices/utils.py`
- `RobotDeviceNotConnectedError` - raised when operation attempted before `connect()`
- `RobotDeviceAlreadyConnectedError` - raised when `connect()` called twice
- Both include default messages but accept custom messages in `__init__`

**Patterns:**
- Connection state checked before operations: `if not robot_device.is_connected`
- Exceptions raised with meaningful context: e.g., "This robot device is not connected. Try calling `robot_device.connect()` first."
- Error wrapping in decorators: `@safe_disconnect` decorator catches exceptions and disconnects robot before re-raising
- Hardware availability checks wrapped: `try/except` with traceback for debugging, `SerialException` for port issues, `ModuleNotFoundError` for missing SDK

**Example from `conftest.py`:**
```python
def _check_component_availability(component_type, available_components, make_component):
    """Generic helper to check if a hardware component is available"""
    try:
        component = make_component(component_type)
        component.connect()
        del component
        return True
    except Exception as e:
        print(f"\nA {component_type} is not available.")
        if isinstance(e, ModuleNotFoundError):
            print(f"\nInstall module '{e.name}'")
        elif isinstance(e, SerialException):
            print("\nNo physical device detected.")
        else:
            traceback.print_exc()
        return False
```

## Logging

**Framework:** `logging` standard library

**Patterns:**
- Module-level imports: `import logging`
- Module-level logger setup: `logger = logging.getLogger(__name__)` (not used everywhere, but pattern exists)
- Direct `logging.info()`, `logging.warning()`, `logging.error()` calls throughout codebase
- Print statements used for CLI output and progress: `print(f"Frame: {frame_index:04d}\tLatency (ms): {(time.perf_counter() - now) * 1000:.2f}")`

**Levels used:**
- `logging.info()` - connection status, camera found messages
- `logging.warning()` - fallback device selection, missing accelerators
- `logging.error()` - operation failures (e.g., image save failures)

**Example from `intelrealsense.py`:**
```python
logging.info(f"Saved image: {path}")
logging.error(f"Failed to save image for camera {serial_number} frame {frame_index}: {e}")
```

## Comments

**When to Comment:**
- Complex algorithms or non-obvious logic: seen in camera frame processing
- TODO markers for known limitations: `# TODO(rcadene): fix test for opencv physical camera`
- Configuration notes: docstrings for config dataclasses with examples
- Platform-specific workarounds: comments explaining macOS vs Linux differences

**DocStrings/Type Hints:**
- Class docstrings extensive for public APIs: `ROS2Camera` has full docstring with examples
- Function docstrings sparse - mostly in configuration classes
- Type hints on function signatures mandatory: `def find_cameras(...) -> list[dict]:`
- Type unions use pipe syntax: `int | None`, `str | None` (Python 3.10+)

**Example from `ros2.py`:**
```python
class ROS2Camera:
    """
    The ROS2Camera class records images from cameras via ROS 2.

    This class requires a ROS 2 camera driver to be running and publishing images on a specified topic.
    It's compatible with any camera that has a ROS 2 driver, whether running on the same host or another host on the network.

    To discover available camera topics:
    ```bash
    ros2 topic list
    ```
    """
```

## Function Design

**Size:** 
- Average 20-50 lines for device management functions
- Longer (~100+ lines) for save/record loops with threaded operations
- Complex init logic in `__init__` and `connect()` methods

**Parameters:** 
- Explicit keyword arguments preferred
- Optional parameters use `None` as default: `fps: int | None = None`
- Mock parameter as boolean flag: `mock: bool = False`
- Collections as typed parameters: `serial_numbers: list[int] | None = None`

**Return Values:** 
- Explicit return types always annotated
- Functions return data structures when multiple values needed: lists of dicts for camera discovery
- Methods return `self` for chaining (not used), `None` for side-effects (connect, disconnect)

## Module Design

**Exports:**
- Camera implementations: Each camera type (OpenCV, IntelRealSense, ROS2) has dedicated module
- Config classes exported from `configs.py`
- Utility functions (`find_cameras`, `save_images_from_cameras`) in same module as implementation
- Abstract base `Camera` class in `utils.py`

**Barrel Files:**
- Registry pattern used: `CameraConfig.register_subclass("opencv")` decorator registers implementations
- Config base class `CameraConfig` extends `draccus.ChoiceRegistry` for automatic factory registration
- Available cameras auto-discovered from registered subclasses

**Camera Extension Pattern (adding new camera type):**

1. **Add config in `lerobot/common/robot_devices/cameras/configs.py`:**
```python
@CameraConfig.register_subclass("camera_type_name")
@dataclass
class NewCameraConfig(CameraConfig):
    """Docstring with examples"""
    required_param: str
    optional_param: int | None = None
    
    def __post_init__(self):
        self.channels = 3  # or 1 for depth
```

2. **Implement camera in new file `lerobot/common/robot_devices/cameras/new_type.py`:**
```python
class NewTypeCamera:
    def __init__(self, config: NewCameraConfig):
        self.config = config
        self.is_connected = False
    
    def connect(self):
        # Validate config, initialize hardware
        self.is_connected = True
    
    def read(self) -> np.ndarray:
        # Return single frame as (H, W, C) array
    
    def async_read(self) -> np.ndarray:
        # Return latest frame from background thread
    
    def disconnect(self):
        self.is_connected = False
        # Cleanup hardware
```

3. **Add factory support in `lerobot/common/robot_devices/cameras/utils.py`:**
```python
# Register the camera in make_camera factory function
if camera_type == "new_type_name":
    from lerobot.common.robot_devices.cameras.new_type import NewTypeCamera
    return NewTypeCamera(config)
```

---

*Convention analysis: 2026-04-23*
