#!/usr/bin/env python

"""Start a LabStreamingLayer Stream from FieldLine Optically Pumped Magnetometers"""
import time
import argparse
import logging
import sys

import FieldLineLSL

stream_handler = logging.StreamHandler()
logging_config = dict(
    format='%(asctime)s %(levelname)s %(threadName)s(%(process)d) %(message)s [%(filename)s:%(lineno)d]',
    datefmt='%d.%m.%Y %H:%M:%S',
    handlers=[stream_handler],
    level=logging.WARNING,
)


def set_verbosity(logging_config, logger, verbosity):
    if verbosity == 0:
        logging_config['level'] = logging.WARNING
        logger.setLevel(logging.INFO)
    elif verbosity == 1:
        logging_config['level'] = logging.WARNING
        logger.setLevel(logging.DEBUG)
    elif verbosity == 2:
        logging_config['level'] = logging.INFO
        logger.setLevel(logging.DEBUG)
    elif verbosity >= 3:
        logging_config['level'] = logging.DEBUG
        logger.setLevel(logging.DEBUG)

    logging.basicConfig(**logging_config)


logger = logging.getLogger(__name__)


def signal_stop_fService(signal, frame, fService):
    """
    Signal handler to perform graceful shutdown of application
    """
    logger.info("Signal handler has been called to shut down application")
    if fService is not None:
        fService.stop_streaming()
        logger.info("FieldLine Service Stopped")
    sys.exit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--chassis', action='append', default=None,
                        help='Connect to chassis ip(s). ', required=True)
    parser.add_argument('--not-skip-restart', action='store_true', default=False,
                        help="If set, all sensors will be restarted automatically")
    parser.add_argument('--not-skip-zeroing', action='store_true', default=False,
                        help="If set, all sensors will be coarse- and fine-zeroed automatically before streaming")
    parser.add_argument('--adc', action='store_true', default=False, help="Activate ADC Streams")
    parser.add_argument('-n', '--stream_name', default='FieldLineOPM', help="Name of the LSL Stream")
    parser.add_argument('-id', '--stream_id', default='FieldLineOPM_sid', help="Unique ID of the LSL Stream")
    parser.add_argument('-t', '--duration', type=int, default=None,
                        help="Duration (in seconds) for the stream to run. Infinite if not given")
    parser.add_argument('--heartbeat', type=int, default=60,
                        help="Heartbeat to print every n seconds when streaming data")
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help="Logging verbosity. Repeat up to three times. Defaults to only script info being printed")

    args = parser.parse_args()

    # Configure the logging
    set_verbosity(logging_config, logger, args.verbose)

    logger.info("Initializing FieldLineLSL")
    print(args.chassis)
    fLSL = FieldLineLSL.FieldLineLSL(ip_list=args.chassis, stream_name=args.stream_name, source_id=args.stream_id, stream_type='MEG',
                                     log_heartbeat=args.heartbeat, unit_T=FieldLineLSL.Unit_T_Factor.fT)

    logger.info("FieldLineLSL initialized. Calling FieldLineService.open()")
    fLSL.open()  # FieldLineService has to be opened to connect to the chassis
    logger.info("Beginning initialization of sensors")
    fLSL.init_sensors(skip_restart=~args.not_skip_restart, skip_zeroing=~args.not_skip_zeroing, adcs=args.adc)
    logger.info("Initialized sensors. Initializing stream")
    fLSL.init_stream()

    logger.info("Starting streaming")
    fLSL.start_streaming()
    if args.duration:
        time.sleep(args.duration)
    else:
        input("Press enter to stop streaming")

    logger.info("Stopping streaming.")
    fLSL.close()