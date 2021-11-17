#!/usr/bin/env python

"""Module documentation goes here"""
from collections import defaultdict

import numpy as np
import sys
import time
import queue

from datetime import datetime, timedelta
import argparse
import signal

from fieldline_api.fieldline_callback import FieldLineCallback
from fieldline_api.fieldline_service import FieldLineService
from fieldline_lsl_outlet import FieldLineStreamOutlet

from pylsl import local_clock

import logging

stream_handler = logging.StreamHandler()
logging_config = dict(
    format='%(asctime)s %(levelname)s %(threadName)s(%(process)d) %(message)s [%(filename)s:%(lineno)d]',
    datefmt='%d.%m.%Y %H:%M:%S',
    handlers=[stream_handler],
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

class FieldLineLSLService(FieldLineService):
    def find_chassis(self, expected_chassis=None):
        discovered_chassis = self.get_chassis_list()
        if not discovered_chassis:
            logger.error("fService: No chassis were found")
            self.stop()
            sys.exit(1)

        logger.info(f"fService: Discovered chassis list: {discovered_chassis}")

        if expected_chassis is None:
            logger.info(f"fService: No chassis expected; connecting to all available devices")
            chassis_list = discovered_chassis
        else:
            logger.info(f"fService: Expected chassis list: {expected_chassis}")

            if not all(ip in discovered_chassis for ip in expected_chassis):
                logger.error(f"fService: Not all expected chassis discovered")
                fService.stop()
                sys.exit(1)
            logger.info(f"fService: Found all expected chassis: {expected_chassis}")
            chassis_list = expected_chassis
        return chassis_list

class FieldLineLSLConnector(FieldLineCallback):
    def __init__(self):
        super().__init__()

        self.chassis_id_to_name = dict()  # Collects all connected chassis
        self.sensors_available = defaultdict(set)
        # self.sensors_ready = defaultdict(list)
        self.sensors_selected = defaultdict(set)
        self.sensors_restarted = defaultdict(set)
        self.sensors_coarse_zeroed = defaultdict(set)
        self.sensors_fine_zeroed = defaultdict(set)
        self.all_sensors = dict()

    def get_chassis_ids(self):
        return list(self.chassis_id_to_name.keys())

    def chassis_descriptor(self, chassis_id):
        return f"Chassis {self.chassis_id_to_name[chassis_id]} (ID {chassis_id})"

    def sensor_descriptor(self, chassis_id, sensor_id):
        return f"Sensor {chassis_id:02}:{sensor_id:02}"

    def callback_chassis_connected(self, chassis_name, chassis_id):
        self.chassis_id_to_name[chassis_id] = chassis_name
        logger.info(f"fConnector: {self.chassis_descriptor(chassis_id)} connected")

    def callback_chassis_disconnected(self, chassis_id):
        logger.info(f"fConnector: {self.chassis_descriptor(chassis_id)} disconnected")
        del self.chassis_id_to_name[chassis_id]

    def callback_sensors_available(self, chassis_id, sensor_list):
        logger.info(f"fConnector: {self.chassis_descriptor(chassis_id)} has {len(sensor_list)} sensors available: {sensor_list}")

        self.sensors_available[chassis_id].update(sensor_list)

    def callback_sensor_ready(self, chassis_id, sensor_id):
        logger.info(f"fConnector: {self.chassis_descriptor(chassis_id)} sensor {sensor_id} is ready to be restarted")

    def callback_restart_complete(self, chassis_id, sensor_id):
        logger.info(f"fConnector: {self.sensor_descriptor(chassis_id, sensor_id)} restarted")
        self.set_sensor_restarted(chassis_id, sensor_id)

    def callback_coarse_zero_complete(self, chassis_id, sensor_id):
        logger.info(f"fConnector: {self.sensor_descriptor(chassis_id, sensor_id)} coarse zeroed")
        self.set_sensor_coarse_zeroed(chassis_id, sensor_id)

    def callback_fine_zero_complete(self, chassis_id, sensor_id):
        logger.info(f"fConnector: {self.sensor_descriptor(chassis_id, sensor_id)} fine-zeroed")
        self.set_sensor_fine_zeroed(chassis_id, sensor_id)

    # Manipulate sensors_available
    def get_sensors_available(self):
        return self.sensors_available

    def has_sensors_available(self):
        return any(len(sensor_list)>0 for chassis_id, sensor_list in self.get_sensors_available().items())

    def pop_sensors_available(self):
        sensors_available = self.get_sensors_available()
        self.sensors_available = defaultdict(set)
        return sensors_available

    # Manipulate sensors_selected
    def get_sensors_selected(self):
        return self.sensors_selected

    def has_sensors_selected(self):
        return any(len(sensor_list)>0 for chassis_id, sensor_list in self.get_sensors_selected().items())

    def select_sensor(self, chassis_id, sensor_id):
        self.sensors_selected[chassis_id].update(set([sensor_id]))

    def deselect_sensor(self, chassis_id, sensor_id):
        self.sensors_selected[chassis_id].difference_update(set([sensor_id]))

    # Manipulate sensors_restarted
    def get_sensors_restarted(self):
        return self.sensors_restarted

    def has_sensors_restarted(self):
        return any(len(sensor_list)>0 for chassis_id, sensor_list in self.get_sensors_restarted().items())

    def set_sensor_restarted(self, chassis_id, sensor_id):
        self.sensors_restarted[chassis_id].update(set([sensor_id]))

    def pop_sensors_restarted(self):
        sensors_restarted = self.get_sensors_restarted()
        self.sensors_restarted = defaultdict(set)
        return sensors_restarted

    # Manipulate sensors_coarse_zeroed
    def get_sensors_coarse_zeroed(self):
        return self.sensors_coarse_zeroed

    def has_sensors_coarse_zeroed(self):
        return any(len(sensor_list)>0 for chassis_id, sensor_list in self.get_sensors_coarse_zeroed().items())

    def set_sensor_coarse_zeroed(self, chassis_id, sensor_id):
        self.sensors_coarse_zeroed[chassis_id].update(set([sensor_id]))

    def pop_sensors_coarse_zeroed(self):
        sensors_coarse_zeroed = self.get_sensors_coarse_zeroed()
        self.sensors_coarse_zeroed = defaultdict(set)
        return sensors_coarse_zeroed

    # Manipulate sensors_fine_zeroed
    def get_sensors_fine_zeroed(self):
        return self.sensors_fine_zeroed

    def has_sensors_fine_zeroed(self):
        return any(len(sensor_list)>0 for chassis_id, sensor_list in self.get_sensors_fine_zeroed().items())

    def set_sensor_fine_zeroed(self, chassis_id, sensor_id):
        self.sensors_fine_zeroed[chassis_id].update(set([sensor_id]))

    def pop_sensors_fine_zeroed(self):
        sensors_fine_zeroed = self.get_sensors_fine_zeroed()
        self.sensors_fine_zeroed = defaultdict(set)
        return sensors_fine_zeroed

    def callback_data_available(self, sample):
        # For LSL we require accurate timestamping, so we add the local_clock time to the sample
        # time = local_clock()
        sample['timestamp_lsl'] = local_clock()
        # data = dict(timestamp=time, samples=sample_list)
        self.data_q.put(sample)

    def clear_queue(self):
        with self.data_q.mutex:
            self.data_q.queue.clear()


def init_sensors(mode='open', chassis_ips=None, disable_restart=False, skip_init=False):
    """
    Initialize, restart and field-zero sensors
    :param mode: Mode of operation. 'open' for open loop, 'closed' for closed loop
    :param chassis_ips: Ip addresses of expected chassis
    :param disable_restart: Flag to disable the restart procedure of sensors and only do zeroing
    :param skip_init: Flag to disable entire init procedure (restart and zeroing)
    :return: fService, fConnector instances of FieldLineLSLService and FieldLineLSLConnector
    """
    expected_sensors = None  # Starts all sensors on all chassis found
    excluded_sensors = []

    ## Initialize the Connectors
    fConnector = FieldLineLSLConnector()
    fService = FieldLineLSLService(fConnector, prefix="")

    logger.info("Start listening for FieldLine devices")
    fService.start()
    # Don't enable data streaming yet! In this scenario, we do this after initializing the sensors
    # fService.start_data()

    # Add a signal handler that performs an orderly shutdown of fService
    def signal_stop_fService(signal, frame, fService):
        """
        Signal handler to perform graceful shutdown of application
        """
        logger.info("Signal handler has been called to shut down application")
        if fService is not None:
            fService.stop_streaming()
            logger.info("FieldLine Service Stopped")
        sys.exit()

    signal.signal(signal.SIGINT, lambda frame, signal: signal_stop_fService(frame, signal, fService))
    signal.signal(signal.SIGTERM, lambda frame, signal: signal_stop_fService(frame, signal, fService))

    logger.debug("Waiting for device discovery")
    time.sleep(2)
    chassis_list = fService.find_chassis(expected_chassis=chassis_ips)

    init_starttime = datetime.now()
    logger.info(f"Starting chassis and sensor initialization ({init_starttime})")

    time.sleep(2)
    logger.info(f"Connecting to chassis: {chassis_list}")
    fService.connect(chassis_list)

    logger.debug("Waiting to establish connection")
    time.sleep(1)

    # Set the mode in which we want to run the sensors
    if mode == 'open':
        pass
    if mode == 'closed':
        fService.set_closed_loop()


    while fService.is_service_running():  # fService can be stopped through signal.SIGINT
        if skip_init:
            logger.info("Initialization sequence skipped")
            break

        if expected_sensors is not None and len(expected_sensors) == 0:
            logger.info(f"No sensors expected, skipping initialization")

        # If new sensors are available, restart them if necessary
        if fConnector.has_sensors_available():
            sensors_available = fConnector.pop_sensors_available()

            for chassis_id, sensor_ids in sensors_available.items():
                logger.info(f"{fConnector.chassis_descriptor(chassis_id)} build version {fService.get_version(chassis_id)}")
                for sensor_id in sensor_ids:
                    # TODO: Add calibration value in information
                    logger.info(f"""{fConnector.sensor_descriptor(chassis_id, sensor_id)} information:
                     State: {fService.get_sensor_state(chassis_id, sensor_id)}
                     Card serial #: {fService.get_serial_numbers(chassis_id, sensor_id)[0]}, Sensor serial #: {fService.get_serial_numbers(chassis_id, sensor_id)[1]}
                     Fields: {fService.get_fields(chassis_id, sensor_id)}""")

                    if (expected_sensors is None or (chassis_id, sensor_id) in expected_sensors) and (
                    chassis_id, sensor_id not in excluded_sensors):
                        fConnector.select_sensor(chassis_id, sensor_id)
                        logger.info(f"Selected {fConnector.sensor_descriptor(chassis_id, sensor_id)}")

                        if disable_restart:
                            logger.info(
                                f"Skipping restart of {fConnector.sensor_descriptor(chassis_id, sensor_id)} (--disable-restart set)")
                            # Instead of restarting just tell the callback it restarted already
                            fConnector.set_sensor_restarted(chassis_id, sensor_id)
                        else:
                            logger.info(f"Restarting {fConnector.sensor_descriptor(chassis_id, sensor_id)}")
                            fService.restart_sensors({chassis_id: [sensor_id]})
                    else:
                        logger.info(
                            f"{fConnector.sensor_descriptor(chassis_id, sensor_id)} not in expected sensors. Turning off")
                        fService.turn_off_sensors({chassis_id: [sensor_id]})

        if fConnector.has_sensors_restarted():
            sensors_restarted = fConnector.get_sensors_restarted()
            sensors_selected = fConnector.get_sensors_selected()

            if all(sensors_restarted[chassis_id] == sensors_selected[chassis_id] for chassis_id in
                   sensors_selected.keys()):
                logger.info(f"Coarse-zeroing sensors {dict(sensors_restarted)}")
                fConnector.pop_sensors_restarted()
                time.sleep(2)
                fService.coarse_zero_sensors(sensors_restarted)

        if fConnector.has_sensors_coarse_zeroed():
            sensors_coarse_zeroed = fConnector.get_sensors_coarse_zeroed()
            sensors_selected = fConnector.get_sensors_selected()

            if all(sensors_coarse_zeroed[chassis_id] == sensors_selected[chassis_id] for chassis_id in
                   sensors_selected.keys()):
                logger.info(f"Fine-zeroing sensors {dict(sensors_coarse_zeroed)}")
                fConnector.pop_sensors_coarse_zeroed()
                fService.fine_zero_sensors(sensors_coarse_zeroed)

        if fConnector.has_sensors_fine_zeroed():
            sensors_fine_zeroed = fConnector.get_sensors_fine_zeroed()
            sensors_selected = fConnector.get_sensors_selected()

            if all(sensors_fine_zeroed[chassis_id] == sensors_selected[chassis_id] for chassis_id in
                   sensors_selected.keys()):
                logger.info("All selected sensors are fine zeroed")
                break

    return fService, fConnector

if __name__ == '__main__':

    ## Parse the arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help="Logging verbosity. Repeat up to three times. Defaults to only script info being printed")
    parser.add_argument('-c', '--chassis', action='append', default=None,
                        help='Connect to chassis ip(s). Can be omitted or given multiple times', required=False)
    parser.add_argument('--adc', action='store_true', default=False, help="Activate ADC Streams")
    parser.add_argument('-n', '--sname', default='FieldLineOPM', help="Name of the LSL Stream")
    parser.add_argument('-id', '--sid', default='flopm', help="Unique ID of the LSL Stream")
    parser.add_argument('-t', '--duration', type=int, default=None,
                        help="Duration (in seconds) for the stream to run. Infinite if not given")
    parser.add_argument('--disable-restart', action='store_true', default=False,
                        help="Disables restarting sensors before zeroing to save time. Will fail if sensors were not already started")
    parser.add_argument('--mode', default='open', help="Start sensors in closed/open loop. Possible values:"
                                                       "open/closed/28/50")
    parser.add_argument('--skip-init', action='store_true', default=False,
                        help="Disables all initialization steps (restarting, coarse- and fine-zeroing)")

    # parser.add_argument('--sensors', type=str, default=None, help='Expected sensors') # Not yet implemented
    args = parser.parse_args()

    ## Configure the logging
    if args.verbose == 0:
        logging_config['level'] = logging.WARNING
        logger.setLevel(logging.INFO)
    elif args.verbose == 1:
        logging_config['level'] = logging.WARNING
        logger.setLevel(logging.DEBUG)
    elif args.verbose == 2:
        logging_config['level'] = logging.INFO
        logger.setLevel(logging.INFO)
    elif args.verbose >= 3:
        logging_config['level'] = logging.DEBUG
        logger.setLevel(logging.DEBUG)

    logging.basicConfig(**logging_config)

    fService, fConnector = init_sensors(mode=args.mode, chassis_ips=args.chassis, disable_restart=args.disable_restart, skip_init=args.skip_init)

    logger.info("Success!")

    fService.start_data()
    if args.adc:
        for chassis_id in fConnector.get_chassis_ids():
            logger.info(f"Start ADC Stream from Chassis {chassis_id}")
            fService.start_adc(chassis_id)
    else:
        for chassis_id in fConnector.get_chassis_ids():
            logger.info(f"Stopping ADC Stream from Chassis {chassis_id}")
            fService.stop_adc(chassis_id)

    if args.duration is not None:
        duration = timedelta(seconds=args.duration)
    else:
        duration = None

    logger.debug(f"Waiting to ensure that all sensors start streaming data")
    time.sleep(0.5)

    # Currently fService/fConnector do not provide information about the streamed channels
    # Therefore, the FieldLineStreamOutlet needs a data sample to determine the proper data structure
    structure_sample = fConnector.data_q.queue[-1]
    print(structure_sample)

    # Open an LSL outlet. Uses the structure_sample to generate LSL Info
    outlet = FieldLineStreamOutlet(structure_sample, fConnector, fService, name=args.sname, adc=args.adc, source_id=args.sid)

    # Empty the queue to start streaming only new samples
    fConnector.clear_queue()
    streaming_start = datetime.now()

    sample_counter = 0

    while fService.is_service_running() and (duration is None or datetime.now() - streaming_start <= duration):
        try:
            data = fConnector.data_q.get(True, 0.001)

            logger.debug(f"Received data from fConnector: {data}")

            timestamp = data['timestamp_lsl']
            data_frames = data['data_frames']

            outlet.push_flchunk(data_frames, timestamp=timestamp)

            if sample_counter % (10*1000) == 0:
                logger.info(
                    f"Streaming data on {outlet.streamInfo.name()} ({outlet.streamInfo.source_id()}) since {(datetime.now() - streaming_start).total_seconds():.3f} seconds")
                logger.info(f"{len(fConnector.data_q.queue)} samples in queue")
                if duration is not None:
                    logger.info(
                        f"{(duration - (datetime.now() - streaming_start)).total_seconds():.3f} seconds remaining")

            sample_counter += 1

        except queue.Empty:
            logger.debug("Queue empty")
            continue

    logger.info("Finished streaming, shut down data streams")
    if args.adc:
        for chassis_id in fConnector.get_chassis_ids():
            fService.stop_adc(chassis_id)
    fService.stop_data()
    fService.stop()