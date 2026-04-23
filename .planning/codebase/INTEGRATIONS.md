# External Integrations

**Analysis Date:** 2026-04-23

## APIs & External Services

**HuggingFace Hub:**
- Purpose: Host and distribute datasets, pretrained models, model cards
- SDK/Client: `huggingface_hub` >=0.27.1 with `hf-transfer` and `cli` extras
- Auth: `HF_TOKEN` environment variable
- Usage: `HfApi`, `snapshot_download`, `hf_hub_download`, `DatasetCard`, `DatasetCardData`
- Files: `lerobot/common/datasets/lerobot_dataset.py`, `lerobot/common/datasets/utils.py`

**Weights & Biases (W&B):**
- Purpose: Experiment tracking, hyperparameter logging, model artifact storage
- SDK/Client: `wandb` >=0.16.3
- Auth: `WANDB_API_KEY` (or interactive login)
- Config: `TrainPipelineConfig.wandb` (project, entity, mode, notes, disable_artifact)
- Features: Run resumption by ID, artifact logging (SafeTensors model files), metrics tracking (train/eval)
- Files: `lerobot/common/utils/wandb_utils.py` (`WandBLogger` class)

## Data Storage

**Databases:**
- None (data stored in files/cloud, not DB-backed)

**File Storage:**

| Format/Service | Client | Purpose | Location |
|---|---|---|---|
| HDF5 | `h5py` >=3.10.0 | Dense dataset storage | `lerobot/common/datasets/` |
| Zarr | `zarr` >=2.17.0 | Chunked/compressed arrays (large-scale) | `lerobot/common/datasets/` |
| JSONL | `jsonlines` >=4.0.0 | Structured metadata (human-readable) | Dataset episode configs |
| PNG / JPEG | `PIL` (via imageio) | Frame images (lossless storage) | Raw dataset directories |
| MP4 / Video | `imageio[ffmpeg]`, `av`, `torchcodec` | Encoded video storage | Dataset video files |
| SafeTensors | `safetensors` (implicit via HF Hub) | Model weights (safe, atomic) | Model checkpoints |
| Local Filesystem | Native | Primary data store | `~/.cache/huggingface/datasets/` or custom paths |

**Caching:**
- HuggingFace datasets cached to: `HF_HOME` (default `~/.cache/huggingface/`)
- Models cached to: `lerobot/.cache/pretrained_models/` (configurable via `PRETRAINED_MODEL_DIR`)
- No explicit memory cache (datasets loaded on-demand)

## Authentication & Identity

**Auth Provider:**
- Custom: Token-based (HuggingFace Hub tokens, W&B API keys)
- No OAuth/SAML integration

**Credentials Management:**
- Environment variables: `HF_TOKEN`, `WANDB_API_KEY`
- Stored by: huggingface-cli, wandb CLI
- Location: `~/.huggingface/token`, `~/.wandb/`

## Monitoring & Observability

**Error Tracking:**
- Weights & Biases - Primary tracking (exceptions logged to W&B)
- No Sentry/other error trackers

**Logs:**
- W&B: Structured metrics (train/eval loss, accuracy, video validation)
- Console: Python logging (termcolor for coloring)
- Files: Model checkpoints + metadata (via W&B artifacts or local storage)
- Rerun SDK: Real-time 3D visualization of trajectories/sensor data

## CI/CD & Deployment

**Hosting:**
- HuggingFace Hub (models and datasets)
- W&B (experiment tracking and artifacts)
- Local filesystem or cloud storage (training checkpoints)

**CI Pipeline:**
- GitHub Actions: `.github/workflows/`
  - `test.yml` - Unit tests
  - `nightly-tests.yml` - Nightly test suite
  - `quality.yml` - Linting, type checking, security (bandit, trufflehog)
  - `build-docker-images.yml` - Docker image builds
  - `upload_pr_documentation.yml` - PR documentation

## Environment Configuration

**Required Env Vars:**
- `HF_TOKEN` - HuggingFace Hub authentication (dataset/model push/pull)
- `WANDB_API_KEY` - Weights & Biases authentication
- `HF_HOME` - HuggingFace cache directory (optional, defaults to `~/.cache/huggingface/`)
- `WANDB_DIR` - W&B local run directory (optional)

**Secrets Location:**
- `.huggingface/token` - HF Hub token (created by `huggingface-cli login`)
- `.wandb/` - W&B credentials (created by `wandb login`)
- `.env` or environment (not committed)

## Camera & Robot Integrations

### Camera Drivers

**OpenCV USB Cameras:**
- Driver: `lerobot/common/robot_devices/cameras/opencv.py`
- SDK: `opencv-python-headless` >=4.9.0 (headless version, no GUI)
- Auth: None (local device)
- Features: USB camera capture, color space conversion (RGB/BGR), rotation
- Config: `OpenCVCameraConfig` (camera_index, fps, width, height, color_mode, rotation)

**Intel RealSense Depth Cameras:**
- Driver: `lerobot/common/robot_devices/cameras/intelrealsense.py`
- SDK: `pyrealsense2` >=2.55.1.6486 (not available on macOS)
- Auth: None (USB device)
- Features: RGB + depth streams, serial number discovery, hardware reset
- Config: `IntelRealSenseCameraConfig` (serial_number or name, fps, width, height, use_depth, rotation)
- Mock support: `tests/cameras/mock_pyrealsense2.py`

**ROS2 Network Cameras (NEW - PR #866):**
- Driver: `lerobot/common/robot_devices/cameras/ros2.py`
- SDK: `rclpy`, `cv_bridge` (ROS2 core + vision bridge)
- Auth: DDS middleware (CycloneDDS) configuration
- Features: Subscribe to ROS2 image topics (`sensor_msgs/Image`), auto-detect resolution, rotation
- Config: `ROS2CameraConfig` (topic, fps, width, height, encoding, channels, rotation)
- Implementation: Thread-based ROS2 node spin, subscription-based message buffering, singleton ROS2 node
- Files:
  - `lerobot/common/robot_devices/cameras/ros2.py` - Main `ROS2Camera` class
  - `lerobot/common/robot_devices/cameras/configs.py` - `ROS2CameraConfig` dataclass

### Motor/Robot Drivers

**Dynamixel Motors (Robotis):**
- SDK: `dynamixel-sdk` >=3.7.31 (Python wrapper)
- Protocol: Dynamixel 2.0 (serial communication)
- Auth: None (serial port)
- Models: XL430, XM430, XM540, XC430 (configuration in robot configs)
- Features: Position/velocity/torque control, goal position setting, protocol 2.0
- Driver: `lerobot/common/robot_devices/motors/dynamixel.py`
- Config: `DynamixelMotorsBusConfig` (port, baudrate, motors dict)

**Feetech Motors:**
- SDK: `feetech-servo-sdk` >=1.0.0
- Protocol: Similar to Dynamixel 2.0
- Auth: None (serial port)
- Driver: `lerobot/common/robot_devices/motors/feetech.py`
- Config: `FeetechMotorsBusConfig` (port, baudrate, motors dict)

**Stretch Robot:**
- SDK: `hello-robot-stretch-body` >=0.7.27 (Linux only)
- Auth: None (localhost hardware)
- Driver: `lerobot/common/robot_devices/robots/stretch.py`
- Features: Full-body arm + mobile base control

### Environment/Simulation Integrations

**Gymnasium Environments:**
- `gym-aloha` >=0.1.1 - ALOHA dual-arm simulation
- `gym-pusht` >=0.1.5 - PushT manipulation task
- `gym-xarm` >=0.1.1 - XArm arm control task
- `gym-dora` (git) - Dora robotics framework

## Video & Media Processing

**Video Decoding (Dataset Loading):**

| Backend | Library | Speed | Platform Support | Usage |
|---------|---------|-------|------------------|-------|
| torchcodec | `torchcodec` ==0.2.1 | Fast (native) | Not darwin x86_64 | Default if available |
| pyav | `av` >=14.2.0 | Slower | All (via ffmpeg) | Fallback default |
| torchvision | `torchvision` >=0.21.0 | Medium | All | Optional ("video_reader") |

- Implementation: `lerobot/common/datasets/video_utils.py`
  - `decode_video_frames()` - Main entry point
  - `decode_video_frames_torchcodec()` - Fast decoder
  - `decode_video_frames_torchvision()` - Fallback (pyav or video_reader backend)
- Features: Frame seeking, tolerance-based timestamp matching, key frame optimization

**Video Encoding (Frame→Video):**
- Tool: ffmpeg (via `imageio[ffmpeg]`)
- Library: `imageio` >=2.34.0
- Implementation: `lerobot/common/datasets/image_writer.py`, `lerobot/common/utils/io_utils.py`
- Features: Batch frame encoding to MP4, configurable bitrate/codec

**Frame I/O:**
- Format: PNG (lossless)
- Library: `PIL` (Pillow)
- Location: `lerobot/common/robot_devices/cameras/ros2.py`, `intelrealsense.py`

## Communication Protocols

**ROS2 / DDS:**
- Middleware: CycloneDDS (default ROS2 on RoboStack macOS)
- Usage: Camera image topics (`sensor_msgs/Image`), robot control (action servers)
- Config: `cyclonedds.xml` (localhost/lo0 binding)
- Integration: `rclpy` (ROS2 Python client)

**ZeroMQ:**
- Library: `pyzmq` >=26.2.1
- Purpose: Inter-process or network communication (teleop, sensor fusion, etc.)
- Implementation: Not directly visible in main code, available for extensions

## Dataset & Model Hub

**HuggingFace Datasets Hub:**
- Org: `https://huggingface.co/lerobot`
- Download: `lerobot/common/datasets/lerobot_dataset.py` (via `snapshot_download`)
- Upload: `lerobot/common/datasets/utils.py` (via `HfApi.upload_folder`)
- Formats: HDF5, Zarr, JSONL metadata, MP4 videos
- Versioning: Git LFS via Hub

**HuggingFace Model Hub:**
- Push: Checkpoint models via W&B integration → HF Hub
- Pull: `huggingface_hub.snapshot_download` or `hf_hub_download`
- Format: SafeTensors (atomic, safe deserialization)

## Webhooks & Callbacks

**Incoming:**
- None documented (datasets/models pulled on-demand)

**Outgoing:**
- W&B: Metrics logged every training step via `wandb.log()`
- HF Hub: Models pushed post-training (via W&B artifacts or direct push)

## Visualization & Inspection

**Rerun SDK:**
- Library: `rerun-sdk` >=0.21.0
- Purpose: Real-time 3D visualization of robot trajectories, camera frames, keypoints
- Usage: Log poses, point clouds, images to Rerun server (local or remote)

**Web UI:**
- Flask: `flask` >=3.0.3 (optional server for dataset browsing/visualization)
- Notebooks: Jupyter integration for interactive training/evaluation

---

*Integration audit: 2026-04-23*
