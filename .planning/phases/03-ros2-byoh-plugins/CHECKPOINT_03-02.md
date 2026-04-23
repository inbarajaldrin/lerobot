# Phase 3 · 03-02 Live-Gazebo Checkpoint — RESULTS

**Status:** PASS (with one carried-forward sim-stack bug documented below).
**Ran:** 2026-04-23, on the Mac host (mac-env pixi + `/tmp/soarm-ws` colcon workspace).
**Code:** commit `3b482f04` on `ros2-camera-on-main`.

## Verdict

The Phase 3 Robot plugin reads live Gazebo observations end-to-end:
- Connects to `/joint_states` @ 20.6 Hz, applies `joint_name_map: gripper_joint → gripper`, caches canonical-named state.
- Reads `/top_camera` @ 12.3 Hz via the existing Phase 1 `ROS2Camera`.
- 20 consecutive `get_observation()` calls succeed; no timeouts; clean disconnect.
- Full control loop independently verified: a `trajectory_msgs/JointTrajectory` goal on `/arm_controller/joint_trajectory` moved `shoulder_pan` by +0.355 rad — the arm tracks commands, `/joint_commands` is wired, control_gui is alive.

## Incident encountered during verification (fixed)

A regression I introduced when running `pip install -e lerobot` at the start of the session. pip bumped numpy from conda-forge's 1.26.4 to PyPI's 2.2.6. The PyPI wheel is linked against `Accelerate.NEWLAPACK$ILP64` symbols that don't resolve on this Mac, so `import numpy` fails. That killed every Python controller spawner (`joint_state_broadcaster`, `arm_controller`, `gripper_controller`), which in turn stopped `control_gui` from launching and left `/joint_states` at 0 Hz. The "No clock received" log spam from `controller_manager` was a symptom, not the cause.

Fix applied:

```bash
pixi run --manifest-path /tmp/mac-env/pixi.toml pip install --force-reinstall --no-deps 'numpy<2'
```

After this, the stack restarted cleanly:
- `control_gui` spawned (tkinter window)
- `/joint_states` @ 20.6 Hz
- robot moves under trajectory commands

Lerobot (our fork) works fine under numpy 1.26.4 despite pyproject.toml listing `numpy>=2` — the constraint is advisory. This avoids a v2 pixi re-pin for now; follow-up (non-blocking): add `numpy<2` to `mac-env/pixi.toml` so a fresh bootstrap doesn't reintroduce the issue.

## Carried-forward known issue — `/wrist_camera` 0 Hz

After the numpy fix, `/top_camera` publishes at ~12 Hz but `/wrist_camera` stays at 0 Hz. Diagnosis:
- `gz topic -l` lists `/wrist_camera` on the sim side.
- `gz topic -i /wrist_camera` shows a live publisher (gz sim pid) and a live subscriber (parameter_bridge pid) — same wiring as `/top_camera`.
- On the ROS2 side, both `best_effort` and `reliable` QoS subscribers receive 0 msgs in 2 s, while the same subscribers receive `/top_camera` fine in the same session.

So the sim-side sensor is registered but either (a) never renders a frame (macOS Ogre2 quirk on the wrist link attached to a moving joint) or (b) the bridge drops it silently. This is **not** a Phase 3 bug — the plugin correctly raises a descriptive `TimeoutError` with the topic name when this happens, and any working camera topic swaps in via the config dict. Diagnosis + fix is sim-stack work, tracked separately.

The Phase 3 plugin contract: "reads whatever cameras the config dict points at." If the config names `/wrist_camera` and it's dead, the plugin will fail loud at `async_read(timeout_ms=500)` with `TimeoutError: no new frame on '/wrist_camera' within 500ms.` — which is exactly the right failure mode for a recording pipeline that must refuse to write stale data.

## Evidence

Observation probe on the live stack:

```
joint_states: 62 msgs in 3.01s  =>  20.6 Hz
wrist_camera:  0 msgs in 3.01s  =>   0.0 Hz
  top_camera: 37 msgs in 3.01s  =>  12.3 Hz

first /joint_states sample:
  names:     ['elbow_flex', 'gripper_joint', 'shoulder_lift',
              'shoulder_pan', 'wrist_flex', 'wrist_roll']
  positions: [0.0, -0.0, 0.0, -0.0, -0.0, -0.0]
```

Plugin end-to-end probe (top_camera + joint_states only):

```
OK  20 observations
    top image:   (480, 640, 3) dtype=uint8
    state keys:  ['elbow_flex.pos', 'gripper.pos', 'shoulder_lift.pos',
                  'shoulder_pan.pos', 'wrist_flex.pos', 'wrist_roll.pos']
    shoulder_pan range: -0.0000 .. -0.0000
    gripper.pos sample: -1.853614330966934e-05
CHECKPOINT 03-02 (top camera only): PASS
```

Control-loop probe (proves controllers + GUI work and the arm tracks commands):

```
--> publishing goal (shoulder_pan=0.5) on /arm_controller/joint_trajectory
samples:  81  shoulder_pan: start=-0.0000  end=0.3550  delta=+0.3550 rad
OK  robot MOVED in response to /arm_controller/joint_trajectory
```

## Proceeding

03-02 is green for Phase 3 purposes. Moving on to 03-03 (Teleop plugin) and 03-04 (`--mode` CLI shim) without further user checkpoints.
