# Technology Stack

**Analysis Date:** 2026-04-23

## Languages

**Primary:**
- Python 3.10+ - All implementation code, policies, datasets, robot device drivers

## Runtime

**Environment:**
- CPython 3.10 or later (requires-python >= 3.10)

**Package Manager:**
- pip / poetry - Specified in `pyproject.toml`
- Lockfile: No lock file present (poetry configured but not enforced)

## Frameworks

**Core ML/Robotics:**
- PyTorch 2.2.1 to <2.7 - Neural network training and inference
- torchvision >=0.21.0 - Computer vision utilities (image transforms, video I/O)
- diffusers >=0.27.2 - Diffusion policy models and utilities

**Gymnasium 0.29.1 - Task/environment definitions (simulation environments)** 
- Note: TODO comment indicates work needed for gym 1.0.0 compatibility

**Configuration & CLI:**
- draccus 0.10.0 - Declarative configuration framework (registry-based subclass patterns)
- OmegaConf >=2.3.0 - Configuration management (YAML parsing, config composition)

**Testing:**
- pytest >=8.1.0 (optional, via `test` extra) - Test framework
- pytest-cov >=5.0.0 (optional) - Coverage reporting

**Build/Dev:**
- cmake >=3.29.0.1 - Required for native extensions (robotics libraries, codec backends)
- poetry-core - Poetry build backend

## Key Dependencies

**Critical:**
- datasets >=2.19.0 - HuggingFace datasets library for loading/streaming datasets
- huggingface-hub[hf-transfer,cli] >=0.27.1 - Hub API for model/dataset download and upload
- torch >=2.2.1,<2.7 - PyTorch (core ML framework)

**Video & Encoding:**
- av >=14.2.0 - PyAV bindings for ffmpeg (video decoding via pyav backend)
- torchcodec ==0.2.1 (conditional platform/arch) - Native video decoder (faster than pyav, not available on darwin x86_64)
- imageio[ffmpeg] >=2.34.0 - Image I/O with ffmpeg backend for video/frame saving
- torchvision >=0.21.0 - Video frame reading and transforms (torchvision.io.VideoReader)

**Data Storage & Serialization:**
- h5py >=3.10.0 - HDF5 file format support (dataset storage)
- zarr >=2.17.0 - Zarr array storage (chunked, compressed arrays for large datasets)
- jsonlines >=4.0.0 - JSONL format (human-readable sequences)

**Numerical & Scientific:**
- einops >=0.8.0 - Tensor operation notation (rearrange, reduce operations)
- numba >=0.59.0 - JIT compilation for numerical loops
- pymunk >=6.6.0 - Physics simulation (used in simulation environments)

**Computer Vision & Robotics:**
- opencv-python-headless >=4.9.0 - OpenCV for image processing (no GUI)
- numpy (via dependencies) - Array operations (implicit via torch, cv2)

**Infrastructure & Utilities:**
- wandb >=0.16.3 - Experiment tracking and logging
- rerun-sdk >=0.21.0 - Visualization SDK for robotics (trajectory/sensor visualization)
- pyzmq >=26.2.1 - ZeroMQ bindings for inter-process/network communication
- flask >=3.0.3 - Web framework (possibly for visualization server)
- gdown >=5.1.0 - Google Drive downloader (dataset fetching)
- pynput >=1.7.7 - Input device control (teleop leader arms)
- deepdiff >=7.0.1 - Deep dictionary comparison utilities
- termcolor >=2.4.0 - Colored terminal output
- packaging >=24.2 - Version parsing and comparison

## Optional Dependencies (Extras)

**Policy Families:**
- `pi0`: transformers >=4.48.0 - For Pi0 vision language model policy
- `aloha`: gym-aloha >=0.1.1 - ALOHA simulation environment
- `pusht`: gym-pusht >=0.1.5 - PushT simulation environment
- `xarm`: gym-xarm >=0.1.1 - XArm simulation environment
- `dora`: gym-dora (from git) - Dora robotics framework integration

**Robot-Specific Drivers:**
- `dynamixel`: dynamixel-sdk >=3.7.31 - Robotis Dynamixel motor control SDK
- `feetech`: feetech-servo-sdk >=1.0.0 - Feetech servo motor SDK
- `intelrealsense`: pyrealsense2 >=2.55.1.6486 (not darwin) - Intel RealSense camera API
- `stretch`: hello-robot-stretch-body >=0.7.27 (linux only), pyrealsense2, pyrender - Stretch robot SDK
- `umi`: imagecodecs >=2024.1.1 - Image codec support for UMI datasets

**Development:**
- `dev`: pre-commit >=3.7.0, debugpy >=1.8.1 - Development tools
- `docs`: hf-doc-builder (from git@main), watchdog >=6.0.0 - Documentation generation

**Testing & Benchmarking:**
- `test`: pytest >=8.1.0, pytest-cov >=5.0.0, pyserial >=3.5 - Testing utilities
- `video_benchmark`: scikit-image >=0.23.2, pandas >=2.2.2 - Video quality benchmarking

## Camera Integration Stack

**Available Camera Drivers:** (from `lerobot/common/robot_devices/cameras/`)
- `opencv.py` - OpenCV-based camera capture (USB cameras, V4L2)
- `intelrealsense.py` - Intel RealSense D400-series depth+color cameras via `pyrealsense2`
- `ros2.py` - **NEW (PR #866)** - ROS2 camera topic subscriber via `rclpy` + `cv_bridge`

**Camera Configuration:** (`lerobot/common/robot_devices/cameras/configs.py`)
- Base: `CameraConfig` (draccus registry pattern)
- `OpenCVCameraConfig` - USB camera by index
- `IntelRealSenseCameraConfig` - RealSense by serial number or name
- `ROS2CameraConfig` - ROS2 topic subscription

## Robot Device Architecture

**Motor Buses:**
- `DynamixelMotorsBusConfig` - Dynamixel SDK control (UART/USB)
- `FeetechMotorsBusConfig` - Feetech SDK control (UART/USB)

**Robots:** (from `lerobot/common/robot_devices/robots/configs.py`)
- `AlohaRobotConfig` - Dual-arm ALOHA (Dynamixel leader/follower arms)
- `MobileAlohaRobotConfig` - Mobile ALOHA variant
- `StretchRobotConfig` - Hello Robot Stretch (hello-robot-stretch-body SDK)
- `KochRobotConfig` - Koch arm
- `SO100Config`, `SO101Config` - SO-arm variants
- `JetankRobotConfig` - JETANK mobile robot

## Policy Families

**Implemented Policies:** (from `lerobot/common/policies/`)
- **ACT** (`act/`) - Action Chunking with Transformers (Diffusion policy variant)
- **Diffusion** (`diffusion/`) - Diffusion Policy (reverse SDE-based trajectory generation)
- **TDMPC** (`tdmpc/`) - Temporal Difference Model Predictive Control
- **VQBeT** (`vqbet/`) - Vector Quantized Behavior Transformer
- **Pi0** (`pi0/`) - Lightweight vision language model policy (via transformers)
- **Pi0Fast** (`pi0fast/`) - Optimized Pi0 variant
- **SmolVLA** - Vision Language Action model (referenced in comments, integration pending)

## Configuration & Build

**Format:** TOML (`pyproject.toml`)
- Project metadata: name, version, authors, license (Apache-2.0)
- Dependencies: core + optional groups
- Build system: poetry-core

**Linting & Formatting:**
- Ruff: target Python 3.10, line length 110
- Linting rules: E4, E7, E9, F, I, N, B, C4, SIM
- Bandit: security scanning (with specific skips)
- Pre-commit hooks: type checking, formatting, linting

## Platform Requirements

**Development:**
- macOS / Linux / Windows support
- Native Python 3.10+ (not conda-locked, but compatible with pyenv/venv)
- CMake >=3.29.0.1 for building native extensions

**Platform-Specific Notes:**
- torchcodec unavailable on: Windows, Linux aarch64/arm64/armv7l, macOS x86_64 (falls back to pyav)
- pyrealsense2 unavailable on: macOS (RealSense SDK not distributed for darwin)
- hello-robot-stretch-body: Linux only
- Paths with spaces unsupported (colcon/cmake limitation when used in monorepo)

## Production Deployment

**Model Serving:**
- HuggingFace Hub integration for model distribution
- SafeTensors format for model checkpoints
- WandB for experiment tracking and artifact logging

**Integration Points:**
- ROS2 middleware (DDS/CycloneDDS) for robot control via ROS2Camera
- ZeroMQ for inter-process communication
- Flask for optional visualization server

---

*Stack analysis: 2026-04-23*
