#include <memory>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/camera_info.hpp"
#include "sensor_msgs/msg/image.hpp"

// Placeholder for a libfreenect bringup on the CM4. libfreenect is not linked.
// The user-supplied Kinect model string is "1505"; which Kinect generation
// that names is unset, so this node does not pick freenect versus freenect2.

class KinectFreenectNode : public rclcpp::Node {
 public:
  KinectFreenectNode() : Node("kinect_freenect") {
    image_pub_ = create_publisher<sensor_msgs::msg::Image>("kinect/image_raw", 10);
    depth_pub_ = create_publisher<sensor_msgs::msg::Image>("kinect/depth", 10);
    info_pub_ =
        create_publisher<sensor_msgs::msg::CameraInfo>("kinect/camera_info", 10);

    RCLCPP_WARN(
        get_logger(),
        "Kinect placeholder. libfreenect is not linked, so %s, %s, and %s "
        "will not publish frames. User-supplied model string: 1505.",
        image_pub_->get_topic_name(), depth_pub_->get_topic_name(),
        info_pub_->get_topic_name());
  }

 private:
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr image_pub_;
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr depth_pub_;
  rclcpp::Publisher<sensor_msgs::msg::CameraInfo>::SharedPtr info_pub_;
};

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<KinectFreenectNode>());
  rclcpp::shutdown();
  return 0;
}
