# Phase 3 · 03-02 Live-Gazebo Checkpoint

Run this on the host that has the SO-ARM101 Gazebo stack (mac-env + `/tmp/soarm-ws`). Code is at commit `3b482f04` on `ros2-camera-on-main`.

The in-process smoke on the mac-env env is already green (synthetic `/joint_states` publisher → `SO101ROS2Robot.connect()` → `get_observation()`). What remains is: does the plugin actually read live Gazebo joint state + bridged camera frames without locking up or dropping messages?

## Prerequisites

```bash
# From the repo root:
cd agents/ros2

# Reinstall lerobot editable into /tmp/mac-env (picks up 03-01/03-02 source).
# This only matters once; the plugin code is symlinked via -e so edits land live.
export PATH="$HOME/.pixi/bin:$PATH"
pixi run --manifest-path /tmp/mac-env/pixi.toml pip install -e \
  "$(pwd)/repos/Exploring-VLAs/lerobot"
```

## Step 1 — Bring up the stack

```bash
bash repos/Exploring-VLAs/mac-env/scripts/stack_start.sh gz
```

Wait for Gazebo window to render. Expect the known "controller_manager: No clock received" log noise — it's the Phase-2-era spawner issue and may still cause `/joint_states` to publish at 0 Hz.

## Step 2 — Pre-flight the topics

```bash
pixi run --manifest-path /tmp/mac-env/pixi.toml bash -c '
  source /tmp/soarm-ws/install/setup.bash 2>/dev/null || true
  export CYCLONEDDS_URI=file:///tmp/mac-env/cyclonedds.xml
  export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
  ros2 topic list | grep -E "(joint_states|wrist_camera|top_camera)"
  echo "--- hz /joint_states (5s):"
  timeout 5 ros2 topic hz /joint_states
  echo "--- hz /wrist_camera (5s):"
  timeout 5 ros2 topic hz /wrist_camera
  echo "--- hz /top_camera (5s):"
  timeout 5 ros2 topic hz /top_camera
'
```

**What must be true before proceeding:** all three topics exist; `/wrist_camera` and `/top_camera` show ≥ 25 Hz; `/joint_states` shows > 0 Hz (even 1 Hz is fine for this checkpoint — we just need messages).

**If `/joint_states` is 0 Hz:** this is the carry-over from Phase 2. Diagnose before continuing — the most likely cause is the `joint_state_broadcaster` spawner crashing with the importlib error mentioned in STATE.md. Fix on `vla_SO-ARM101/src/so_arm101_control/` and re-run Step 1. Do not continue the checkpoint with a 0 Hz topic; the plugin will correctly raise a readable `TimeoutError` after 5 s.

## Step 3 — End-to-end plugin smoke

Drop this script anywhere (e.g. `/tmp/so101_ros2_checkpoint.py`) and run it inside the mac-env pixi shell:

```python
"""03-02 live-Gazebo checkpoint.

Exercises SO101ROS2Robot against the full SO-ARM101 Gazebo stack.
Prints either OK for every check or a readable diagnostic on failure.
"""
import time

from lerobot.cameras.ros2 import ROS2CameraConfig
from lerobot.robots.so101_ros2 import SO101ROS2Robot, SO101ROS2RobotConfig

cfg = SO101ROS2RobotConfig(
    state_timeout_s=8.0,
    image_timeout_ms=1000,
    cameras={
        "wrist": ROS2CameraConfig(topic="/wrist_camera", width=1280, height=720, fps=30),
        "top":   ROS2CameraConfig(topic="/top_camera",   width=640,  height=480, fps=30),
    },
)
robot = SO101ROS2Robot(cfg)
robot.connect()

try:
    # Read 30 observations over ~3 seconds; track shapes and values.
    shoulder_positions = []
    for i in range(30):
        obs = robot.get_observation()
        assert set(obs) == set(robot.observation_features), set(obs).symmetric_difference(set(robot.observation_features))
        assert obs["wrist"].shape == (720, 1280, 3), obs["wrist"].shape
        assert obs["top"].shape == (480, 640, 3), obs["top"].shape
        shoulder_positions.append(obs["shoulder_pan.pos"])
        time.sleep(0.1)
    print(f"OK  30 observations, shoulder_pan range: "
          f"{min(shoulder_positions):.3f} .. {max(shoulder_positions):.3f}")
    print(f"OK  wrist image shape: {obs['wrist'].shape} dtype={obs['wrist'].dtype}")
    print(f"OK  top   image shape: {obs['top'].shape} dtype={obs['top'].dtype}")
    print(f"OK  state keys: {sorted(k for k in obs if k.endswith('.pos'))}")
finally:
    robot.disconnect()
print("CHECKPOINT 03-02: PASS")
```

Run it:

```bash
pixi run --manifest-path /tmp/mac-env/pixi.toml bash -c '
  export CYCLONEDDS_URI=file:///tmp/mac-env/cyclonedds.xml
  export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
  export KMP_DUPLICATE_LIB_OK=TRUE
  python /tmp/so101_ros2_checkpoint.py
'
```

**Must see:**
- `OK  30 observations, shoulder_pan range: …` with a sensible range (even if the arm is idle, a small range like `-0.001 .. 0.001` is fine).
- Both image shapes exactly matching the config.
- `state keys: ['elbow_flex.pos', 'gripper.pos', 'shoulder_lift.pos', 'shoulder_pan.pos', 'wrist_flex.pos', 'wrist_roll.pos']`.
- Final line `CHECKPOINT 03-02: PASS`.

## Step 4 — `lerobot-teleoperate` dry run (optional but recommended)

Confirms the plugin plays nicely with upstream's teleop CLI using the keyboard teleop (cheap, always available):

```bash
pixi run --manifest-path /tmp/mac-env/pixi.toml bash -c '
  export CYCLONEDDS_URI=file:///tmp/mac-env/cyclonedds.xml
  export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
  export KMP_DUPLICATE_LIB_OK=TRUE
  lerobot-teleoperate \
    --robot.type=so101_ros2 \
    --robot.cameras="{wrist: {type: ros2, topic: /wrist_camera, width: 1280, height: 720, fps: 30}, top: {type: ros2, topic: /top_camera, width: 640, height: 480, fps: 30}}" \
    --teleop.type=keyboard
'
```

Expected: it connects, prints observations, and accepts keyboard inputs (which we ignore downstream because `send_action` is a no-op). Ctrl-C to stop.

## Step 5 — Tear down the stack

```bash
pkill -SIGINT -f "ros2.*launch" 2>/dev/null
# Or: bash repos/Exploring-VLAs/mac-env/scripts/stack_stop.sh
```

## Reporting back

Paste the output of Step 3 (the python script) here. Three possible outcomes:

1. **Green — `CHECKPOINT 03-02: PASS`:** sign off, I'll kick off 03-03 and 03-04.
2. **State TimeoutError from connect():** `/joint_states` is 0 Hz or the joint names don't overlap. Share the `ros2 topic echo /joint_states -n 1` output and the broadcaster spawner log, I'll patch.
3. **Image TimeoutError from get_observation():** camera is publishing but `async_read` starves. Usually means a QoS mismatch in `ROS2Camera` or Gazebo frames being slower than 500 ms under RViz+GUI load — either bump `image_timeout_ms` in the checkpoint script and re-run, or share `ros2 topic hz /wrist_camera` so I can confirm.

Once green, I proceed autonomously through 03-03 (Teleop plugin) and 03-04 (`--mode` shim) without further stops.
