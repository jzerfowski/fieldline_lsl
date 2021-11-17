#!/usr/bin/env python

"""Module documentation goes here"""
from collections import defaultdict
from dataclasses import dataclass
from typing import List

import logging
logger = logging.getLogger(__name__)
logger.setLevel(level=logging.DEBUG)

import numpy as np
# logging.basicConfig(level=logging.DEBUG)
from new_v21.MyFieldLineService import MyFieldLineService
from fieldline_api.fieldline_callback import FieldLineCallback

class Sensor:
    def __init__(self, chassis_id, sensor_id):

class MyFieldLineConnector(FieldLineCallback):
    def __init__(self):
        super().__init__()
        # self.fService = fService

        self.chassis_id_to_name = dict()
        # self.chassis = dict()
        self.sensors_available = defaultdict(set)
        self.sensors_restarted = defaultdict(set)

        self.sensor_states: dict = dict()


    def chassis_descriptor(self, chassis_id):
        return f"Chassis {self.chassis_id_to_name[chassis_id]} (ID {chassis_id:02})"

    def sensor_descriptor(self, chassis_id, sensor_id):
        return f"{chassis_id:02}:{sensor_id:02}"

    def callback_chassis_connected(self, chassis_name, chassis_id):
        self.chassis_id_to_name[chassis_id] = chassis_name
        logger.info(f"Chassis {chassis_name} with ID {chassis_id} connected")

    def callback_chassis_disconnected(self, chassis_id):
        logger.info(f"Chassis {self.chassis_id_to_name[chassis_id]}")

    def callback_sensors_available(self, chassis_id, sensor_list):
        sensor_descriptor_list = [self.sensor_descriptor(chassis_id, sensor_id) for sensor_id in sensor_list]
        logger.info(f"{self.chassis_descriptor(chassis_id)} has sensors available: {sensor_descriptor_list}")
        self.sensors_available[chassis_id].update(sensor_list)

    def callback_sensor_ready(self, chassis_id, sensor_id):
        logger.info(f"Sensor {self.sensor_descriptor(chassis_id, sensor_id)} ready to be restarted")

    def callback_restart_complete(self, chassis_id, sensor_id):
        logger.info(f"Sensor {self.sensor_descriptor(chassis_id, sensor_id)} restarted")
        self.sensors_restarted[chassis_id].update(set([sensor_id]))
