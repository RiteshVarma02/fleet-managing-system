# Fleet files: push the waypoint JSON (and map) to every robot

The fleet has **one** waypoint graph JSON and **one** map. Every robot keeps its
own copy. These scripts put a new version on all robots at once, verify
each copy by checksum, and tell you which robots got it.

```
fleet PC                                        each robot
push_fleet_files.py  --/{robot}/fleet/file_update-->  fleet_file_receiver.py
                     <--/{robot}/fleet/file_ack-----   writes graph/map, runs --on-update
```

Topic names come from `backend/config/fleet_topics.yaml` (`file_update`,
`file_ack`, `goal`), the same single place the backend uses.

## 1. On every robot (once, keep it running)

Copy `fleet_file_receiver.py` and `fleet_file_protocol.py` to the robot, then:

```bash
source /opt/ros/humble/setup.bash
python3 fleet_file_receiver.py --robot-ns robot1 \
    --graph-path /home/hs/Downloads/drl_map.json \
    --map-dir /home/hs/3d_slam_ws/src/nav2_config/maps \
    --on-update "systemctl --user restart route_manager"   # optional
```

* `--graph-path` must be the exact file route_manager / `mission_commander.py`
  loads. It is replaced atomically, and the previous file is kept as `*.bak`.
* `--on-update` runs after a successful write (`$FLEET_FILE_KIND` is `graph` or
  `map`). Use it to restart whatever reads the files.

## 2. On the fleet PC, whenever the JSON or map changes

```bash
source /opt/ros/humble/setup.bash
cd tools/fleet_files

# graph JSON to every robot that is online (auto-discovered via /{robot}/amr/goal)
python3 push_fleet_files.py --graph ~/maps/amr_path.json

# graph + map, to named robots only
python3 push_fleet_files.py --graph amr_path.json --map ariyan_FMS.yaml --robots robot1 kumki
```

Example output:

```
📦 graph 2026-10-15T01:30:00Z: amr_path.json (4 KB)
🤖 robots: kumki, robot1

  kumki            graph  ✅ /home/hs/Downloads/drl_map.json
  robot1           graph  FAILED: this robot has no --graph-path configured

Some robots were NOT updated.
```

The exit code is `0` only when every robot confirmed every file.

## Safety checks

* The graph is validated **before** sending and again on the robot: it needs a
  non-empty `waypoints` list with unique integer `id`s and unique `name`s
  (what `mission_commander.py` relies on).
* Every file carries a sha256. A corrupted copy is rejected and nothing is written.
* Sender file names are stripped to a bare name, so they can't write outside `--map-dir`.
* The map `.yaml` must have `image`, `resolution` and `origin`, and its image must sit next to it.

## Tests

```bash
pip install pytest pyyaml
pytest tools/fleet_files      # no ROS needed
```
