#include <memory>
#include <string>

#include "geometry_msgs/msg/twist.hpp"
#include "nav_msgs/msg/odometry.hpp"
#include "rclcpp/rclcpp.hpp"

// Placeholder bridge. The serial protocol is documented in
// docs/serial-protocol.md. Wheel mixing is omitted until wheel radius and
// track width are measured, and this node does not open a serial port.

class BaseDriverNode : public rclcpp::Node {
 public:
  BaseDriverNode() : Node("base_driver") {
    port_ = declare_parameter<std::string>("serial_port", "/dev/ttyAMA0");
    baud_ = declare_parameter<int>("baud", 115200);

    cmd_sub_ = create_subscription<geometry_msgs::msg::Twist>(
        "cmd_vel", 10,
        [this](const geometry_msgs::msg::Twist::SharedPtr msg) { onCmd(msg); });
    odom_pub_ = create_publisher<nav_msgs::msg::Odometry>("odom", 10);

    RCLCPP_WARN(
        get_logger(),
        "Placeholder base driver. serial_port=%s baud=%d is not opened. "
        "cmd_vel is logged only. odom (%s) stays silent until wheel geometry "
        "is measured.",
        port_.c_str(), baud_, odom_pub_->get_topic_name());
  }

 private:
  void onCmd(const geometry_msgs::msg::Twist::SharedPtr & msg) {
    RCLCPP_INFO_THROTTLE(
        get_logger(), *get_clock(), 1000,
        "cmd_vel linear.x=%.3f angular.z=%.3f (not sent to the ESP32)",
        msg->linear.x, msg->angular.z);
  }

  std::string port_;
  int baud_;
  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr cmd_sub_;
  rclcpp::Publisher<nav_msgs::msg::Odometry>::SharedPtr odom_pub_;
};

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<BaseDriverNode>());
  rclcpp::shutdown();
  return 0;
}
