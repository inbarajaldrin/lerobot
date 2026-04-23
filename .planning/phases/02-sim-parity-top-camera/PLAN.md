# Phase 2 Plan: Sim Parity — Top Camera

**Phase goal:** Gazebo publishes both `/wrist_camera` and `/top_camera` on ROS2 so the sim observation schema matches the real SO-101 dataset's two-camera schema.

**Requirements covered:** FOUND-04 (no-op — already canonical), OBS-03.

**Scope collapse:** FOUND-04 was a misread on my part — every joint name in the SO-ARM101 URDF, SRDF, controllers, and joint_limits already matches HF canonical (`shoulder_pan/shoulder_lift/elbow_flex/wrist_flex/wrist_roll/gripper_joint`). Marking that REQ Complete as a no-op. Phase 2 shrinks from 2 plans to 1.

## Decisions (locked)

| Decision | Chosen | Rationale |
|---|---|---|
| Top camera resolution | **640×480 @ 30 fps R8G8B8** | Matches the RealSense top camera in `LEROBOT_GUIDE.md` (your colleague's real flow). Swapping is a 3-line change if Phase 5 parity demands it. |
| Top camera pose | **Attached to a new `top_camera_link`, fixed to `world` at (0, 0, 0.6 m), rotated so optical axis points down** | Standard tabletop top-down view. Workspace is ~40 cm wide around origin; 60 cm height gives a reasonable FOV. |
| Optical convention | **`ros_gz` camera with image frame pointing -Z in world** | Matches ROS image convention (X-right, Y-down, Z-into-scene) used by `ros_gz_bridge`. |
| Mount link | **New fixed `top_camera_link` off `world`** | Keeps camera outside the arm's TF chain; MoveIt planning doesn't see it as an end-effector. |

## Tasks

### 02-01 — Top camera: xacro + bridge

**File 1: `src/so_arm101_description/urdf/so_arm101.gazebo.xacro`** — add near the existing `wrist_camera` sensor block:

```xml
<!-- Top camera (tabletop top-down view for pick-and-place datasets) -->
<link name="top_camera_link">
  <inertial>
    <mass value="0.01"/>
    <inertia ixx="1e-5" ixy="0" ixz="0" iyy="1e-5" iyz="0" izz="1e-5"/>
  </inertial>
  <visual>
    <geometry><box size="0.04 0.04 0.02"/></geometry>
    <material name="black"><color rgba="0.1 0.1 0.1 1"/></material>
  </visual>
</link>

<joint name="top_camera_joint" type="fixed">
  <parent link="world"/>
  <child link="top_camera_link"/>
  <!-- 60 cm above origin, rotated so the camera's +X (image forward) faces -Z (down) -->
  <origin xyz="0 0 0.6" rpy="0 1.5708 0"/>
</joint>

<gazebo reference="top_camera_link">
  <sensor name="top_camera" type="camera">
    <pose>0 0 0 0 0 0</pose>
    <always_on>1</always_on>
    <update_rate>30</update_rate>
    <visualize>true</visualize>
    <ignition_frame_id>top_camera_link</ignition_frame_id>
    <camera name="top_camera">
      <horizontal_fov>1.2</horizontal_fov>
      <image>
        <width>640</width>
        <height>480</height>
        <format>R8G8B8</format>
      </image>
      <clip><near>0.05</near><far>5.0</far></clip>
    </camera>
    <topic>top_camera</topic>
    <camera_info_topic>top_camera/camera_info</camera_info_topic>
  </sensor>
</gazebo>
```

**File 2: `src/so_arm101_control/launch/gazebo.launch.py`** — user has uncommitted work here, so APPEND only. Locate the existing `parameter_bridge` `arguments=[...]` list and add two entries:

```python
'/top_camera@sensor_msgs/msg/Image[gz.msgs.Image',
'/top_camera/camera_info@sensor_msgs/msg/CameraInfo[gz.msgs.CameraInfo',
```

## Static verification (runs inside this session)

1. **xacro parse**: `xacro so_arm101.gazebo.xacro > /tmp/out.urdf` should succeed with exit 0; output should contain both `wrist_camera` and `top_camera_link`.
2. **Launch file syntax**: `python -c "import ast; ast.parse(open('gazebo.launch.py').read())"` should return cleanly.
3. **Grep check**: both `wrist_camera` and `top_camera` appear in the bridge argument list.
4. **No duplicate names**: the new `top_camera_link` + `top_camera_joint` don't collide with anything existing in `so_arm101.urdf.xacro`'s `<link>` / `<joint>` names.

## Runtime verification (deferred)

Requires the full SO-ARM101 Gazebo stack — not installable in the current `mac-env` pixi env. Deferred to Phase 5's full-stack runbook:
- `ros2 topic list` includes `/top_camera` + `/top_camera/camera_info`
- `ros2 topic hz /top_camera` reports ≥ 25 Hz
- Frame contents look like a reasonable top-down view of the workspace (eyeball via rviz or image_view)

This is captured explicitly as a Phase 5 follow-up in its runbook.

## Risks

| Risk | Mitigation |
|---|---|
| User's uncommitted edits to `gazebo.launch.py` make the bridge list location ambiguous | Read the file first; find the existing `parameter_bridge` `arguments=[...]` block and add entries inside. Don't reformat. |
| FOV 1.2 rad (~68°) doesn't cover the full workspace | Re-tune in Phase 5 based on pick-and-place visual content. Easy two-number change in the xacro. |
| Pose orientation wrong — top-down view shows the wrong axis as "up" in image | Verify visually in Phase 5; rotate by -90° around image-plane axes if needed. |
| Gazebo Harmonic's camera plugin needs a specific SDF element we missed | Mirror the existing working `wrist_camera` block exactly; only swap the pose and link attachment. |

## Out of scope for Phase 2

- Running Gazebo (requires separate pixi env with `ros-jazzy-ros-gz` + SO-ARM101 packages colcon-built).
- Matching the real dataset's exact camera intrinsics — that's a Phase 5 parity-tuning task.
- Any URDF joint renaming (already canonical).
