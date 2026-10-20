// Kinect bridge. Compiled against libfreenect only when the headers and
// library are found (AMR_HAS_FREENECT). Otherwise the node advertises the
// topics and exits the camera loop with a warning.
//
// Model 1414 is the original Xbox 360 Kinect (v1), which libfreenect targets.
// Camera intrinsics are left unset: K and D are zeros,
// not a nominal Kinect focal length.
// This file was not colcon-built in the environment that added it.

#include <cstdint>
#include <cstring>
#include <memory>
#include <string>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/camera_info.hpp"
#include "sensor_msgs/msg/image.hpp"

#ifdef AMR_HAS_FREENECT
#include "libfreenect/libfreenect.h"
#endif

namespace {

constexpr int kWidth = 640;
constexpr int kHeight = 480;

sensor_msgs::msg::CameraInfo blankInfo(const std::string & frame) {
  sensor_msgs::msg::CameraInfo info;
  info.header.frame_id = frame;
  info.width = kWidth;
  info.height = kHeight;
  // Intrinsics are unknown for this robot. Do not invent a focal length.
  info.k = {0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0};
  info.d = {0.0, 0.0, 0.0, 0.0, 0.0};
  info.r = {1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0};
  info.p = {0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0};
  info.distortion_model = "plumb_bob";
  return info;
}

}  // namespace

class KinectFreenectNode : public rclcpp::Node {
 public:
  KinectFreenectNode() : Node("kinect_freenect") {
    frame_ = declare_parameter<std::string>("frame_id", "kinect_link");
    image_pub_ = create_publisher<sensor_msgs::msg::Image>("kinect/image_raw", 10);
    depth_pub_ = create_publisher<sensor_msgs::msg::Image>("kinect/depth", 10);
    info_pub_ = create_publisher<sensor_msgs::msg::CameraInfo>("kinect/camera_info", 10);
  }

  void run() {
#ifdef AMR_HAS_FREENECT
    runFreenect();
#else
    RCLCPP_WARN(
        get_logger(),
        "libfreenect was not found at build time. %s, %s, and %s stay quiet. "
        "Kinect model 1414 (Xbox 360).",
        image_pub_->get_topic_name(), depth_pub_->get_topic_name(),
        info_pub_->get_topic_name());
    rclcpp::spin(shared_from_this());
#endif
  }

 private:
#ifdef AMR_HAS_FREENECT
  static void videoCallback(freenect_device * dev, void * video, uint32_t) {
    auto * self = static_cast<KinectFreenectNode *>(freenect_get_user(dev));
    if (self == nullptr || video == nullptr) {
      return;
    }
    self->publishRgb(static_cast<const uint8_t *>(video));
  }

  static void depthCallback(freenect_device * dev, void * depth, uint32_t) {
    auto * self = static_cast<KinectFreenectNode *>(freenect_get_user(dev));
    if (self == nullptr || depth == nullptr) {
      return;
    }
    self->publishDepth(static_cast<const uint16_t *>(depth));
  }

  void publishRgb(const uint8_t * rgb) {
    sensor_msgs::msg::Image msg;
    msg.header.stamp = now();
    msg.header.frame_id = frame_;
    msg.height = kHeight;
    msg.width = kWidth;
    msg.encoding = "rgb8";
    msg.is_bigendian = 0;
    msg.step = kWidth * 3;
    msg.data.assign(rgb, rgb + static_cast<size_t>(kWidth) * kHeight * 3);
    image_pub_->publish(msg);
    auto info = blankInfo(frame_);
    info.header.stamp = msg.header.stamp;
    info_pub_->publish(info);
  }

  void publishDepth(const uint16_t * depth) {
    sensor_msgs::msg::Image msg;
    msg.header.stamp = now();
    msg.header.frame_id = frame_;
    msg.height = kHeight;
    msg.width = kWidth;
    msg.encoding = "16UC1";
    msg.is_bigendian = 0;
    msg.step = kWidth * sizeof(uint16_t);
    const auto * bytes = reinterpret_cast<const uint8_t *>(depth);
    msg.data.assign(bytes, bytes + static_cast<size_t>(msg.step) * kHeight);
    depth_pub_->publish(msg);
  }

  void runFreenect() {
    freenect_context * ctx = nullptr;
    if (freenect_init(&ctx, nullptr) < 0 || ctx == nullptr) {
      RCLCPP_ERROR(get_logger(), "freenect_init failed");
      return;
    }
    // Camera only. Do not add freenect_set_tilt_degs: on this CM4,
    // open_device followed by tilt segfaults. Tilt and LED are pyusb
    // transfers to 045e:02b0 in cm4/server.
    freenect_select_subdevices(ctx, FREENECT_DEVICE_CAMERA);
    freenect_device * dev = nullptr;
    if (freenect_open_device(ctx, &dev, 0) < 0 || dev == nullptr) {
      RCLCPP_ERROR(
          get_logger(),
          "freenect_open_device failed for Kinect model 1414. See docs/bring-up.md.");
      freenect_shutdown(ctx);
      return;
    }
    freenect_set_user(dev, this);
    freenect_set_video_callback(dev, &KinectFreenectNode::videoCallback);
    freenect_set_depth_callback(dev, &KinectFreenectNode::depthCallback);
    freenect_set_video_mode(
        dev, freenect_find_video_mode(FREENECT_RESOLUTION_MEDIUM, FREENECT_VIDEO_RGB));
    freenect_set_depth_mode(
        dev, freenect_find_depth_mode(FREENECT_RESOLUTION_MEDIUM, FREENECT_DEPTH_MM));
    freenect_start_video(dev);
    freenect_start_depth(dev);
    RCLCPP_INFO(get_logger(), "libfreenect camera started (RGB + depth mm)");
    while (rclcpp::ok()) {
      if (freenect_process_events(ctx) < 0) {
        RCLCPP_ERROR(get_logger(), "freenect_process_events failed");
        break;
      }
    }
    freenect_stop_depth(dev);
    freenect_stop_video(dev);
    freenect_close_device(dev);
    freenect_shutdown(ctx);
  }
#endif

  std::string frame_;
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr image_pub_;
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr depth_pub_;
  rclcpp::Publisher<sensor_msgs::msg::CameraInfo>::SharedPtr info_pub_;
};

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  auto node = std::make_shared<KinectFreenectNode>();
  node->run();
  rclcpp::shutdown();
  return 0;
}
