This file provides guidance to AI agents when working with code in this repository.

> **User-facing help → [`AGENT_GUIDE.md`](./AGENT_GUIDE.md)** (SO-101 setup, recording, picking a policy, training duration, eval — with copy-pasteable commands).
>
> **ROS2 plugin authoring → [`ROS2_PLUGINS.md`](./ROS2_PLUGINS.md)** (fork-specific: two-tier plugin architecture, per-arm plugin workflow, rclpy singleton, known macOS gotchas).
>
> **Project state / what's been built → `.planning/STATE.md`, `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, `.planning/phases/*/SUMMARY.md`** — this is a `gsd`-style planned fork; the planning dir is the ground truth for *why* things were built and *what's next*.
>
> **macOS context → `../vla_SO-ARM101/docs/LEROBOT_ROS2_MAC_SETUP.md`** is the living runbook for using this fork on Apple Silicon.

## Project Overview

LeRobot is a PyTorch-based library for real-world robotics, providing datasets, pretrained policies, and tools for training, evaluation, data collection, and robot control. It integrates with Hugging Face Hub for model/dataset sharing.

**This fork** (branch `ros2-camera-on-main`) adds first-class ROS2 support — see `ROS2_PLUGINS.md` for architecture. Three plugins not in upstream:

- `lerobot.cameras.ros2.ROS2Camera` — `--robot.cameras='{wrist: {type: ros2, topic: /wrist_camera, ...}}'`
- `lerobot.robots.so101_ros2.SO101ROS2Robot` — `--robot.type=so101_ros2`
- `lerobot.teleoperators.so101_ros2.SO101ROS2Teleoperator` — `--teleop.type=so101_ros2`

Both robot plugins must be imported in `src/lerobot/scripts/lerobot_record.py` and `lerobot_teleoperate.py` for `@register_subclass` discovery.

## Tech Stack

Python 3.12+ · PyTorch · Hugging Face (datasets, Hub, accelerate) · draccus (config/CLI) · Gymnasium (envs) · `uv` (upstream/Linux package mgr) · `pixi` + RoboStack (this fork on macOS, lives at `/tmp/mac-env/`)

## Development setup — pick your platform

**macOS Apple Silicon (recommended for this fork):** see the parent project's bootstrap. The fork lives as a submodule of `Exploring-VLAs`; build via `bash ../mac-env/scripts/bootstrap.sh`. The conventional `uv sync` path doesn't apply — RoboStack ships ROS2 + Python deps as conda packages.

**Linux / upstream-style** (no ROS2 needed):

```bash
uv sync --locked                            # Base dependencies
uv sync --locked --extra test --extra dev   # Test + dev tools
uv sync --locked --extra all                # Everything
git lfs install && git lfs pull             # Test artifacts
```

## Key commands

```bash
# Upstream test/lint (Linux path)
uv run pytest tests -svv --maxfail=10                 # All tests
DEVICE=cuda make test-end-to-end                      # All E2E tests
pre-commit run --all-files                            # Lint + format (ruff, typos, bandit, etc.)

# macOS / fork path — replace `uv run` with pixi-run-via-mac-env:
pixi run --manifest-path /tmp/mac-env/pixi.toml pytest tests -svv

# Fork-specific record pipeline (assumes mac-env bootstrap done):
bash ../mac-env/scripts/stack_start.sh headless                # bring up Gazebo
bash ../mac-env/scripts/record.sh --dataset.repo_id=...        # record (sim default)
bash ../mac-env/scripts/record.sh --mode=real --dataset...     # real-hw record
```

## Architecture (`src/lerobot/`)

- **`scripts/`** — CLI entry points (`lerobot-train`, `lerobot-eval`, `lerobot-record`, etc.), mapped in `pyproject.toml [project.scripts]`.
- **`configs/`** — Dataclass configs parsed by draccus. `train.py` has `TrainPipelineConfig` (top-level). `policies.py` has `PreTrainedConfig` base. Polymorphism via `draccus.ChoiceRegistry` with `@register_subclass("name")` decorators.
- **`policies/`** — Each policy in its own subdir. All inherit `PreTrainedPolicy` (`nn.Module` + `HubMixin`) from `pretrained.py`. Factory with lazy imports in `factory.py`.
- **`processor/`** — Data transformation pipeline. `ProcessorStep` base with registry. `DataProcessorPipeline` / `PolicyProcessorPipeline` chain steps.
- **`datasets/`** — `LeRobotDataset` (episode-aware sampling + video decoding) and `LeRobotDatasetMetadata`.
- **`envs/`** — `EnvConfig` base in `configs.py`, factory in `factory.py`. Each env subclass defines `gym_kwargs` and `create_envs()`.
- **`robots/`, `motors/`, `cameras/`, `teleoperators/`** — Hardware abstraction layers.
- **`types.py`** and **`configs/types.py`** — Core type aliases and feature type definitions.

## Repository Structure (outside `src/`)

- **`tests/`** — Pytest suite organized by module. Fixtures in `tests/fixtures/`, mocks in `tests/mocks/`. Hardware tests use skip decorators from `tests/utils.py`. E2E tests via `Makefile` write to `tests/outputs/`.
- **`.github/workflows/`** — CI: `quality.yml` (pre-commit), `fast_tests.yml` (base deps, every PR), `full_tests.yml` (all extras + E2E + GPU, post-approval), `latest_deps_tests.yml` (daily lockfile upgrade), `security.yml` (TruffleHog), `release.yml` (PyPI publish on tags).
- **`docs/source/`** — HF documentation (`.mdx` files). Per-policy READMEs, hardware guides, tutorials. Built separately via `docs-requirements.txt` and CI workflows.
- **`examples/`** — End-user tutorials and scripts organized by use case (dataset creation, training, hardware setup).
- **`docker/`** — Dockerfiles for user (`Dockerfile.user`) and CI (`Dockerfile.internal`).
- **`benchmarks/`** — Performance benchmarking scripts.
- **Root files**: `pyproject.toml` (single source of truth for deps, build, tool config), `Makefile` (E2E test targets), `uv.lock`, `CONTRIBUTING.md` & `README.md` (general information).

## Notes

- **Mypy is gradual**: strict only for `lerobot.envs`, `lerobot.configs`, `lerobot.optim`, `lerobot.model`, `lerobot.cameras`, `lerobot.motors`, `lerobot.transport`. Add type annotations when modifying these modules.
- **Optional dependencies**: many policies, envs, and robots are behind extras (e.g., `lerobot[aloha]`). New imports for optional packages must be guarded or lazy. See `pyproject.toml [project.optional-dependencies]`.
- **Video decoding**: datasets can store observations as video files. `LeRobotDataset` handles frame extraction, but tests need ffmpeg installed.
- **Prioritize use of `uv run`** to execute Python commands (not raw `python` or `pip`) on Linux. On macOS use `pixi run --manifest-path /tmp/mac-env/pixi.toml ...` instead.

## ROS2 fork-specific rules (read before touching anything in `cameras/ros2/`, `robots/so101_ros2/`, or `teleoperators/so101_ros2/`)

- **rclpy singleton, hard rule.** Do NOT call `rclpy.init()` directly or start your own spin thread. Use `ROS2Camera._ensure_rclpy_started()` and reuse `ROS2Camera._rclpy_node`. macOS spin-thread races on multiple nodes (`ValueError: generator already executing`) — one shared executor is the workaround. See `ROS2_PLUGINS.md` § rclpy singleton.
- **`SO101ROS2Robot.send_action` is a no-op by design.** Returns input unchanged. The teleop / drive script / leader arm publishes `/joint_commands`; the Robot plugin only produces observations. Don't "fix" this without reading `ROS2_PLUGINS.md` § send_action no-op contract.
- **`numpy<2` pin on macOS** — `pip install -e .` bumps numpy to 2.x which kills controller spawners (`Accelerate NEWLAPACK$ILP64`). After any pip touching numpy: `pixi run pip install --force-reinstall --no-deps 'numpy<2'`.
- **`ros2` CLI hangs on macOS without `--no-daemon`**. Always pass `--no-daemon` to topic list / topic hz / topic echo / pkg list, etc.
- **CycloneDDS env vars** — required for cross-process discovery on macOS:
  ```bash
  export CYCLONEDDS_URI=file:///tmp/mac-env/cyclonedds.xml
  export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
  export KMP_DUPLICATE_LIB_OK=TRUE
  ```
- **Plugin discovery requires explicit imports** in `src/lerobot/scripts/lerobot_record.py` and `lerobot_teleoperate.py`. Adding a new `<arm>_ros2` plugin without updating those scripts → `--robot.type=<arm>_ros2` fails with "invalid choice".
