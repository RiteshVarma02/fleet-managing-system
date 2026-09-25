#!/usr/bin/env python3
"""
Robot action forwarder for cross-domain navigation (UPDATED VERSION).
Run this on the robot domain (domain 2 or 3) to forward goals.

IMPROVEMENTS:
- Better feedback messages with timestamps
- Intermediate status updates (IN_PROGRESS)
- Better error handling and logging
- Proper callback sequencing
"""

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from nav2_msgs.action import NavigateToPose
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import Bool, String
from action_msgs.msg import GoalStatus
import os
import time


class RobotStatus:
    """Standardized robot navigation statuses."""
    PENDING = GoalStatus.STATUS_ACCEPTED
    IN_PROGRESS = GoalStatus.STATUS_EXECUTING
    ACCEPTED = GoalStatus.STATUS_ACCEPTED
    COMPLETED = GoalStatus.STATUS_SUCCEEDED
    CANCELED = GoalStatus.STATUS_CANCELED
    FAILED = GoalStatus.STATUS_ABORTED


STATUS_STRING_TO_CODE: dict[str, int] = {
    'READY': RobotStatus.PENDING,
    'SENDING_GOAL': RobotStatus.PENDING,
    'IN_PROGRESS': RobotStatus.IN_PROGRESS,
    'ACCEPTED': RobotStatus.ACCEPTED,
    'COMPLETED': RobotStatus.COMPLETED,
    'CANCELED': RobotStatus.CANCELED,
    'FAILED': RobotStatus.FAILED,
    'ERROR': RobotStatus.FAILED,
}


def _convert_status_to_code(status: str) -> int:
    """Convert raw status string to GoalStatus int code."""
    return STATUS_STRING_TO_CODE.get(status.upper(), GoalStatus.STATUS_UNKNOWN)


class RobotActionForwarder(Node):
    def __init__(
        self,
        robot_id="robot_1",
        robot_domain=2,
        goal_topic="/goal_request",
        status_topic="/navigation_status",
        cancel_topic="/goal_cancel"
    ):
        super().__init__('robot_action_forwarder')
        
        self.robot_id = robot_id
        self.robot_domain = robot_domain
        self.goal_topic = goal_topic
        self.status_topic = status_topic
        self.callback_group = ReentrantCallbackGroup()
        
        # Track current goal
        self.current_goal_handle = None
        self.goal_start_time = None
        self._last_feedback_second = -1
        
        # Action client to the local robot action server
        self.navigate_client = ActionClient(
            self, 
            NavigateToPose, 
            '/navigate_to_pose',
            callback_group=self.callback_group
        )
        
        # Topic subscriber for goal requests from server
        # Note: domain_bridge should remap /robot_X/goal_request -> /goal_request on robot domain
        self.goal_sub = self.create_subscription(
            PoseStamped,
            self.goal_topic,
            self.goal_callback,
            10,
            callback_group=self.callback_group
        )

        # Topic subscriber for cancel requests from server.
        # The server publishes Bool(True) on /robot_X/goal_cancel which the
        # domain bridge remaps to /goal_cancel here. Without this subscription
        # operator cancels never reach Nav2 and the robot keeps driving.
        self.cancel_sub = self.create_subscription(
            Bool,
            cancel_topic,
            self.cancel_callback,
            10,
            callback_group=self.callback_group
        )
        
        # Topic publisher for feedback/results
        # Note: domain_bridge should remap /navigation_status -> /robot_X/navigation_status on server domain
        self.status_pub = self.create_publisher(
            String,
            self.status_topic,
            10
        )
        
        self.get_logger().info(
            f'✓ Initialized forwarder for {robot_id} (domain {robot_domain})\n'
            f'  goal_topic={self.goal_topic}\n'
            f'  status_topic={self.status_topic}'
        )
        self._publish_status_with_code(GoalStatus.STATUS_UNKNOWN)

    def _publish_status_with_code(self, status_code: GoalStatus):
        """Publish status with proper GoalStatus code (for downstream enum access)."""
        
        # Create human-readable message
        status_msg = String()
        # Map numeric code to readable message using correct integer values
        status_dict = {
            GoalStatus.STATUS_UNKNOWN: 'UNKNOWN',
            GoalStatus.STATUS_ACCEPTED: 'ACCEPTED',
            GoalStatus.STATUS_EXECUTING: 'IN_PROGRESS',
            GoalStatus.STATUS_SUCCEEDED: 'COMPLETED',
            GoalStatus.STATUS_CANCELED: 'CANCELLED',
            GoalStatus.STATUS_ABORTED: 'FAILED',
        }

        text_status = status_dict.get(status_code, f'STATUS_{status_code}')
        
        msg_data = f'[{self.robot_id}] {text_status}'
        status_msg.data = msg_data
        
        self.status_pub.publish(status_msg)
        self.get_logger().info(f'📤 STATUS CODE: {status_code} → {msg_data}')

    def _publish_status(self, status_str: str, message=None):
        """Helper to publish status messages with optional custom text"""
        if message:
            msg_data = f'[{self.robot_id}] {status_str}: {message}'
        else:
            msg_data = f'[{self.robot_id}] {status_str}'
        
        status_msg = String()
        status_msg.data = msg_data
        self.status_pub.publish(status_msg)
        self.get_logger().info(f'📤 STATUS: {msg_data}')

    def _publish_status_with_code(self, status_code: GoalStatus):
        """Helper to publish status using internal action code"""
        # Map internal status codes to user-friendly status strings
        status_map = {
            GoalStatus.STATUS_UNKNOWN: 'UNKNOWN',
            GoalStatus.STATUS_ACCEPTED: 'ACCEPTED',
            GoalStatus.STATUS_EXECUTING: 'EXECUTING',
            GoalStatus.STATUS_SUCCEEDED: 'SUCCEEDED',
            GoalStatus.STATUS_CANCELED: 'CANCELED',
            GoalStatus.STATUS_ABORTED: 'ABORTED'
        }
        
        status_str = status_map.get(status_code, f'STATUS_{status_code}')
        self._publish_status(status_str)

    def cancel_callback(self, msg: Bool):
        """Cancel the active NavigateToPose goal (server-driven pause/cancel)."""
        if not msg.data:
            return
        if self.current_goal_handle is None:
            self.get_logger().info('📥 CANCEL received but no active goal')
            return
        self.get_logger().info('📥 CANCEL received — cancelling active Nav2 goal')
        self._publish_status_with_code(GoalStatus.STATUS_CANCELED)
        try:
            cancel_future = self.current_goal_handle.cancel_goal_async()
            # The result callback publishes the terminal CANCELLED status once
            # Nav2 confirms; do not block this callback on it.
            cancel_future.add_done_callback(self._cancel_response_callback)
        except Exception as e:
            self.get_logger().error(f'✗ Cancel failed: {e}')
            self._publish_status_with_code(GoalStatus.STATUS_ABORTED.value)

    def _cancel_response_callback(self, future):
        try:
            response = future.result()
            accepted = getattr(response, 'return_code', None) == 0
            self.get_logger().info(
                f'✓ Cancel request {"accepted" if accepted else "rejected"} by nav2'
            )
        except Exception as e:
            self.get_logger().error(f'✗ Cancel response error: {e}')

    def goal_callback(self, msg: PoseStamped):
        """Callback when server sends a goal via topic"""
        self.get_logger().info(
            f'📥 GOAL RECEIVED: x={msg.pose.position.x:.2f}, '
            f'y={msg.pose.position.y:.2f}, z={msg.pose.position.z:.2f}'
        )
        
        # Cancel previous goal if exists
        if self.current_goal_handle is not None:
            self.get_logger().warn('⚠️  Cancelling previous goal...')
            try:
                cancel_future = self.current_goal_handle.cancel_goal_async()
                cancel_future.result(timeout_sec=1.0)
            except Exception as e:
                self.get_logger().warn(f'Could not cancel previous goal: {e}')
        
        self.send_nav_goal(msg)

    def send_nav_goal(self, pose_msg: PoseStamped):
        """Send navigation goal to the robot's action server"""
        
        # Wait for action server
        self.get_logger().info('⏳ Waiting for nav2 action server...')
        if not self.navigate_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error('✗ navigate_to_pose action server NOT available!')
            self._publish_status('ERROR', 'Nav2 action server unavailable')
            return False
        
        self.get_logger().info('✓ Nav2 action server available')
        self._publish_status_with_code(GoalStatus.STATUS_UNKNOWN)
        
        # Create goal
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = pose_msg
        
        self.goal_start_time = time.time()
        self._last_feedback_second = -1
        
        # Send goal and attach callbacks
        self.get_logger().info(f'🎯 Sending goal to nav2...')
        future = self.navigate_client.send_goal_async(
            goal_msg,
            feedback_callback=self.feedback_callback
        )
        future.add_done_callback(self.goal_response_callback)
        return True

    def feedback_callback(self, feedback_msg):
        """Handle navigation feedback (called periodically during navigation).

        Throttled to one status per second — Nav2 emits feedback far more often
        and every message crosses the domain bridge.
        """
        try:
            elapsed = time.time() - self.goal_start_time
            self.get_logger().debug(f'⚙️  Feedback at {elapsed:.1f}s')

            whole_second = int(elapsed)
            if elapsed > 1.0 and whole_second != self._last_feedback_second:
                self._last_feedback_second = whole_second
                self._publish_status_with_code(GoalStatus.STATUS_EXECUTING)
        except Exception as e:
            self.get_logger().debug(f'Feedback error: {e}')

    def goal_response_callback(self, future):
        """Handle goal acceptance/rejection"""
        try:
            goal_handle = future.result()
        except Exception as e:
            self.get_logger().error(f'✗ Failed to send goal: {e}')
            self._publish_status_with_code(GoalStatus.STATUS_REJECTED)
            return

        if not goal_handle or not goal_handle.accepted:
            self.get_logger().warning('✗ Goal rejected by nav2')
            self._publish_status_with_code(GoalStatus.STATUS_REJECTED)
            self.current_goal_handle = None
            return
        
        self.current_goal_handle = goal_handle
        self.get_logger().info('✓ Goal accepted by nav2')
        self._publish_status_with_code(GoalStatus.STATUS_UNKNOWN)
        
        # Wait for result
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.get_result_callback)

    def get_result_callback(self, future):
        """Handle navigation result — MUST branch on the real goal status code.

        rclpy resolves get_result_async() to a response carrying `.status`
        (action_msgs GoalStatus int) and `.result` (the Result message, which
        is always truthy!). Branching on `.result` truthiness reported
        COMPLETED for cancelled and aborted goals too, which made the fleet
        server believe unreachable drops were reached.
        """
        try:
            response = future.result()
            elapsed = time.time() - self.goal_start_time

            status_code = getattr(response, "status", None)
            # action_msgs/msg/GoalStatus: 4=SUCCEEDED, 5=CANCELED, 6=ABORTED
            if status_code == 4:
                self.get_logger().info(f'✓ Navigation succeeded in {elapsed:.1f}s')
                self._publish_status_with_code(GoalStatus.STATUS_SUCCEEDED)
            elif status_code == 5:
                self.get_logger().warning(f'Goal cancelled after {elapsed:.1f}s')
                self._publish_status_with_code(GoalStatus.STATUS_CANCELED)
            elif status_code == 6:
                self.get_logger().error(f'✗ Goal aborted after {elapsed:.1f}s')
                self._publish_status_with_code(GoalStatus.STATUS_ABORTED)
            else:
                self.get_logger().error(f'✗ Goal ended with unknown status {status_code}')
                self._publish_status_with_code(GoalStatus.STATUS_ABORTED)

        except Exception as e:
            elapsed = time.time() - self.goal_start_time
            self.get_logger().error(f'✗ Navigation failed after {elapsed:.1f}s: {e}')
            self._publish_status('FAILED', f'Exception: {str(e)[:50]}')
        finally:
            self.current_goal_handle = None

def main(args=None):
    # Read robot ID and domain from environment or args
    robot_id = os.getenv('ROBOT_ID', 'robot_11')
    robot_domain = int(os.getenv('ROS_DOMAIN_ID', '3'))
    goal_topic = os.getenv('FORWARDER_GOAL_TOPIC', '/goal_request')
    status_topic = os.getenv('FORWARDER_STATUS_TOPIC', '/navigation_status')
    cancel_topic = os.getenv('FORWARDER_CANCEL_TOPIC', '/goal_cancel')
    
    rclpy.init(args=args)
    
    forwarder = RobotActionForwarder(
        robot_id=robot_id,
        robot_domain=robot_domain,
        goal_topic=goal_topic,
        status_topic=status_topic,
        cancel_topic=cancel_topic
    )
    
    executor = MultiThreadedExecutor()
    executor.add_node(forwarder)
    
    forwarder.get_logger().info(
        f'\n{"="*70}\n'
        f'🚀 Robot Action Forwarder Started\n'
        f'  Robot: {robot_id} | Domain: {robot_domain}\n'
        f'  Waiting for goals on {goal_topic} topic...\n'
        f'{"="*70}\n'
    )
    
    try:
        executor.spin()
    except KeyboardInterrupt:
        forwarder.get_logger().info('\n⛔ Shutting down...')
    finally:
        executor.shutdown()
        rclpy.shutdown()
        forwarder.get_logger().info('✓ Shutdown complete')


if __name__ == '__main__':
    main()
