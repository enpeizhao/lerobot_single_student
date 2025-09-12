#!/usr/bin/env python

"""
让episode1运动到默认位置，方便安装相机、夹爪

使用方法：
python -m lerobot.episode_default_position --usb_index=1
"""

import logging
import time

from lerobot.robots.enpei_follower.episode_server import EpisodeAPP
from lerobot.utils.utils import init_logging


def move_to_default_position():
    """移动机械臂到默认位置"""
    try:
        # 初始化控制器
        controller = EpisodeAPP(ip='localhost', port=12345)
        logging.info("Connected to EnpeiRobot controller")
        
        # 移动到默认位置
        # 使能两个机械臂
        fixed_degrees = [180, 90, 83, 210, 110, 210, 90]
        t = controller.angle_mode(fixed_degrees)
        time.sleep(t)
        fixed_degrees = [180, 90, 83, 210, 110-90, 210, 90]
        t = controller.angle_mode(fixed_degrees)
        time.sleep(t)

        # 夹爪运动到10度
        controller.servo_gripper(10)
        logging.info(f"Moving to default position, estimated time: {t:.2f}s")
        
        # 等待移动完成
        time.sleep(t)
        logging.info("Successfully moved to default position")
        
    except Exception as e:
        logging.error(f"Failed to move to default position: {e}")
        raise

def main():
    # 初始化日志
    init_logging()
    
    # 移动到默认位置
    move_to_default_position()

if __name__ == "__main__":
    main()