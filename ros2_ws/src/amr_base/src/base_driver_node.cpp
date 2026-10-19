// ESP32 serial bridge for the CM4.
//
// cmd_vel is mixed into per-wheel DRIVE lines. Encoder ticks on ENC become
// odom and a tf from odom to base_link. Geometry numbers default to the
// placeholders in cm4/server/calibration.py. They are not measurements.
//
// Do not run this node at the same time as cm4/server. Both open the UART.
// TransformBroadcaster(node) matches Humble and newer. Passing
// shared_from_this() from this constructor is not safe.
// This file was not colcon-built in the environment that added it.

#include <chrono>
#include <cmath>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include <cerrno>
#include <fcntl.h>
#include <termios.h>
#include <unistd.h>

#include "geometry_msgs/msg/transform_stamped.hpp"
#include "geometry_msgs/msg/twist.hpp"
#include "nav_msgs/msg/odometry.hpp"
#include "rclcpp/rclcpp.hpp"
#include "tf2_ros/transform_broadcaster.h"

namespace {

constexpr int kWheelMin = -255;
constexpr int kWheelMax = 255;

int clampPwm(int value) {
  if (value < kWheelMin) {
    return kWheelMin;
  }
  if (value > kWheelMax) {
    return kWheelMax;
  }
  return value;
}

class SerialLink {
 public:
  ~SerialLink() { close(); }

  bool open(const std::string & path) {
    close();
    fd_ = ::open(path.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (fd_ < 0) {
      return false;
    }
    termios tty {};
    if (tcgetattr(fd_, &tty) != 0) {
      close();
      return false;
    }
    cfmakeraw(&tty);
    cfsetispeed(&tty, B115200);
    cfsetospeed(&tty, B115200);
    tty.c_cflag |= (CLOCAL | CREAD);
    tty.c_cflag &= ~CRTSCTS;
    tty.c_cc[VMIN] = 0;
    tty.c_cc[VTIME] = 0;
    if (tcsetattr(fd_, TCSANOW, &tty) != 0) {
      close();
      return false;
    }
    return true;
  }

  void close() {
    if (fd_ >= 0) {
      ::close(fd_);
      fd_ = -1;
    }
  }

  bool ok() const { return fd_ >= 0; }

  bool writeLine(const std::string & line) {
    if (fd_ < 0) {
      return false;
    }
    const std::string payload = line + "\n";
    const char * data = payload.data();
    size_t left = payload.size();
    while (left > 0) {
      const ssize_t wrote = ::write(fd_, data, left);
      if (wrote < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
          return false;
        }
        return false;
      }
      data += wrote;
      left -= static_cast<size_t>(wrote);
    }
    return true;
  }

  std::vector<std::string> readLines() {
    std::vector<std::string> lines;
    if (fd_ < 0) {
      return lines;
    }
    char chunk[256];
    while (true) {
      const ssize_t got = ::read(fd_, chunk, sizeof chunk);
      if (got < 0) {
        break;
      }
      if (got == 0) {
        break;
      }
      buffer_.append(chunk, static_cast<size_t>(got));
    }
    while (true) {
      const auto cut = buffer_.find('\n');
      if (cut == std::string::npos) {
        break;
      }
      std::string line = buffer_.substr(0, cut);
      buffer_.erase(0, cut + 1);
      if (!line.empty() && line.back() == '\r') {
        line.pop_back();
      }
      if (!line.empty()) {
        lines.push_back(line);
      }
    }
    if (buffer_.size() > 1024) {
      buffer_.clear();
    }
    return lines;
  }

 private:
  int fd_{-1};
  std::string buffer_;
};

}  // namespace

class BaseDriverNode : public rclcpp::Node {
 public:
  BaseDriverNode() : Node("base_driver") {
    port_ = declare_parameter<std::string>("serial_port", "/dev/ttyAMA0");
    declare_parameter<int>("baud", 115200);
    // CALIBRATE. Same placeholders as cm4/server/calibration.py.
    wheel_diameter_m_ = declare_parameter<double>("wheel_diameter_m", 0.065);
    track_width_m_ = declare_parameter<double>("track_width_m", 0.20);
    ticks_per_rev_ = declare_parameter<double>("ticks_per_rev", 360.0);
    left_sign_ = declare_parameter<int>("left_tick_sign", 1);
    right_sign_ = declare_parameter<int>("right_tick_sign", 1);
    pwm_per_mps_ = declare_parameter<double>("pwm_per_mps", 400.0);
    geometry_calibrated_ = declare_parameter<bool>("geometry_calibrated", false);
    cmd_timeout_s_ = declare_parameter<double>("cmd_timeout_s", 0.3);
    drive_repeat_s_ = declare_parameter<double>("drive_repeat_s", 0.2);
    odom_frame_ = declare_parameter<std::string>("odom_frame", "odom");
    base_frame_ = declare_parameter<std::string>("base_frame", "base_link");

    cmd_sub_ = create_subscription<geometry_msgs::msg::Twist>(
        "cmd_vel", 10,
        [this](const geometry_msgs::msg::Twist::SharedPtr msg) { onCmd(msg); });
    odom_pub_ = create_publisher<nav_msgs::msg::Odometry>("odom", 10);
    tf_broadcaster_ = std::make_unique<tf2_ros::TransformBroadcaster>(this);

    timer_ = create_wall_timer(
        std::chrono::milliseconds(50), [this]() { onTimer(); });

    if (!geometry_calibrated_) {
      RCLCPP_WARN(
          get_logger(),
          "Wheel diameter %.3f m, track %.3f m, ticks/rev %.1f, pwm/mps %.1f "
          "are placeholders. Set geometry_calibrated after measuring them.",
          wheel_diameter_m_, track_width_m_, ticks_per_rev_, pwm_per_mps_);
    }
    RCLCPP_INFO(
        get_logger(),
        "Base driver will open %s at 115200. Stop cm4/server before this node.",
        port_.c_str());
  }

 private:
  void onCmd(const geometry_msgs::msg::Twist::SharedPtr & msg) {
    linear_x_ = msg->linear.x;
    angular_z_ = msg->angular.z;
    last_cmd_ = now();
    have_cmd_ = true;
  }

  void onTimer() {
    ensureOpen();
    if (!serial_.ok()) {
      return;
    }
    for (const std::string & line : serial_.readLines()) {
      handleLine(line);
    }
    publishOdom();
    sendDrive();
  }

  void ensureOpen() {
    if (serial_.ok()) {
      return;
    }
    const rclcpp::Time stamp = now();
    if ((stamp - last_open_try_).seconds() < 1.0 && last_open_try_.nanoseconds() != 0) {
      return;
    }
    last_open_try_ = stamp;
    if (!serial_.open(port_)) {
      RCLCPP_WARN_THROTTLE(
          get_logger(), *get_clock(), 5000,
          "Could not open %s. The CM4 UART device node is still a placeholder.",
          port_.c_str());
      return;
    }
    serial_.writeLine("TELEM 1");
    RCLCPP_INFO(get_logger(), "Opened %s and sent TELEM 1", port_.c_str());
  }

  void handleLine(const std::string & line) {
    if (line.rfind("ENC ", 0) != 0) {
      if (line.rfind("ERR", 0) == 0) {
        RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000, "%s", line.c_str());
      }
      return;
    }
    long left = 0;
    long right = 0;
    int batt_mv = 0;
    const int fields = std::sscanf(line.c_str(), "ENC %ld %ld %d", &left, &right, &batt_mv);
    if (fields < 2) {
      return;
    }
    if (fields >= 3 && batt_mv != batt_mv_) {
      batt_mv_ = batt_mv;
      // Firmware millivolts already include the divider ratio. Ratio 1.0 is pin volts.
      RCLCPP_INFO(get_logger(), "battery field %d mV (uncalibrated unless the divider ratio was set)", batt_mv_);
    }
    integrate(static_cast<int64_t>(left), static_cast<int64_t>(right));
  }

  void integrate(int64_t left_ticks, int64_t right_ticks) {
    if (!have_ticks_) {
      prev_left_ = left_ticks;
      prev_right_ = right_ticks;
      have_ticks_ = true;
      return;
    }
    if (ticks_per_rev_ == 0.0 || track_width_m_ == 0.0) {
      prev_left_ = left_ticks;
      prev_right_ = right_ticks;
      return;
    }
    const double circumference = M_PI * wheel_diameter_m_;
    const double left_m =
        static_cast<double>(left_ticks - prev_left_) * left_sign_ /
        ticks_per_rev_ * circumference;
    const double right_m =
        static_cast<double>(right_ticks - prev_right_) * right_sign_ /
        ticks_per_rev_ * circumference;
    prev_left_ = left_ticks;
    prev_right_ = right_ticks;
    const double center = (left_m + right_m) / 2.0;
    const double delta_theta = (right_m - left_m) / track_width_m_;
    const double mid = theta_ + delta_theta / 2.0;
    x_ += center * std::cos(mid);
    y_ += center * std::sin(mid);
    theta_ += delta_theta;
  }

  void publishOdom() {
    if (!have_ticks_) {
      return;
    }
    const rclcpp::Time stamp = now();
    geometry_msgs::msg::Quaternion q;
    q.z = std::sin(theta_ / 2.0);
    q.w = std::cos(theta_ / 2.0);

    nav_msgs::msg::Odometry odom;
    odom.header.stamp = stamp;
    odom.header.frame_id = odom_frame_;
    odom.child_frame_id = base_frame_;
    odom.pose.pose.position.x = x_;
    odom.pose.pose.position.y = y_;
    odom.pose.pose.orientation = q;
    odom_pub_->publish(odom);

    geometry_msgs::msg::TransformStamped tf;
    tf.header.stamp = stamp;
    tf.header.frame_id = odom_frame_;
    tf.child_frame_id = base_frame_;
    tf.transform.translation.x = x_;
    tf.transform.translation.y = y_;
    tf.transform.rotation = q;
    tf_broadcaster_->sendTransform(tf);
  }

  void sendDrive() {
    const bool fresh = have_cmd_ && (now() - last_cmd_).seconds() <= cmd_timeout_s_;
    if (!fresh) {
      if (motors_on_) {
        serial_.writeLine("STOP");
        motors_on_ = false;
        sent_left_ = 0;
        sent_right_ = 0;
      }
      return;
    }
    const double half = track_width_m_ / 2.0;
    const double v_left = linear_x_ - angular_z_ * half;
    const double v_right = linear_x_ + angular_z_ * half;
    const int left = clampPwm(static_cast<int>(std::lround(v_left * pwm_per_mps_)));
    const int right = clampPwm(static_cast<int>(std::lround(v_right * pwm_per_mps_)));
    if (left == 0 && right == 0) {
      if (motors_on_) {
        serial_.writeLine("STOP");
        motors_on_ = false;
        sent_left_ = 0;
        sent_right_ = 0;
      }
      return;
    }
    const bool due = (now() - last_drive_send_).seconds() >= drive_repeat_s_;
    if (!due && left == sent_left_ && right == sent_right_) {
      return;
    }
    serial_.writeLine("DRIVE " + std::to_string(left) + " " + std::to_string(right));
    motors_on_ = true;
    sent_left_ = left;
    sent_right_ = right;
    last_drive_send_ = now();
  }

  rclcpp::Time now() { return get_clock()->now(); }

  std::string port_;
  double wheel_diameter_m_{0.065};
  double track_width_m_{0.20};
  double ticks_per_rev_{360.0};
  int left_sign_{1};
  int right_sign_{1};
  double pwm_per_mps_{400.0};
  bool geometry_calibrated_{false};
  double cmd_timeout_s_{0.3};
  double drive_repeat_s_{0.2};
  std::string odom_frame_;
  std::string base_frame_;

  double linear_x_{0.0};
  double angular_z_{0.0};
  rclcpp::Time last_cmd_{0, 0, RCL_ROS_TIME};
  rclcpp::Time last_drive_send_{0, 0, RCL_ROS_TIME};
  rclcpp::Time last_open_try_{0, 0, RCL_ROS_TIME};
  bool have_cmd_{false};
  bool motors_on_{false};
  int sent_left_{0};
  int sent_right_{0};

  bool have_ticks_{false};
  int64_t prev_left_{0};
  int64_t prev_right_{0};
  int batt_mv_{0};
  double x_{0.0};
  double y_{0.0};
  double theta_{0.0};

  SerialLink serial_;
  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr cmd_sub_;
  rclcpp::Publisher<nav_msgs::msg::Odometry>::SharedPtr odom_pub_;
  std::unique_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster_;
  rclcpp::TimerBase::SharedPtr timer_;
};

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<BaseDriverNode>());
  rclcpp::shutdown();
  return 0;
}
