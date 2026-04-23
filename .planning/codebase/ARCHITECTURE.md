# Architecture

**Analysis Date:** 2026-04-23

## Pattern Overview

**Overall:** Device/Policy/Dataset Separation with Registry-Based Configuration

LeRobot follows a clean three-tier architecture separating concerns:
- **Devices**: Robots, cameras, motors (hardware abstractions)
- **Policies**: Learnable models (ACT, Diffusion, TDMPC, VQBeT)
- **Datasets**: Frame collection, storage, and retrieval for training/evaluation

**Key Characteristics:**
- Registry-based configuration using `draccus.ChoiceRegistry` for pluggable hardware and policies
- Dataclass-driven configuration (typed, validated, serializable)
- Camera abstraction allows ROS2, OpenCV, Intel RealSense, and custom implementations
- Dataset versioning (v2.1 codebase) with HuggingFace Hub integration
- Modular factory pattern for constructing robots, cameras, policies, and datasets

## Layers

**Scripts (CLI Entry Points):**
- Purpose: User-facing command-line interfaces for data collection, training, evaluation, and robot control
- Location: `lerobot/scripts/`
- Contains: `control_robot.py`, `train.py`, `eval.py`, `control_sim_robot.py`, calibration/visualization utilities
- Depends on: Common layer (datasets, policies, robots, environments)
- Used by: End users running data collection and training workflows

**Configs (Type System):**
- Purpose: Defines all configuration types with validation and serialization
- Location: `lerobot/configs/`
- Contains: `types.py`, `default.py`, `parser.py`, `train.py`, `eval.py`, `policies.py`
- Depends on: `draccus` library for registry pattern
- Used by: Scripts and common modules for configuration instantiation

**Common Layer (Core Implementations):**
- Purpose: Implements robot devices, policies, datasets, and environments
- Location: `lerobot/common/`
- Contains: `robot_devices/`, `policies/`, `datasets/`, `envs/`, `optim/`, `utils/`
- Depends on: Configs, third-party libraries (torch, HF Hub, rclpy for ROS2)
- Used by: Scripts and other common modules

**Robot Devices Sublayer:**
- Location: `lerobot/common/robot_devices/`
- Contains:
  - `robots/`: Robot implementations (Manipulator, MobileManipulator, Stretch) with configs
  - `cameras/`: Camera implementations (OpenCV, IntelRealSense, ROS2) with configs
  - `motors/`: Motor bus implementations (Dynamixel, Feetech) with configs
  - `control_configs.py`: Control mode configurations (teleoperate, record, replay, calibrate)
  - `control_utils.py`: Utilities for control loop management
- Pattern: Each hardware type has a `Config` dataclass + implementation class

**Policies Sublayer:**
- Location: `lerobot/common/policies/`
- Contains:
  - `pretrained.py`: `PreTrainedPolicy` base class with Hub loading/saving
  - `factory.py`: Policy instantiation from configs
  - `normalize.py`: Observation/action normalization
  - Per-policy dirs: `act/`, `diffusion/`, `tdmpc/`, `vqbet/`, `pi0/`, `pi0fast/`
- Pattern: Each policy defines `Config` class and `Policy` class (subclass of `PreTrainedPolicy`)

**Datasets Sublayer:**
- Location: `lerobot/common/datasets/`
- Contains:
  - `lerobot_dataset.py`: `LeRobotDataset` and `LeRobotDatasetMetadata` core classes
  - `factory.py`: Dataset instantiation
  - `image_writer.py`: Async image I/O
  - `utils.py`: Episode/frame/stats management
  - `transforms.py`: Data augmentation
  - `sampler.py`: Episode-aware sampling
  - `v2/`, `v21/`: Version-specific implementations
- Pattern: Datasets integrate local storage + HuggingFace Hub with episode-chunk organization

**Environments Sublayer:**
- Location: `lerobot/common/envs/`
- Contains: Gymnasium-based environment wrappers for Aloha, PushT, XArm with observation/action spaces
- Used by: Evaluation and sim-based training

## Data Flow

**Data Collection Pipeline (control_robot.py):**

1. **Initialization**: `make_robot()` constructs robot from config → connects cameras + motors
2. **Camera Read**: Robot.get_observation() reads all cameras (calls `camera.read()`)
3. **Frame Capture**: Image stored via `dataset.add_frame(observations)` → queued in `OnlineBuffer`
4. **Episode Save**: On episode completion, `dataset.write_episode()` → writes parquet + images
5. **Hub Push**: `dataset.push_to_hub()` uploads to HuggingFace Hub (if enabled)

**Flow**: `camera.read()` → `robot.get_observation()` → `dataset.add_frame()` → `OnlineBuffer.queue` → `write_episode()` → `.parquet` + `.png` files → HF Hub

**Training Pipeline (train.py):**

1. **Dataset Load**: `LeRobotDataset(repo_id)` downloads metadata from Hub, caches locally
2. **Dataloader**: `dataset.__getitem__(index)` returns frame window (past/current/future observations + actions)
3. **Policy Forward**: `policy.forward(batch)` computes loss + outputs
4. **Backward Pass**: Loss backpropagation with gradient clipping
5. **Checkpoint Save**: `policy._save_pretrained(dir/)` saves config + safetensor weights

**Flow**: HF Hub metadata → `LeRobotDatasetMetadata` → episode parquets + images → dataloader → batches → policy training loop → checkpoints

**Evaluation Pipeline (eval.py):**

1. **Policy Load**: `PreTrainedPolicy.from_pretrained(path)` loads config + safetensors
2. **Env Create**: `make_env(env_type)` instantiates Gymnasium env
3. **Rollout**: Policy feeds observations to env, env executes actions in sim
4. **Metrics**: Success rate, cumulative reward computed across episodes
5. **Video Render**: Optional trajectory visualization saved

**Flow**: Policy checkpoint → loaded policy → environment rollout → metrics/video output

**State Management:**

- **Robot State**: Stored in `robot.leader_arms`, `robot.follower_arms`, `robot.cameras` (dicts by name)
- **Dataset State**: Metadata (episodes, tasks, stats) in `LeRobotDatasetMetadata`, frames in `OnlineBuffer`
- **Policy State**: Model weights in `PreTrainedPolicy.state_dict()`, config in `PreTrainedConfig`
- **Observation/Action Spaces**: Defined in robot configs, normalized via `Normalize` policy wrapper

## Key Abstractions

**CameraConfig Registry:**
- Purpose: Define camera hardware and parameters
- Examples: `OpenCVCameraConfig`, `IntelRealSenseCameraConfig`, `ROS2CameraConfig`
- Pattern: Subclass `CameraConfig` with `@CameraConfig.register_subclass("type")` decorator
- PR #866 Addition: `ROS2CameraConfig` at `lerobot/common/robot_devices/cameras/configs.py` lines 117-231
  - Supports ROS2 topic subscription for any camera driver
  - Includes encoding, fps, width, height, rotation, channels configuration
  - `ROS2Camera` class at `lerobot/common/robot_devices/cameras/ros2.py` manages subscription lifecycle

**RobotConfig Registry:**
- Purpose: Define robot architecture (arms, cameras, motors)
- Examples: `AlohaRobotConfig`, `ManipulatorRobotConfig`, `MobileManipulatorRobotConfig`
- Pattern: Subclass `RobotConfig` with arms/cameras/motors dicts
- Instance: `AlohaRobotConfig` at `lerobot/common/robot_devices/robots/configs.py` lines 84-250+

**MotorsBusConfig Registry:**
- Purpose: Define motor bus hardware
- Examples: `DynamixelMotorsBusConfig`, `FeetechMotorsBusConfig`
- Pattern: Subclass `MotorsBusConfig` with port + motors dict
- Instance: Lines 28-42 in `configs.py`

**PreTrainedPolicy:**
- Purpose: Base class for all learnable policies
- Location: `lerobot/common/policies/pretrained.py`
- Methods: `from_pretrained()`, `_save_pretrained()`, `forward(batch)` (abstract)
- Subclasses: `ACTPolicy`, `DiffusionPolicy`, `TDMPCPolicy`, `VQBeTPolicy`

**LeRobotDataset:**
- Purpose: Unified interface for episode-based frame data
- Location: `lerobot/common/datasets/lerobot_dataset.py`
- Key Methods: `__getitem__(index)` returns frame window dict, `add_frame()` queues observation
- Metadata: `LeRobotDatasetMetadata` loads from Hub, manages episodes/stats/tasks

**Camera Protocol:**
- Purpose: Defines camera interface
- Location: `lerobot/common/robot_devices/cameras/utils.py`
- Methods: `connect()`, `read()`, `async_read()`, `disconnect()`
- Factory: `make_cameras_from_configs()` instantiates camera instances from config dict

## Entry Points

**control_robot.py:**
- Location: `lerobot/scripts/control_robot.py`
- Triggers: User CLI `python lerobot/scripts/control_robot.py --robot.type=aloha --control.type=teleoperate`
- Responsibilities:
  - Parse arguments (robot config, control mode, FPS, episode count)
  - Instantiate robot via `make_robot(config)`
  - Connect cameras/motors
  - Control loop: read observations → predict actions (via policy or teleop) → execute → log
  - Record frames to `LeRobotDataset`
  - Push dataset to Hub if enabled

**train.py:**
- Location: `lerobot/scripts/train.py`
- Triggers: User CLI `python lerobot/scripts/train.py --dataset.repo_id=lerobot/aloha_sim_transfer_cube_human --policy.type=act`
- Responsibilities:
  - Load dataset from Hub or cache
  - Create policy from config
  - Setup optimizer + scheduler
  - Training loop: sample batches → forward pass → backward pass → checkpoint
  - Log metrics to WandB
  - Save best checkpoint

**eval.py:**
- Location: `lerobot/scripts/eval.py`
- Triggers: User CLI `python lerobot/scripts/eval.py --policy.path=outputs/train/act_aloha/checkpoints/080000/pretrained_model --env.type=aloha`
- Responsibilities:
  - Load policy from pretrained path
  - Create vectorized environments (batch of parallel envs)
  - Run rollout(): policy inference → action execution → metric collection
  - Save video trajectory if enabled
  - Print success rate, cumulative reward

**control_sim_robot.py:**
- Location: `lerobot/scripts/control_sim_robot.py`
- Status: Marked `NotImplementedError` (deactivated)
- Purpose: Sim-based data collection using Gymnasium envs

## Error Handling

**Strategy:** Validation-first at config instantiation, exception propagation at runtime

**Patterns:**

- **Config Validation**: `__post_init__` methods in dataclasses validate before object creation
  - Example: `ROS2CameraConfig.__post_init__` validates rotation ∈ [-90, None, 90, 180]
  - Example: `ManipulatorRobotConfig.__post_init__` validates max_relative_target dimensions

- **Connection Errors**: Custom exception `RobotDeviceAlreadyConnectedError` when reconnecting
  - Location: `lerobot/common/robot_devices/utils.py`
  - Example: `ROS2Camera.connect()` raises if already connected

- **Missing Camera Data**: Block-wait with timeout for first message
  - Location: `ROS2Camera.connect()` lines 202-204 spins until `has_message` is True

- **Dataset Version Compatibility**: Check codebase version matches dataset version
  - Location: `LeRobotDatasetMetadata.load_metadata()` calls `check_version_compatibility()`
  - Backward compatibility support for v2.0 → v2.1 migrations

- **Policy Loading**: Handle missing pretrained weights or config
  - `PreTrainedPolicy.from_pretrained()` downloads from Hub or uses local path
  - Fallback to default config if config.json missing

## Cross-Cutting Concerns

**Logging:** 
- Framework: Python `logging` module + `wandb` (weights & biases) for training metrics
- Implementation: `init_logging()` sets up file + console handlers
- Policy training logs loss, accuracy, gradients to WandB dashboard

**Validation:** 
- Config dataclasses with `__post_init__` checks
- Robot/camera/motor instantiation validates hardware compatibility
- Dataset version checks on load

**Authentication:** 
- HuggingFace Hub: Automatic via `huggingface-hub` library (reads `~/.cache/huggingface/token` or `HF_TOKEN` env var)
- No explicit auth code; library handles transparently

**Synchronization:** 
- Robot control loop uses busy-wait with FPS capping via `busy_wait(start_time, target_dt)`
- ROS2Camera uses threading: spinner thread processes subscriptions, main thread reads latest message
- Dataset I/O: Async image writing via `AsyncImageWriter` (ThreadPoolExecutor)

**Normalization:** 
- Observation/action normalization via `Normalize` policy wrapper (stats from dataset metadata)
- Location: `lerobot/common/policies/normalize.py`
- Applied per-key in observation/action dicts

---

*Architecture analysis: 2026-04-23*
