cmake_minimum_required(VERSION 3.8)
project(amr_base)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(tf2_ros REQUIRED)

add_executable(base_driver_node src/base_driver_node.cpp)
ament_target_dependencies(base_driver_node
  rclcpp geometry_msgs nav_msgs tf2_ros)

add_executable(kinect_freenect_node src/kinect_freenect_node.cpp)
ament_target_dependencies(kinect_freenect_node rclcpp sensor_msgs)

# Optional. Model 1414 is an Xbox 360 Kinect, which this library targets.
find_path(FREENECT_INCLUDE_DIR libfreenect/libfreenect.h)
find_library(FREENECT_LIBRARY freenect)
if(FREENECT_INCLUDE_DIR AND FREENECT_LIBRARY)
  target_compile_definitions(kinect_freenect_node PRIVATE AMR_HAS_FREENECT)
  target_include_directories(kinect_freenect_node PRIVATE ${FREENECT_INCLUDE_DIR})
  target_link_libraries(kinect_freenect_node ${FREENECT_LIBRARY})
  message(STATUS "amr_base: libfreenect found, Kinect node will open a device")
else()
  message(STATUS "amr_base: libfreenect not found, Kinect node stays quiet")
endif()

install(TARGETS base_driver_node kinect_freenect_node
  DESTINATION lib/${PROJECT_NAME})

install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME})

ament_package()
