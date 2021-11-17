from fieldline_api.fieldline_datatype import FieldLineSensorStatusType
from fieldline_api.fieldline_service import FieldLineService

import logging
logger = logging.getLogger(__name__)

class MyFieldLineService(FieldLineService):
    def find_chassis(self, expected_chassis: list = None):
        discovered_chassis = self.get_chassis_list()
        if not discovered_chassis:
            logger.error("No chassis were found")
            return None

        logger.info(f"Discovered chassis list: {discovered_chassis}")

        if expected_chassis is None:
            logger.debug(f"No chassis expected; connecting to all available devices")
            return discovered_chassis
        else:
            if not (all(ip in discovered_chassis for ip in expected_chassis)):
                logger.error(f"Not all expected chassis discovered. Expected: {expected_chassis}")
                return None
            else:
                logger.info(f"Found all expected chassis: {expected_chassis}")
                return expected_chassis

    def get_sensors_in_state(self, state: FieldLineSensorStatusType):
        chassis_list = self.get_chassis_list()

        for chassis in chassis_list:
            self.get_serial_numbers()