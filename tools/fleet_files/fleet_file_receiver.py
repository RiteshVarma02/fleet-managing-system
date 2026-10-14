#!/usr/bin/env python3
"""Robot side: receive the waypoint graph JSON / fleet map and write them.

Run on EACH robot (ROS 2 sourced, same ROS_DOMAIN_ID as the fleet PC):

    python3 fleet_file_receiver.py --robot-ns robot1 \\
        --graph-path /home/hs/Downloads/drl_map.json \\
        --map-dir /home/hs/3d_slam_ws/src/nav2_config/maps \\
        --on-update "systemctl --user restart route_manager"

* --graph-path   the exact file route_manager / mission_commander.py loads.
                 It is overwritten atomically; the old copy is kept as *.bak.
* --map-dir      where the map .yaml + image go (same file names as sent).
* --on-update    optional shell command run after a successful write, e.g.
                 to restart the nodes that read these files. The kind
                 ("graph" or "map") is passed in $FLEET_FILE_KIND.

Topic names come from fleet_topics.yaml when --topics-config is given,
otherwise the defaults /{robot}/fleet/file_update and /{robot}/fleet/file_ack.
Only needs this file + fleet_file_protocol.py on the robot.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fleet_file_protocol import FleetFileError, apply_update, load_topic_templates, topic_for  # noqa: E402

LATCHED = QoSProfile(
    depth=1,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
)


class Receiver(Node):
    def __init__(self, args):
        super().__init__("fleet_file_receiver")
        self.args = args
        templates = load_topic_templates(args.topics_config, args.robot_type)
        update_topic = topic_for(templates["file_update"], args.robot_ns)
        ack_topic = topic_for(templates["file_ack"], args.robot_ns)
        self._seen = set()
        self.ack_pub = self.create_publisher(String, ack_topic, 10)
        self.create_subscription(String, update_topic, self._on_update, LATCHED)
        self.get_logger().info(f"Waiting for fleet files on {update_topic} (acks on {ack_topic})")

    def _ack(self, **fields):
        msg = String()
        msg.data = json.dumps({"robot": self.args.robot_ns, **fields})
        self.ack_pub.publish(msg)

    def _on_update(self, msg):
        try:
            update = json.loads(msg.data)
        except json.JSONDecodeError as exc:
            self.get_logger().error(f"bad update JSON: {exc}")
            return
        kind, version = update.get("kind"), update.get("version")
        key = (kind, version)
        if key in self._seen:  # latched re-delivery of an update already applied
            self._ack(kind=kind, version=version, ok=True, written=[], duplicate=True, error=None)
            return
        try:
            result = apply_update(
                update,
                graph_path=self.args.graph_path,
                map_dir=self.args.map_dir,
                keep_backup=not self.args.no_backup,
            )
        except (FleetFileError, OSError) as exc:
            self.get_logger().error(f"{kind} {version} rejected: {exc}")
            self._ack(kind=kind, version=version, ok=False, written=[], error=str(exc))
            return

        self._seen.add(key)
        self.get_logger().info(f"{kind} {version} written: {', '.join(result['written'])}")
        error = None
        if self.args.on_update:
            completed = subprocess.run(
                self.args.on_update,
                shell=True,
                env={**os.environ, "FLEET_FILE_KIND": str(kind)},
                capture_output=True,
                text=True,
                timeout=120,
            )
            if completed.returncode != 0:
                error = f"files written, but --on-update failed: {completed.stderr.strip()[:300]}"
                self.get_logger().error(error)
        self._ack(kind=kind, version=version, ok=error is None, error=error, **result)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--robot-ns", required=True, help="this robot's namespace, e.g. robot1")
    parser.add_argument("--graph-path", help="graph JSON file to overwrite")
    parser.add_argument("--map-dir", help="directory for the map yaml + image")
    parser.add_argument("--on-update", help="shell command to run after a successful update")
    parser.add_argument("--topics-config", help="optional copy of fleet_topics.yaml")
    parser.add_argument("--robot-type", help="robot type in fleet_topics.yaml (default: its default)")
    parser.add_argument("--no-backup", action="store_true", help="don't keep *.bak copies")
    args = parser.parse_args()
    if not args.graph_path and not args.map_dir:
        parser.error("give --graph-path and/or --map-dir")

    rclpy.init()
    node = Receiver(args)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
