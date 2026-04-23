# Testing Patterns

**Analysis Date:** 2026-04-23

## Test Framework

**Runner:**
- pytest (8.1.0+)
- Config: No `pytest.ini` found; all config in `pyproject.toml`
- Optional: pytest-cov (5.0.0+) for coverage reporting

**Assertion Library:**
- pytest standard assertions (`assert`, `pytest.raises()`)
- numpy assertions for numerical validation: `np.testing.assert_allclose()`, `np.allclose()`

**Run Commands:**
```bash
# Run all tests
pytest tests -v --cov=./lerobot --durations=0

# Run single test file
pytest tests/cameras/test_cameras.py -v

# Run specific test with parameters
pytest -sx 'tests/test_cameras.py::test_camera[opencv-False]'

# Run with minimal install (test extras only)
uv sync --extra "test"
uv run pytest tests -v --cov=./lerobot

# Run with all extras (full features)
uv sync --all-extras
uv run pytest tests -v --cov=./lerobot --durations=0

# Ignored warnings (pre-configured in CI)
pytest tests -v \
  -W ignore::DeprecationWarning:imageio_ffmpeg._utils:7 \
  -W ignore::UserWarning:torch.utils.data.dataloader:558 \
  -W ignore::UserWarning:gymnasium.utils.env_checker:247
```

## Test File Organization

**Location:**
- Co-located with code: Test files in `tests/` directory parallel to `lerobot/` structure
- Test fixtures in `tests/fixtures/` (dataset factories, hub mocks, etc.)
- Utilities in `tests/utils.py` (decorators, helpers, device detection)
- Mock implementations in `tests/cameras/mock_*.py` (mock_cv2, mock_pyrealsense2)

**Naming:**
- Test modules: `test_<feature>.py`
- Test functions: `test_<functionality>`
- Test classes: none observed (functional style preferred)

**Structure:**
```
tests/
├── conftest.py                 # Root fixtures, pytest plugins
├── utils.py                    # Test utilities, decorators
├── cameras/
│   ├── test_cameras.py         # Camera integration tests
│   ├── mock_cv2.py             # Mock OpenCV for testing
│   └── mock_pyrealsense2.py    # Mock Intel RealSense for testing
├── datasets/
│   ├── test_datasets.py
│   ├── test_utils.py
│   ├── test_visualize_dataset.py
│   └── test_*.py
├── fixtures/
│   ├── constants.py            # TEST_CAMERA_TYPES, DEFAULT_FPS, etc.
│   ├── dataset_factories.py    # Fixtures for creating test datasets
│   ├── files.py                # File/path fixtures
│   ├── hub.py                  # Hub integration fixtures
│   └── optimizers.py           # Optimizer fixtures
├── motors/
│   └── test_motors.py
├── robots/
├── policies/
├── examples/
└── configs/
```

## Test Structure

**Suite Organization:**

```python
# From tests/cameras/test_cameras.py

import pytest
from lerobot.common.robot_devices.utils import (
    RobotDeviceAlreadyConnectedError,
    RobotDeviceNotConnectedError,
)
from tests.utils import TEST_CAMERA_TYPES, make_camera, require_camera

# Constants for test thresholds
MAX_PIXEL_DIFFERENCE = 25

# Helper functions
def compute_max_pixel_difference(first_image, second_image):
    return np.abs(first_image.astype(float) - second_image.astype(float)).max()

# Parametrized test with decorators
@pytest.mark.parametrize("camera_type, mock", TEST_CAMERA_TYPES)
@require_camera
def test_camera(request, camera_type, mock):
    """Docstring describing test assumptions"""
    # Conditional skips for known issues
    if camera_type == "opencv" and not mock:
        pytest.skip("TODO(rcadene): fix test for opencv physical camera")
    
    # Test setup
    camera_kwargs = {"camera_type": camera_type, "mock": mock}
    
    # Test error conditions before connect
    with pytest.raises(RobotDeviceNotConnectedError):
        camera.read()
    
    # Test happy path
    camera = make_camera(**camera_kwargs)
    camera.connect()
    assert camera.is_connected
    
    # Test assertions with numpy
    color_image = camera.read()
    assert isinstance(color_image, np.ndarray)
    assert color_image.ndim == 3
    h, w, c = color_image.shape
    assert c == 3
    
    # Cleanup
    camera.disconnect()
    del camera
```

**Patterns:**

- **Setup:** Create fixture objects, verify preconditions
- **Parametrization:** `@pytest.mark.parametrize()` for multiple hardware types and mock/real variants
- **Conditional skips:** `pytest.skip()` for known issues or missing hardware
- **Cleanup:** explicit `disconnect()` calls or `del` object to trigger `__del__`
- **Error testing:** `pytest.raises(ExceptionType)` context manager
- **Assertions:** Standard `assert`, numpy comparisons with tolerances

## Mocking

**Framework:** unittest.mock + custom mock implementations

**Mock Implementations:**
- `tests/cameras/mock_cv2.py` - Mock OpenCV VideoCapture and frame generation
- `tests/cameras/mock_pyrealsense2.py` - Mock Intel RealSense context and devices
- Conditional loading: `if mock: import tests.cameras.mock_X as X else: import X`

**Patterns:**
```python
# From opencv.py find_cameras():
def _find_cameras(possible_camera_ids: list[int | str], raise_when_empty=False, mock=False):
    if mock:
        import tests.cameras.mock_cv2 as cv2  # Conditional import
    else:
        import cv2
    
    camera_ids = []
    for camera_idx in possible_camera_ids:
        camera = cv2.VideoCapture(camera_idx)
        is_open = camera.isOpened()
        camera.release()
        if is_open:
            camera_ids.append(camera_idx)
    
    return camera_ids

# From conftest.py fixtures:
def _check_component_availability(component_type, available_components, make_component):
    """Generic helper to check if a hardware component is available"""
    try:
        component = make_component(component_type)
        component.connect()
        del component
        return True
    except Exception as e:
        # Specific exception handling for diagnosis
        if isinstance(e, ModuleNotFoundError):
            print(f"\nInstall module '{e.name}'")
        elif isinstance(e, SerialException):
            print("\nNo physical device detected.")
        else:
            traceback.print_exc()
        return False
```

**What to Mock:**
- Hardware SDKs (cv2, pyrealsense2) - replaced with deterministic test doubles
- Device detection - mocked to always return test devices
- Frame capture - mocked to return stable test images (useful for regression testing)

**What NOT to Mock:**
- Core LeRobot APIs (`make_camera`, config dataclasses)
- Connection lifecycle (`connect()`, `disconnect()`)
- Frame processing logic (transformations, rotations)

## Fixtures and Factories

**Test Data:**

From `tests/fixtures/dataset_factories.py`:
```python
@pytest.fixture(scope="session")
def img_array_factory():
    """Factory for creating random image arrays"""
    def _create_img_array(height=100, width=100, channels=3, dtype=np.uint8) -> np.ndarray:
        if np.issubdtype(dtype, np.unsignedinteger):
            # Int array in [0, 255] range
            img_array = np.random.randint(0, 256, size=(height, width, channels), dtype=dtype)
        elif np.issubdtype(dtype, np.floating):
            # Float array in [0, 1] range
            img_array = np.random.rand(height, width, channels).astype(dtype)
        else:
            raise ValueError(dtype)
        return img_array
    
    return _create_img_array

# Usage in tests:
def test_image_processing(img_array_factory):
    img = img_array_factory(height=480, width=640, channels=3)
    assert img.shape == (480, 640, 3)
```

**Fixture Scope Hierarchy:**
- `scope="session"` - Image factories created once per test session
- `scope="function"` - Fixture recreated for each test (default)

**Device Configuration Constants:**

From `tests/fixtures/constants.py`:
```python
DEFAULT_FPS = 30
DUMMY_ROBOT_TYPE = "dummy_robot"
DUMMY_CAMERA_FEATURES = {"camera": (1, 3, 224, 224)}
DUMMY_VIDEO_INFO = {"fps": 30, "chunks": 1}
```

**Location:**
- `tests/fixtures/dataset_factories.py` - `img_tensor_factory`, `img_array_factory`, dataset builders
- `tests/fixtures/constants.py` - Configuration constants for test data
- `tests/conftest.py` - Pytest-level fixtures (hardware availability, input mocking)

## Coverage

**Requirements:** No hard target enforced in config, but CI runs with `--cov=./lerobot`

**View Coverage:**
```bash
# Generate coverage report
pytest tests -v --cov=./lerobot --cov-report=html

# View HTML report
open htmlcov/index.html
```

**Coverage excludes:**
- `tests/artifacts/**/*.safetensors` - Binary model files (configured in `pyproject.toml`)
- Test code itself (coverage tool default)

## Test Types

**Unit Tests:**
- Scope: Individual camera/motor/robot implementations
- Approach: Test with mocks (no hardware), validate configuration, frame processing
- Examples: `test_camera` parametrized with `mock=True` variants
- Assertions: Output shape/dtype, error conditions, state transitions

**Integration Tests:**
- Scope: Full camera connection cycle, multi-step operations
- Approach: Real hardware if available, skip if not (via `@require_camera` decorator)
- Examples: `test_camera` with `mock=False` variants tests real devices
- Assertions: Frame availability, performance (FPS), state consistency

**End-to-End Tests:**
- Scope: Full training/inference pipelines
- Approach: Run in CI via `make test-end-to-end`
- Coverage: Dataset loading, model training, evaluation
- Assertions: Output produced, no errors

**Hardware Tests (optional):**
- Conditional skip via decorators if hardware unavailable
- Decorators check environment variables: `LEROBOT_TEST_OPENCV_CAMERA_INDEX`, `LEROBOT_TEST_INTELREALSENSE_SERIAL_NUMBER`
- Graceful skip message: "A {camera_type} camera is not available."

## Common Patterns

**Async Testing:**
```python
# From test_cameras.py
camera = make_camera(**camera_kwargs)
camera.connect()

# Warm up first frames (can be black)
for _ in range(30):
    camera.read()

color_image = camera.read()
async_color_image = camera.async_read()

# Compare async vs sync with tolerance
error_msg = (
    "max_pixel_difference between read() and async_read()",
    compute_max_pixel_difference(color_image, async_color_image),
)
np.testing.assert_allclose(
    color_image, async_color_image, rtol=1e-5, atol=MAX_PIXEL_DIFFERENCE, err_msg=error_msg
)
```

**Error Testing:**
```python
# Test state machine violations
with pytest.raises(RobotDeviceNotConnectedError):
    camera.read()

with pytest.raises(RobotDeviceNotConnectedError):
    camera.async_read()

with pytest.raises(RobotDeviceNotConnectedError):
    camera.disconnect()

# Test double-connect prevention
camera = make_camera(**camera_kwargs)
camera.connect()
with pytest.raises(RobotDeviceAlreadyConnectedError):
    camera.connect()
```

**Device Parameterization:**
```python
# Test matrix: all camera types × (mock + real hardware)
@pytest.mark.parametrize("camera_type, mock", TEST_CAMERA_TYPES)
@require_camera
def test_camera(request, camera_type, mock):
    # TEST_CAMERA_TYPES auto-generated from available_cameras registry
    # Each test runs twice: once with mock=True, once with mock=False (if hardware available)
    pass
```

**Fixture Dependency Pattern:**
```python
# From conftest.py
@pytest.fixture
def is_camera_available(camera_type):
    return _check_component_availability(camera_type, available_cameras, make_camera)

# Used in tests via request fixture:
@require_camera
def test_camera(request, camera_type, mock):
    if not mock and not request.getfixturevalue("is_camera_available"):
        pytest.skip(f"A {camera_type} camera is not available.")
```

---

*Testing analysis: 2026-04-23*
