#!/usr/bin/env python3
"""Push the waypoint graph JSON (and/or the fleet map) to ALL robots.

Run on the fleet PC with ROS 2 sourced, same ROS_DOMAIN_ID as the robots.
Every robot must be running `fleet_file_receiver.py`.

    # graph JSON to every robot that is online (auto-discovered)
    python3 push_fleet_files.py --graph ~/maps/amr_path.json

    # graph + map to specific robots
    python3 push_fleet_files.py --graph amr_path.json --map ariyan_FMS.yaml \\
        --robots robot1 robot2 kumki

Robots are discovered from live topics matching the `goal` topic in
backend/config/fleet_topics.yaml (e.g. /robot1/amr/goal). Topic names for
the update/ack come from that same file. Exit code is 0 only if every robot
acknowledged every file with a matching checksum.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fleet_file_protocol import (  # noqa: E402
    FleetFileError,
    build_graph_update,
    build_map_update,
    load_topic_templates,
    robots_from_topics,
    topic_for,
)

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "backend" / "config" / "fleet_topics.yaml"

LATCHED = QoSProfile(
    depth=1,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
)


class Pusher(Node):
    def __init__(self, templates):
        super().__init__("fleet_file_pusher")
        self.templates = templates
        self.acks = {}  # (robot, kind) -> ack dict
        self._pubs = {}
        self._subs = []

    def discover(self, wait: float):
        deadline = time.time() + wait
        robots = []
        while time.time() < deadline:
            rclpy.spin_once(self, timeout_sec=0.2)
            names = [name for name, _ in self.get_topic_names_and_types()]
            robots = robots_from_topics(self.templates["goal"], names)
        return robots

    def prepare(self, robot):
        pub = self.create_publisher(String, topic_for(self.templates["file_update"], robot), LATCHED)
        self._pubs[robot] = pub
        self._subs.append(
            self.create_subscription(
                String,
                topic_for(self.templates["file_ack"], robot),
                lambda msg, r=robot: self._on_ack(r, msg),
                10,
            )
        )

    def _on_ack(self, robot, msg):
        try:
            ack = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        self.acks[(robot, ack.get("kind"))] = ack

    def wait_for_subscriber(self, robot, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._pubs[robot].get_subscription_count() > 0:
                return True
            rclpy.spin_once(self, timeout_sec=0.1)
        return False

    def send(self, robot, update):
        msg = String()
        msg.data = json.dumps(update)
        self._pubs[robot].publish(msg)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--graph", help="waypoint graph JSON ({'waypoints': [{id, name, ...}]})")
    parser.add_argument("--map", help="map .yaml (its image file must sit next to it)")
    parser.add_argument("--robots", nargs="*", help="robot ids (default: auto-discover)")
    parser.add_argument("--topics-config", default=str(DEFAULT_CONFIG), help="fleet_topics.yaml")
    parser.add_argument("--discover-seconds", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds to wait for acks")
    args = parser.parse_args()

    if not args.graph and not args.map:
        parser.error("give --graph and/or --map")

    updates = []
    try:
        if args.graph:
            updates.append(build_graph_update(args.graph, socket.gethostname()))
        if args.map:
            updates.append(build_map_update(args.map, socket.gethostname()))
    except (FleetFileError, OSError) as exc:
        print(f"❌ {exc}")
        return 2
    for update in updates:
        sizes = ", ".join(f"{f['name']} ({len(f['data']) * 3 // 4 // 1024} KB)" for f in update["files"])
        print(f"📦 {update['kind']} {update['version']}: {sizes}")

    rclpy.init()
    node = Pusher(load_topic_templates(args.topics_config))
    try:
        robots = args.robots or node.discover(args.discover_seconds)
        if not robots:
            print("❌ no robots found (none publishing/subscribing "
                  f"{node.templates['goal'].format(robot='<robot>')}). Use --robots.")
            return 2
        print(f"🤖 robots: {', '.join(robots)}")

        for robot in robots:
            node.prepare(robot)
        reachable = []
        for robot in robots:
            if node.wait_for_subscriber(robot, 5.0):
                reachable.append(robot)
            else:
                print(f"⚠️  {robot}: no fleet_file_receiver listening on "
                      f"{topic_for(node.templates['file_update'], robot)}")

        for update in updates:
            for robot in reachable:
                node.send(robot, update)

        expected = {(robot, u["kind"]) for robot in reachable for u in updates}
        deadline = time.time() + args.timeout
        while time.time() < deadline and not expected.issubset(node.acks):
            rclpy.spin_once(node, timeout_sec=0.2)

        ok_all = len(reachable) == len(robots)
        print()
        for robot in robots:
            for update in updates:
                ack = node.acks.get((robot, update["kind"]))
                if robot not in reachable:
                    line = "not reachable"
                    ok = False
                elif ack is None:
                    line, ok = "no ack (timeout)", False
                elif not ack.get("ok"):
                    line, ok = f"FAILED: {ack.get('error')}", False
                elif ack.get("version") != update["version"]:
                    line, ok = f"acked a different version ({ack.get('version')})", False
                else:
                    line, ok = "✅ " + ", ".join(ack.get("written") or []), True
                ok_all &= ok
                print(f"  {robot:<16} {update['kind']:<6} {line}")
        print()
        print("All robots updated." if ok_all else "Some robots were NOT updated.")
        return 0 if ok_all else 1
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    sys.exit(main())
