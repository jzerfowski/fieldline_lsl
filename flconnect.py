#!/usr/bin/env python

"""Module documentation goes here"""


import logging
import argparse
import queue
import time
import sys
import signal
import sys

import numpy as np

from datetime import datetime, timedelta

from fieldline_connector import FieldLineConnector
from fieldline_api.fieldline_service import FieldLineService

from fllsl import FieldLineLSL




def set_logging(args):
    stream_handler = logging.StreamHandler()
    log_level = logging.ERROR

    if not args.verbose:
        log_level = logging.ERROR
    elif args.verbose == 1:
        log_level = logging.WARNING
    elif args.verbose == 2:
        log_level = logging.INFO
    elif args.verbose >= 3:
        log_level = logging.DEBUG

    logging.basicConfig(
        format='%(asctime)s %(levelname)s %(threadName)s(%(process)d) %(message)s [%(filename)s:%(lineno)d]',
        datefmt='%m/%d/%Y %I:%M:%S %p',
        level=log_level,
        handlers=[stream_handler]
    )
    logging.debug(f"Set log-level to {logging.getLevelName(log_level)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action="count", default=0, help="verbose level... repeat up to three times.")
    parser.add_argument('-c', '--chassis', action='append', help='Connect to chassis ip. Can be omitted or given multiple times', required=False)
    parser.add_argument('--adc', action='store_true', default=False, help="Activate ADC Input")
    parser.add_argument('-n', '--sname', default='FieldLineOPM', help="Name of the LSL Stream")
    parser.add_argument('-id', '--sid', default='flopm', help="Unique ID of the LSL Stream")
    parser.add_argument('-t', '--duration', type=int, default=0, help="Duration (in seconds) for the stream to run. 0-->24 hours")

    args = parser.parse_args()

    set_logging(args)

    logging.info("Starting FieldLine LSL Connector")

    fConnector = FieldLineConnector()
    fService = FieldLineService(fConnector, prefix="")

    def signal_handler(signal, frame):
        logging.info(f"Handling {signal}-SIGNAL ")
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

    chassis_list = fService.get_chassis_list()

    logging.info(f"Discovered chassis list: {chassis_list}")

    if args.chassis is not None:
        logging.info(f"Expected IP list: {args.chassis}")
        all_found = True
        for ip in args.chassis:
            if ip not in chassis_list:
                all_found = False
        if not all_found:
            logging.error("Not all expected chassis discovered")
            fService.stop()
            sys.exit()
        fService.connect(args.chassis)
    else:
        fService.connect(chassis_list)

    all_sensors_calibrated = False

    while fService.is_service_running() and not all_sensors_calibrated:
        if fConnector.num_valid_sensors() == 0:
            break
        if fConnector.has_sensors_ready():
            sensors = fConnector.get_sensors_ready()
            fConnector.set_all_sensors_valid()
            for c, s in sensors.items():
                if args.adc:
                    logging.info(f"Starting ADC on chassis {c}")
                    fService.start_adc(c)
                logging.info(f"Chassis {c} got new sensors {s}")
                for sensor in s:
                    fService.restart_sensor(c, sensor)
        elif fConnector.has_restarted_sensors() and fConnector.num_valid_sensors() == fConnector.get_num_restarted_sensors():
            sensors = fConnector.get_restarted_sensors()
            for c, s in sensors.items():
                logging.info(f"Chassis {c} got restarted sensors {s}")
                for sensor in s:
                    fService.coarse_zero_sensor(c, sensor)
        elif fConnector.has_coarse_zero_sensors() and fConnector.num_valid_sensors() == fConnector.get_num_coarse_zero_sensors():
            sensors = fConnector.get_coarse_zero_sensors()
            for c, s in sensors.items():
                logging.info(f"Chassis {c} got coarse zero sensors {s}")
                for sensor in s:
                    logging.info(f"Fine-Zeroing sensor {sensor}")
                    fService.fine_zero_sensor(c, sensor)
        elif fConnector.has_fine_zero_sensors() and fConnector.num_valid_sensors() == fConnector.get_num_fine_zero_sensors():
            sensors = fConnector.get_fine_zero_sensors()
            all_sensors_calibrated = True

    logging.info("Initialization finished, preparing data stream")

    fService.start_data()
    if args.adc:
        fService.start_adc(0)

    time.sleep(1)

    sample = fConnector.data_q.queue[-1][0]
    fConnector.empty_queue()

    logging.info(f"Opening LSL-Outlet")
    outlet = FieldLineLSL(fConnector, sample, name=args.sname, source_id=args.sid)
    print(outlet.streamInfo)

    print(outlet)

    if not args.duration == 0:
        duration = timedelta(seconds=args.duration)
    else:
        duration = timedelta(hours=24)

    duration = duration.total_seconds()
    start = datetime.now()


    print(f"Starting data stream for {duration}")
    runtime = 0
    samples_counter = 0

    while duration > runtime:
        runtime = (datetime.now() - start).total_seconds()
        if np.ceil(runtime) % 10 == 1:
            print(f"Running since {runtime} seconds with {samples_counter/runtime} samples/second")

        try:
            samples = fConnector.data_q.get(True, 0.001)
            lsldata = [[ch_data['data'] for ch_data in sample.values()] for sample in samples]
            outlet.push_chunk(lsldata)
            samples_counter += len(samples)
        except queue.Empty:
            continue
    print("Stopping")

    if args.adc:
        fService.stop_adc(0)
    fService.stop_data()
