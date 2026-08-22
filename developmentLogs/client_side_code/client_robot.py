#!/usr/bin/env python3
"""
Robot Registration Client Node

This node runs before robot startup to:
1. Check if robot_id is already assigned (stored locally)
2. If not, request one from the server by publishing MAC address
3. Listen for approval/assignment response
4. Store the robot_id persistently
5. Exit when robot_id is confirmed, allowing main robot to start

Usage:
    ros2 run swarm_controller robot_registration_client.py
    # or directly:
    python3 robot_registration_client.py

Environment Variables (optional, can be set in a .env file placed next to this script):
    ROBOT_REGISTRATION_CONFIG: Path to config file (default: ~/.robot_config)
    ROBOT_MAC_ADDRESS: Override MAC address (default: auto-detected from network interfaces)
    ROBOT_HOSTNAME: Override hostname (default: from socket.gethostname())
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import json
import socket
import os
import time
from pathlib import Path
import subprocess


class RobotRegistrationClient(Node):
    """Client node for requesting and storing robot registration."""

    def __init__(self):
        super().__init__('robot_registration_client')
        
        # Configuration
        self.config_path = Path(
            os.getenv('ROBOT_REGISTRATION_CONFIG', 
                      f'/home/{os.getenv("USER", "robot")}/.robot_config')
        )
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.robot_id = None
        self.mac_address = self._get_mac_address()
        self.hostname = os.getenv('ROBOT_HOSTNAME', socket.gethostname())
        self.ip_address = self._get_ip_address()
        
        self.get_logger().info(f'Robot Registration Client Started')
        self.get_logger().info(f'  MAC: {self.mac_address}')
        self.get_logger().info(f'  Hostname: {self.hostname}')
        self.get_logger().info(f'  IP: {self.ip_address}')
        
        # Try to load existing robot_id
        if self._load_robot_id():
            self.get_logger().info(f'✓ Loaded stored robot_id: {self.robot_id}')
            self._exit_success()
            return
        
        self.get_logger().info('⏳ No stored robot_id found. Requesting from server...')
        
        # Publisher for registration requests
        self.register_pub = self.create_publisher(String, '/robot/register', 10)
        
        # Subscriber for registration responses
        self.response_sub = self.create_subscription(
            String,
            '/robot/register/response',
            self.response_callback,
            10
        )
        
        # Retry logic
        self.registration_attempts = 0
        self.max_attempts = 5
        self.attempt_interval = 3.0  # seconds
        
        # Publish registration request
        self._publish_registration_request()
        
        # Timer to retry if no response
        self.create_timer(self.attempt_interval, self._retry_registration)

    def _get_mac_address(self) -> str:
        """Get MAC address from environment override or auto-detect from all network interfaces."""
        # Check for manual override first (env var or .env file)
        mac = os.getenv('ROBOT_MAC_ADDRESS')
        if mac:
            self.get_logger().info(f'Using MAC from ROBOT_MAC_ADDRESS override: {mac.strip().upper()}')
            return mac.strip().upper()

        # Enumerate all interfaces under /sys/class/net/ dynamically
        net_path = Path('/sys/class/net')
        try:
            # Sort for consistent ordering (eth0 before eth1, wlan0 before wlan1, etc.)
            for iface_path in sorted(net_path.iterdir()):
                iface_name = iface_path.name

                # Skip loopback and known virtual/bridge interfaces
                if iface_name == 'lo' or iface_name.startswith(
                    ('docker', 'br-', 'veth', 'virbr', 'vmnet', 'tun', 'tap')
                ):
                    continue

                addr_file = iface_path / 'address'
                type_file = iface_path / 'type'

                if not addr_file.exists():
                    continue

                try:
                    # Interface type 1 = ARPHRD_ETHER (real Ethernet or Wi-Fi)
                    if type_file.exists() and int(type_file.read_text().strip()) != 1:
                        continue

                    mac = addr_file.read_text().strip().upper()
                    if mac and mac != '00:00:00:00:00:00':
                        self.get_logger().info(
                            f'Using MAC from interface [{iface_name}]: {mac}'
                        )
                        return mac
                except Exception:
                    continue
        except Exception as e:
            self.get_logger().warn(f'Error enumerating network interfaces: {e}')

        # No valid interface found — require manual override
        self.get_logger().error(
            'Could not read a real MAC address from any network interface!\n'
            '  → Set ROBOT_MAC_ADDRESS=XX:XX:XX:XX:XX:XX in your .env file or environment.'
        )
        raise RuntimeError(
            'Cannot determine MAC address. '
            'Please set ROBOT_MAC_ADDRESS=XX:XX:XX:XX:XX:XX in your .env file.'
        )

    def _get_ip_address(self) -> str:
        """Get primary IP address."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return '127.0.0.1'

    def _load_robot_id(self) -> bool:
        """Load stored robot_id from config file."""
        if not self.config_path.exists():
            return False
        
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
                self.robot_id = config.get('robot_id')
                if self.robot_id:
                    return True
        except Exception as e:
            self.get_logger().warn(f'Failed to load config: {e}')
        
        return False

    def _save_robot_id(self):
        """Save robot_id to config file."""
        try:
            config = {'robot_id': self.robot_id, 'timestamp': time.time()}
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)
            self.get_logger().info(f'✓ Saved robot_id to {self.config_path}')
        except Exception as e:
            self.get_logger().error(f'Failed to save config: {e}')

    def _publish_registration_request(self):
        """Publish registration request."""
        payload = {
            'mac_address': self.mac_address,
            'hostname': self.hostname,
            'ip_address': self.ip_address
        }
        msg = String(data=json.dumps(payload))
        self.register_pub.publish(msg)
        self.registration_attempts += 1
        self.get_logger().info(
            f'Published registration request (attempt {self.registration_attempts}/{self.max_attempts})'
        )

    def _retry_registration(self):
        """Retry registration indefinitely until approved by the operator."""
        if self.robot_id is not None:
            return

        # Every max_attempts iterations print a prominent reminder
        if self.registration_attempts > 0 and self.registration_attempts % self.max_attempts == 0:
            self.get_logger().warn(
                f'⏳ Still waiting for operator approval after '
                f'{self.registration_attempts} attempts. '
                'Robot will keep retrying — do NOT kill this process.'
            )

        self.get_logger().info(
            f'Retrying registration request (attempt {self.registration_attempts + 1})...'
        )
        self._publish_registration_request()

    def response_callback(self, msg: String):
        """Handle registration response from server."""
        try:
            data = json.loads(msg.data)
            status = data.get('status')
            
            if status == 'approved':
                self.robot_id = data.get('robot_id')
                self.get_logger().info(f'✓ APPROVED! Assigned robot_id: {self.robot_id}')
                self._save_robot_id()
                self._exit_success()
            
            elif status == 'pending':
                self.get_logger().info(f'⏳ PENDING: Waiting for operator approval...')
        
        except Exception as e:
            self.get_logger().error(f'Error processing response: {e}')

    def _exit_success(self):
        """Exit successfully with robot_id available."""
        self.get_logger().info('')
        self.get_logger().info('=' * 60)
        self.get_logger().info(f'✓ Robot Registration Complete!')
        self.get_logger().info(f'  Robot ID: {self.robot_id}')
        self.get_logger().info(f'  Config saved to: {self.config_path}')
        self.get_logger().info('=' * 60)
        
        os.environ['ROBOT_ID'] = self.robot_id
        time.sleep(1)
        rclpy.shutdown()


def _load_env_file():
    """
    Load a .env file from the same directory as this script.

    Each line should be:  KEY=VALUE
    Lines starting with # are treated as comments.
    Values wrapped in single or double quotes are automatically stripped.
    Existing OS environment variables are NOT overridden.

    Example .env file location:
        /home/<user>/FMS_Codes/.env   (same folder as client_robot.py)
    """
    env_file = Path(__file__).parent / '.env'
    if not env_file.exists():
        return
    print(f'[env] Loading environment from: {env_file}')
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:   # never override real env vars
                os.environ[key] = value
                print(f'[env]   {key} = {value}')


def main(args=None):
    _load_env_file()          # load .env before anything else
    rclpy.init(args=args)
    node = RobotRegistrationClient()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
