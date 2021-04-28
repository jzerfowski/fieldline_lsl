import sys
import time
import queue
import signal
import logging
import argparse
from datetime import datetime, timedelta


from fieldline_api.fieldline_service import FieldLineService

from fieldline_lsl_connector import FieldLineConnector
from fieldline_lsl_outlet import FieldLineStreamOutlet

stream_handler = logging.StreamHandler()
logging_config = dict(
    format='%(asctime)s %(levelname)s %(threadName)s(%(process)d) %(message)s [%(filename)s:%(lineno)d]',
    datefmt='%d.%m.%Y %H:%M:%S',
    handlers=[stream_handler],
    level=logging.WARNING,
)


logger = logging.getLogger(__name__)


def signal_stop_fService(signal, frame, fService):
    """
    Signal handler to perform graceful shutdown of application
    """
    logger.info("Signal handler has been called to shut down application")
    if fService is not None:
        fService.stop()
        logger.info("FieldLine Service Stopped")
    sys.exit()


def find_chassis(fService, expected_chassis=None):
    # Obtain list of IPs of discovered chassis
    # We sort them to make sure that connected chassis are always in the same order
    discovered_chassis = sorted(fService.get_chassis_list())
    if not discovered_chassis:
        logger.error("No chassis were found")
        fService.stop()
        sys.exit(1)

    logger.info(f"Discovered chassis list: {discovered_chassis}")

    if expected_chassis is not None:
        logger.info(f"Expected chassis list: {expected_chassis}")

        if not all(ip in discovered_chassis for ip in expected_chassis):
            logger.error("Not all expected chassis discovered")
            fService.stop()
            sys.exit(1)
        logger.info(f"Found all expected chassis: {expected_chassis}")
        chassis_list = expected_chassis
    else:
        logger.info(f"No chassis expected; connecting to all available devices")
        chassis_list = discovered_chassis
    return chassis_list


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help="Logging verbosity. Repeat up to three times. Defaults to only script info being printed")
    parser.add_argument('-c', '--chassis', action='append', default=None,
                        help='Connect to chassis ip(s). Can be omitted or given multiple times', required=False)
    parser.add_argument('--init_timeout', type=int, default=None,
                        help="Timeout (in s) of initialization sequence (restart and coarse zeroing). Defaults to 1 hour")
    parser.add_argument('--adc', action='store_true', default=False, help="Activate ADC Streams")
    parser.add_argument('-n', '--sname', default='FieldLineOPM', help="Name of the LSL Stream")
    parser.add_argument('-id', '--sid', default='flopm', help="Unique ID of the LSL Stream")
    parser.add_argument('-t', '--duration', type=int, default=None,
                        help="Duration (in seconds) for the stream to run. Infinite if not given")
    parser.add_argument('--disable-restart', action='store_true', default=False,
                        help="Disables restarting sensors before zeroing to save time. Will fail if sensors were not already started")
    # parser.add_argument('--sensors', type=str, default=None, help='Expected sensors') # Not yet implemented
    args = parser.parse_args()

    expected_sensors = None  # Starts all sensors on all chassis found
    excluded_sensors = []

    # Configure the logging
    print(args.verbose)
    if args.verbose == 0:
        logging_config['level'] = logging.WARNING
        logger.setLevel(logging.INFO)
    elif args.verbose == 1:
        logging_config['level'] = logging.WARNING
        logger.setLevel(logging.DEBUG)
    elif args.verbose == 2:
        logging_config['level'] = logging.INFO
        logger.setLevel(logging.DEBUG)
    elif args.verbose >= 3:
        logging_config['level'] = logging.DEBUG
        logger.setLevel(logging.DEBUG)

    logging.basicConfig(**logging_config)

    # Configure a timeout for the sensor startup phase
    if args.init_timeout is not None:
        init_timeout = timedelta(seconds=args.init_timeout)
    else:
        init_timeout = timedelta(hours=1)

    logger.debug("Initialize the necessary FieldLine API communication instances")
    fConnector = FieldLineConnector()
    fService = FieldLineService(fConnector, prefix="")

    logger.info("Start listening for FieldLine devices")
    fService.start()
    # Don't enable data streaming yet! In this scenario, we do this after initializing the sensors
    # fService.start_data()

    # Add a signal handler that performs an orderly shutdown of fService
    signal.signal(signal.SIGINT, lambda frame, signal: signal_stop_fService(frame, signal, fService))

    logger.debug("Waiting for device discovery")
    time.sleep(2)
    chassis_list = find_chassis(fService, args.chassis)

    init_starttime = datetime.now()
    logger.info(f"Starting chassis and sensor initialization ({init_starttime})")

    logger.info(f"Connecting to chassis: {chassis_list}")
    fService.connect(chassis_list)


    logger.debug("Waiting to establish connection")
    time.sleep(1)

    while fService.is_service_running():
        """
        This loop restarts the sensors (or fakes their restart), and performs the field-zeroing steps
        It only enters the next stage when all sensors finish previous stage"""
        if fConnector.has_sensors_ready():
            sensors = fConnector.get_sensors_ready()
            for chassis_id, sensor_ids in sensors.items():
                logger.info(f"Chassis {chassis_id} has sensors {sensor_ids} available/ready")
                for sensor_id in sensor_ids:
                    if (expected_sensors is None or (chassis_id, sensor_id) in expected_sensors) and (
                    chassis_id, sensor_id) not in excluded_sensors:
                        # fService.turn_off_sensor(chassis_id, sensor_id)
                        # time.sleep(1)
                        fConnector.set_sensor_valid(chassis_id, sensor_id)
                        logger.info(f"Set sensor {chassis_id:02}:{sensor_id:02} valid")
                        if not args.disable_restart:
                            fService.restart_sensor(chassis_id, sensor_id)
                            logger.info(f"Restarting sensor {chassis_id:02}:{sensor_id:02}")
                        else:
                            logger.info(f"Skipping sensor restart (--disable-restart set)")
                            # Instead of restarting just tell the callback it restarted already
                            fConnector.callback_restart_complete(chassis_id, sensor_id)
                    else:
                        logger.debug(f"Sensor {chassis_id:02}:{sensor_id:02} not in expected sensors, turning off")
                        fService.turn_off_sensor(chassis_id, sensor_id)

        elif fConnector.has_restarted_sensors() and fConnector.num_valid_sensors() == fConnector.get_num_restarted_sensors():
            sensors = fConnector.get_restarted_sensors()
            for chassis_id, sensor_ids in sensors.items():
                logger.info(f"Chassis {chassis_id} got restarted sensors {sensor_ids}")
                for sensor_id in sensor_ids:
                    logger.info(f"Coarse Zeroing sensor {chassis_id:02}:{sensor_id:02}")
                    fService.coarse_zero_sensor(chassis_id, sensor_id)

        elif fConnector.has_coarse_zero_sensors() and fConnector.num_valid_sensors() == fConnector.get_num_coarse_zero_sensors():
            sensors = fConnector.get_coarse_zero_sensors()
            for chassis_id, sensor_ids in sensors.items():
                logger.info(f"Chassis {chassis_id} got coarse zeroed sensors {sensor_ids}")
                for sensor_id in sensor_ids:
                    fService.fine_zero_sensor(chassis_id, sensor_id)

        elif fConnector.has_fine_zero_sensors() and fConnector.num_valid_sensors() == fConnector.get_num_fine_zero_sensors():
            sensors = fConnector.get_fine_zero_sensors()
            if expected_sensors is None or all(
                    sensor_id in sensors[chassis_id] for (chassis_id, sensor_id) in expected_sensors):
                logger.info("Success! All expected sensors are up and running")
                break

        elif expected_sensors is not None and fConnector.num_valid_sensors() < len(expected_sensors):
            logger.error(f"An error occurred. There are fewer valid sensors than expected.")
            fService.stop()
            sys.exit(1)

        if expected_sensors is not None and len(expected_sensors) == 0:
            logger.info(f"No Sensors expected, skipping initialization")
            break

        if (datetime.now() - init_starttime) > init_timeout:
            logger.error(f"Initialization of sensors took longer than the defined timeout")
            fService.stop()
            sys.exit(1)

    logger.info("Initialization of sensors complete")
    logger.info("Start data stream from FieldLine Chassis")
    fService.start_data()
    if args.adc:
        for chassis_id in fConnector.get_chassis_ids():
            logger.info(f"Start ADC Stream from Chassis {chassis_id}")
            fService.start_adc(chassis_id)

    if args.duration is not None:
        duration = timedelta(seconds=args.duration)
    else:
        duration = None

    logger.debug(f"Waiting to ensure that all sensors start streaming data")
    time.sleep(0.5)

    # Currently fService/fConnector do not provide information about the streamed channels
    # Therefore, the FieldLineStreamOutlet needs a data sample to determine the proper data structure
    structure_sample = fConnector.data_q.queue[-1]['samples'][0]

    # Open an LSL outlet. Uses the structure_sample to generate LSL Info
    outlet = FieldLineStreamOutlet(structure_sample, fConnector, name=args.sname, adc=args.adc, source_id=args.sid)

    # Empty the queue to start streaming only new samples
    fConnector.clear_queue()
    streaming_start = datetime.now()

    chunk_counter = 0
    while fService.is_service_running() and (duration is None or datetime.now() - streaming_start <= duration):
        try:
            data = fConnector.data_q.get(True, 0.001)

            logger.debug(f"Received data from fConnector: {data}")

            outlet.push_flchunk(data['samples'], timestamp=data['timestamp'])

            if chunk_counter % 1000 == 0:
                logger.info(
                    f"Streaming data on {outlet.streamInfo.name()} ({outlet.streamInfo.source_id()}) since {(datetime.now() - streaming_start).total_seconds():.3f} seconds")
                if duration is not None:
                    logger.info(
                        f"{(duration - (datetime.now() - streaming_start)).total_seconds():.3f} seconds remaining")
            chunk_counter += 1

        except queue.Empty:
            logger.debug("Queue empty")
            continue

    logger.info("Finished streaming, shut down data streams")
    if args.adc:
        for chassis_id in fConnector.get_chassis_ids():
            fService.stop_adc(chassis_id)
    fService.stop_data()
    fService.stop()
