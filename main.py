from fieldline_connector import FieldLineConnector
from fieldline_api.fieldline_service import FieldLineService
from fieldline_api.fieldline_datatype import FieldLineWaveType

import logging
import argparse
import queue
import time
import sys
import signal
import sys

from datetime import datetime, timedelta
streaming_duration = 10  # Stop stream after n seconds

samples = []

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='store_true', default=False, help="Include debug-level logs.")
    args = parser.parse_args()

    stream_handler = logging.StreamHandler()
    logging.basicConfig(
        format='%(asctime)s %(levelname)s %(threadName)s(%(process)d) %(message)s [%(filename)s:%(lineno)d]',
        datefmt='%m/%d/%Y %I:%M:%S %p',
        level=logging.DEBUG if args.verbose else logging.INFO,
        handlers=[stream_handler]
    )
    logging.info("Starting FieldLine service main")

    ip_list = ['192.168.2.41']
    fConnector = FieldLineConnector()
    fService = FieldLineService(fConnector, prefix="")
    def signal_handler(signal, frame):
        logging.info("SIGNAL handler")
        if fService is not None:
            fService.stop()
        logging.info("FieldLine Service stopped")
    signal.signal(signal.SIGINT, signal_handler)

    # Start listening for FieldLine devices
    fService.start()
    # Enable data streaming
    fService.start_data()
    # Wait for devices to be discovered
    time.sleep(2)
    # Return list of IPs of chassis discovered
    chassis_list = fService.get_chassis_list()
    logging.info("Discovered chassis list: %s" % chassis_list)
    logging.info("Expected IP list: %s" % ip_list)
    all_found = True
    for ip in ip_list:
        if ip not in chassis_list:
            all_found = False
    if not all_found:
        logging.error("Not all expected chassis discovered")
        # Stop all services and shut down cleanly
        fService.stop()
        sys.exit()
    # Connect to list of IPs
    fService.connect(ip_list)
    my_chassis = None

    start = None

    while fService.is_service_running():
        if fConnector.has_sensors_ready():
            sensors = fConnector.get_sensors_ready()
            fConnector.set_all_sensors_valid()
            for c, s in sensors.items():
                if not my_chassis:
                    my_chassis = c
                    #logging.info("Starting ADC on chassis %d" % my_chassis)
                    #fService.start_adc(c, 1000)
                logging.info("Chassis %d got new sensors %s" % (c, s))
                for sensor in s:
                    fService.restart_sensor(c, sensor)
        elif fConnector.has_restarted_sensors() and fConnector.num_valid_sensors() == fConnector.get_num_restarted_sensors():
            sensors = fConnector.get_restarted_sensors()
            for c, s in sensors.items():
                logging.info("Chassis %s got restarted sensors %s" % (c, s))
                for sensor in s:
                    fService.coarse_zero_sensor(c, sensor)
        elif fConnector.has_coarse_zero_sensors() and fConnector.num_valid_sensors() == fConnector.get_num_coarse_zero_sensors():
            sensors = fConnector.get_coarse_zero_sensors()
            for c, s in sensors.items():
                logging.info("Chassis %s got coarse zero sensors %s" % (c, s))
                for sensor in s:
                    fService.fine_zero_sensor(c, sensor)
        elif fConnector.has_fine_zero_sensors() and fConnector.num_valid_sensors() == fConnector.get_num_fine_zero_sensors():
            sensors = fConnector.get_fine_zero_sensors()
            #for c, s in sensors.items():
            #    logging.info("Chassis %s got fine zero sensors %s" % (c, s))
            #    fService.start_bz(c, s, 1000)
            #    for sensor in s:
            #        fService.set_bz_wave(c, sensor, FieldLineWaveType.WAVE_SINE, 1, 1)

        try:
            data = fConnector.data_q.get(True, 0.01)

            samples.append(data)
            # Start the timer after the first data sample has been received
            if not start:
                start = datetime.now()

            if timedelta(seconds=streaming_duration) < datetime.now() - start:
                break

            logging.info("DATA %s" % data)
        except queue.Empty:
            continue

    # Stop streaming after streaming_duration to do some debugging
    fService.stop_data()
