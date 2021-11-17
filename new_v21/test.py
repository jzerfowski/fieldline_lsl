#!/usr/bin/env python

"""Module documentation goes here"""
import logging
logger = logging.getLogger(__name__)

import time
from datetime import datetime

logger.setLevel(level=logging.DEBUG)
from new_v21.MyFieldLineConnector import MyFieldLineConnector
from new_v21.MyFieldLineService import MyFieldLineService

fConnector = MyFieldLineConnector()
fService = MyFieldLineService(fConnector, prefix="")

logger.info("Start listening for FieldLine devices")
fService.start()

logger.debug("Waiting for device discovery")
time.sleep(2)

chassis_list = fService.find_chassis(expected_chassis=None)

init_starttime = datetime.now()
logger.info(f"Starting chassis and sensor initialization ({init_starttime})")

time.sleep(2)
logger.info(f"Connecting to chassis: {chassis_list}")
fService.connect(chassis_list)