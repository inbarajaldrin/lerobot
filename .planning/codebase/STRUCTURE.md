# Codebase Structure

**Analysis Date:** 2026-04-23

## Directory Layout

```
lerobot/
├── lerobot/                      # Main package
│   ├── __init__.py               # Available robots, cameras, policies, datasets listing
│   ├── __version__.py            # Version info
│   ├── common/                   # Core implementations
│   │   ├── constants.py          # Global constants
│   │   ├── datasets/             # Dataset loading and management
│   │   │   ├── lerobot_dataset.py      # LeRobotDataset, LeRobotDatasetMetadata classes
│   │   │   ├── factory.py              # make_dataset() factory function
│   │   │   ├── image_writer.py         # AsyncImageWriter for concurrent I/O
│   │   │   ├── online_buffer.py        # OnlineBuffer for live frame queuing
│   │   │   ├── sampler.py              # EpisodeAwareSampler for batching
│   │   │   ├── transforms.py           # Data augmentation transforms
│   │   │   ├── utils.py                # Episode/frame/stats utilities
│   │   │   ├── video_utils.py          # Video codec and frame extraction
│   │   │   ├── compute_stats.py        # Statistics computation per episode
│   │   │   ├── v2/                     # v2.0 dataset format support
│   │   │   └── v21/                    # v2.1 dataset format support
│   │   ├── envs/                 # Gymnasium environment wrappers
│   │   │   ├── factory.py              # make_env() factory
│   │   │   ├── utils.py                # Env utilities
│   │   │   └── [env-specific dirs]
│   │   ├── optim/                # Optimization utilities
│   │   │   ├── factory.py              # Optimizer and scheduler instantiation
│   │   │   └── utils.py
│   │   ├── policies/             # Policy implementations
│   │   │   ├── pretrained.py           # PreTrainedPolicy base class
│   │   │   ├── factory.py              # make_policy() factory
│   │   │   ├── normalize.py            # Observation/action normalization
│   │   │   ├── utils.py                # Policy utilities
│   │   │   ├── act/                    # ACT policy (Action Chunking Transformer)
│   │   │   ├── diffusion/              # Diffusion policy
│   │   │   ├── tdmpc/                  # TDMPC policy
│   │   │   ├── vqbet/                  # VQBeT policy
│   │   │   ├── pi0/                    # π0 policy
│   │   │   └── pi0fast/                # π0 fast variant
│   │   ├── robot_devices/        # Hardware abstractions
│   │   │   ├── cameras/                # Camera implementations
│   │   │   │   ├── configs.py          # CameraConfig, OpenCVCameraConfig, IntelRealSenseCameraConfig, ROS2CameraConfig
│   │   │   │   ├── opencv.py           # OpenCVCamera (USB webcams)
│   │   │   │   ├── intelrealsense.py   # IntelRealSenseCamera (D405, D435, etc.)
│   │   │   │   ├── ros2.py             # ROS2Camera (ROS2 topic subscriber) — PR #866
│   │   │   │   └── utils.py            # Camera factory and protocol
│   │   │   ├── motors/                 # Motor bus implementations
│   │   │   │   ├── configs.py          # MotorsBusConfig, DynamixelMotorsBusConfig, FeetechMotorsBusConfig
│   │   │   │   ├── dynamixel.py        # Dynamixel motor bus interface
│   │   │   │   ├── feetech.py          # Feetech motor bus interface
│   │   │   │   └── utils.py            # Motor utilities
│   │   │   ├── robots/                 # Robot types
│   │   │   │   ├── configs.py          # RobotConfig, ManipulatorRobotConfig, specific robot configs
│   │   │   │   ├── manipulator.py      # Manipulator (arms + gripper) base
│   │   │   │   ├── mobile_manipulator.py # Mobile manipulator (base + arms)
│   │   │   │   ├── stretch.py          # Stretch robot
│   │   │   │   ├── utils.py            # Robot factory and helpers
│   │   │   │   ├── lekiwi_remote.py    # LeKiwi remote control
│   │   │   │   ├── dynamixel_calibration.py  # Calibration for Dynamixel
│   │   │   │   └── feetech_calibration.py    # Calibration for Feetech
│   │   │   ├── control_configs.py      # Control modes (teleoperate, record, replay, calibrate)
│   │   │   ├── control_utils.py        # Control loop utilities
│   │   │   └── utils.py                # Common device exceptions and helpers
│   │   └── utils/                # Shared utilities
│   │       ├── utils.py               # General utilities
│   │       ├── logging_utils.py       # Logging and metrics
│   │       ├── random_utils.py        # RNG seeding
│   │       ├── train_utils.py         # Training checkpoint management
│   │       ├── wandb_utils.py         # Weights & Biases integration
│   │       ├── io_utils.py            # File I/O
│   │       ├── hub.py                 # HuggingFace Hub mixin
│   │       └── [other utilities]
│   ├── configs/                  # Configuration system (draccus-based)
│   │   ├── parser.py             # CLI argument parser
│   │   ├── types.py              # Config base types
│   │   ├── default.py            # Default configurations
│   │   ├── train.py              # TrainPipelineConfig
│   │   ├── eval.py               # EvalPipelineConfig
│   │   └── policies.py           # PreTrainedConfig (base for policy configs)
│   ├── scripts/                  # CLI entry points
│   │   ├── control_robot.py      # Robot teleoperation, recording, replay, calibration
│   │   ├── control_sim_robot.py  # Sim-based data collection (currently NotImplementedError)
│   │   ├── train.py              # Train policy on dataset
│   │   ├── eval.py               # Evaluate policy on environment
│   │   ├── configure_motor.py    # Motor configuration utility
│   │   ├── find_motors_bus_port.py  # Find motor bus ports
│   │   ├── visualize_dataset.py  # Visualize frames and episodes
│   │   ├── visualize_dataset_html.py # HTML-based visualization
│   │   ├── visualize_image_transforms.py # Test data augmentation
│   │   ├── push_pretrained.py    # Push trained model to Hub
│   │   └── display_sys_info.py   # System information
│   └── templates/                # HTML/Jinja2 templates
│       ├── visualize_dataset_template.html
│       └── visualize_dataset_homepage.html
├── tests/                        # Test suite
│   ├── conftest.py               # Pytest configuration and fixtures
│   ├── cameras/                  # Camera tests
│   │   ├── mock_cv2.py           # Mock OpenCV for testing
│   │   └── [camera-specific tests]
│   ├── datasets/                 # Dataset tests
│   ├── motors/                   # Motor tests
│   ├── robots/                   # Robot tests
│   ├── policies/                 # Policy tests
│   ├── envs/                     # Environment tests
│   ├── optim/                    # Optimizer tests
│   ├── configs/                  # Config tests
│   ├── fixtures/                 # Test data and fixtures
│   ├── artifacts/                # Pre-built test artifacts
│   ├── utils/                    # Utility tests
│   ├── examples/                 # Example usage tests
│   ├── test_available.py         # Test available items inventory
│   └── utils.py                  # Test helper functions
├── examples/                     # Example notebooks and scripts
├── docker/                       # Dockerfile configurations
├── benchmarks/                   # Performance benchmarks
├── docs/                         # Documentation
└── README.md, pyproject.toml, etc. # Root project files
```

## Directory Purposes

**lerobot/common/datasets/:**
- Purpose: Load, save, and manage episode-based frame collections
- Contains: Dataset classes, episode I/O, statistics, version management
- Key files:
  - `lerobot_dataset.py`: Main `LeRobotDataset` class for accessing frames and metadata
  - `lerobot_dataset.py`: `LeRobotDatasetMetadata` for Hub integration
  - `factory.py`: `make_dataset()` instantiates from repo_id or path
  - `online_buffer.py`: `OnlineBuffer` queues frames during live recording

**lerobot/common/policies/:**
- Purpose: Define learnable policy models and their training/inference logic
- Contains: Policy base class, implementations (ACT, Diffusion, TDMPC, VQBeT), normalization
- Key files:
  - `pretrained.py`: `PreTrainedPolicy` base class with Hub I/O
  - `factory.py`: `make_policy()` from config
  - `normalize.py`: Observation/action standardization

**lerobot/common/robot_devices/:**
- Purpose: Abstract hardware (robots, cameras, motors) into reusable interfaces
- Contains: Pluggable implementations for different robot types and sensor types
- Key files:
  - `cameras/configs.py`: `CameraConfig` registry with subclasses for OpenCV, RealSense, ROS2
  - `cameras/ros2.py`: `ROS2Camera` class implementing ROS2 topic subscription (PR #866 addition)
  - `cameras/utils.py`: `Camera` protocol and factory
  - `robots/configs.py`: `RobotConfig` registry with Aloha, Koch, etc. defaults
  - `motors/configs.py`: `MotorsBusConfig` for Dynamixel/Feetech buses

**lerobot/common/robot_devices/cameras/:
- Purpose: Sensor abstraction for image capture
- File organization:
  - `configs.py`: Configuration classes (one per camera type)
  - `<name>.py`: Implementation class (paired with config)
  - Naming: `OpenCVCamera` ↔ `OpenCVCameraConfig`, `ROS2Camera` ↔ `ROS2CameraConfig`
- ROS2 Integration (PR #866):
  - `ROS2CameraConfig` (lines 117-231): Configures ROS2 topic, encoding, dimensions, rotation
  - `ROS2Camera` (lines 86-277): Manages rclpy node lifecycle, subscribes to ImageMsg topic, converts via cv_bridge
  - Thread-safe: Spinner thread processes messages, main thread reads latest frame

**lerobot/configs/:**
- Purpose: Typed configuration system for all subsystems
- Contains: Dataclasses with validation, serialization to/from YAML/JSON
- Key files:
  - `types.py`: Base config types
  - `parser.py`: Hydra CLI parser
  - `train.py`: `TrainPipelineConfig` aggregates dataset, policy, optimizer, scheduler configs
  - `eval.py`: `EvalPipelineConfig` for evaluation

**tests/:**
- Purpose: Pytest test suite covering all modules
- Organization: Mirrors `lerobot/common/` structure
- Key files:
  - `conftest.py`: Pytest fixtures (e.g., temporary directories, mock configs)
  - `fixtures/`: Pre-built test data (configs, small datasets)
  - `artifacts/`: Binary test data (pretrained models, videos)

## Key File Locations

**Entry Points:**
- `lerobot/scripts/control_robot.py`: Robot teleoperation, recording, replay
- `lerobot/scripts/train.py`: Policy training pipeline
- `lerobot/scripts/eval.py`: Policy evaluation pipeline
- `lerobot/scripts/control_sim_robot.py`: Simulation-based recording (NotImplementedError)

**Configuration:**
- `lerobot/configs/train.py`: `TrainPipelineConfig` for training CLI
- `lerobot/configs/eval.py`: `EvalPipelineConfig` for evaluation CLI
- `lerobot/configs/policies.py`: `PreTrainedConfig` base for all policy configs

**Core Logic:**
- `lerobot/common/datasets/lerobot_dataset.py`: `LeRobotDataset` and `LeRobotDatasetMetadata`
- `lerobot/common/policies/pretrained.py`: `PreTrainedPolicy` base class
- `lerobot/common/robot_devices/robots/utils.py`: `make_robot()` factory
- `lerobot/common/robot_devices/cameras/utils.py`: `make_cameras_from_configs()` factory

**Testing:**
- `tests/conftest.py`: Pytest configuration
- `tests/utils.py`: Common test helpers
- `tests/fixtures/`: Test data
- `tests/test_available.py`: Inventory validation

## Naming Conventions

**Files:**
- `*_config*.py` or `configs.py`: Dataclass configurations with registry
- `*_utils.py`: Utility functions and helpers
- `*_factory.py` or `factory.py`: Factory functions (`make_*()`)
- Implementation classes paired with config classes: `OpenCVCamera` with `OpenCVCameraConfig`

**Directories:**
- Plural for collections: `datasets/`, `policies/`, `cameras/`, `motors/`, `robots/`, `envs/`, `utils/`
- Singular for specific implementations: `opencv.py`, `dynamixel.py`, `stretch.py`

**Classes:**
- Config classes: `<Name>Config` (e.g., `OpenCVCameraConfig`, `ManipulatorRobotConfig`)
- Implementation classes: `<Name>` (e.g., `OpenCVCamera`, `Manipulator`)
- Base classes: `<Name>` with `abc.ABC` and `draccus.ChoiceRegistry` (e.g., `CameraConfig`, `RobotConfig`)

**Functions:**
- Factories: `make_<resource>()` (e.g., `make_policy()`, `make_robot()`, `make_dataset()`)
- Utilities: `<verb>_<noun>()` (e.g., `save_image()`, `load_episodes()`)

## Where to Add New Code

**New Camera Type (e.g., hypothetical DepthCameraThermalCamera):**
1. Create config subclass in `lerobot/common/robot_devices/cameras/configs.py`:
   ```python
   @CameraConfig.register_subclass("thermal")
   @dataclass
   class ThermalCameraConfig(CameraConfig):
       port: str
       ...
   ```
2. Create implementation in `lerobot/common/robot_devices/cameras/thermal.py`:
   ```python
   class ThermalCamera:
       def connect(self): ...
       def read(self) -> np.ndarray: ...
       def async_read(self) -> np.ndarray: ...
       def disconnect(self): ...
   ```
3. Register in factory: `lerobot/common/robot_devices/cameras/utils.py` line 47-50 add elif branch
4. Add to `lerobot/__init__.py` line 189: `"thermal"` in `available_cameras`

**New Robot Type (e.g., quadruped with cameras):**
1. Create config in `lerobot/common/robot_devices/robots/configs.py`:
   ```python
   @RobotConfig.register_subclass("quadruped")
   @dataclass
   class QuadrupedRobotConfig(RobotConfig):
       leader_arms: dict[str, MotorsBusConfig] = ...
       cameras: dict[str, CameraConfig] = ...
   ```
2. Create implementation in `lerobot/common/robot_devices/robots/quadruped.py` inheriting from `Manipulator` or `MobileManipulator`
3. Add factory entry in `lerobot/common/robot_devices/robots/utils.py`
4. Add to `lerobot/__init__.py` line 179: `"quadruped"` in `available_robots`

**New Policy Type (e.g., transformer-based policy):**
1. Create config in `lerobot/common/policies/` (e.g., `transformer_config.py`)
2. Create implementation in `lerobot/common/policies/transformer/` with model class inheriting `PreTrainedPolicy`
3. Register factory in `lerobot/common/policies/factory.py`
4. Add to `lerobot/__init__.py` line 171: `"transformer"` in `available_policies`
5. Create tests in `tests/policies/test_transformer.py`

**New CLI Script (e.g., data analysis):**
1. Create `lerobot/scripts/analyze_dataset.py`
2. Define config dataclass (inherit from base configs)
3. Use Hydra/draccus parser via `lerobot/configs/parser.py`
4. Entry point: CLI invocation by users

**New Environment (e.g., robot arm in physics sim):**
1. Create `lerobot/common/envs/custom_sim_env.py` wrapping Gymnasium
2. Register in `lerobot/common/envs/factory.py`
3. Add to `available_tasks_per_env` in `lerobot/__init__.py`

**Tests for New Code:**
- Unit tests: Mirror the module location under `tests/`
  - Camera test: `tests/cameras/test_thermal.py`
  - Robot test: `tests/robots/test_quadruped.py`
  - Policy test: `tests/policies/test_transformer.py`
- Use fixtures from `tests/conftest.py` for configs, mocks for hardware
- See `tests/utils.py` for common helpers

## Special Directories

**lerobot/.cache/:**
- Purpose: Cache for downloaded models and datasets
- Generated: Yes (created by HuggingFace Hub API)
- Committed: No (in `.gitignore`)

**lerobot/outputs/:**
- Purpose: Training checkpoints, logs, evaluation results
- Generated: Yes (created by `train.py`, `eval.py`)
- Committed: No (in `.gitignore`)

**tests/fixtures/:**
- Purpose: Pre-built test data (small configs, dataset fixtures)
- Generated: No (committed)
- Committed: Yes

**tests/artifacts/:**
- Purpose: Binary test data (pre-trained models, reference videos)
- Generated: No (committed)
- Committed: Yes

---

*Structure analysis: 2026-04-23*
