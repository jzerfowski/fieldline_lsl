import sys
import time
import queue
import signal
import logging
import argparse
import collections
from datetime import datetime, timedelta

from fieldline_api.fieldline_service import FieldLineService

from fieldline_connector_lsl import FieldLineConnector
from fieldline_stream_outlet import FieldLineStreamOutlet

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action="count", default=0, help="Verbosity level - repeat up to three times.")
    parser.add_argument('-c', '--chassis', action='append', default=None, help='Connect to chassis ip(s). Can be omitted or given multiple times', required=False)
    parser.add_argument('--init_timeout', type=int, default=None, help="Timeout of initialization sequence (restart and coarse zeroing). Infinite if not given")
    parser.add_argument('--adc', action='store_true', default=False, help="Activate ADC Streams")
    parser.add_argument('-n', '--sname', default='FieldLineOPM', help="Name of the LSL Stream")
    parser.add_argument('-id', '--sid', default='flopm', help="Unique ID of the LSL Stream")
    parser.add_argument('-t', '--duration', type=int, default=None, help="Duration (in seconds) for the stream to run. Infinite if not given")
    # parser.add_argument('--sensors', type=str, default=None, help='Expected sensors') # Not yet implemented
    args = parser.parse_args()

    # expected_sensors = args.sensors
    expected_sensors = [(0, 1), (0, 2), (1, 4)]  # Should be a list of tuples (chassis_id, sensor_id)
    expected_sensors = None  # Starts all sensors on all chassis found

    # Configure the logging
    stream_handler = logging.StreamHandler()
    logging.basicConfig(
        format='%(asctime)s %(levelname)s %(threadName)s(%(process)d) %(message)s [%(filename)s:%(lineno)d]',
        datefmt='%d.%m.%Y %H:%M:%S',
        level=[logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG][args.verbose],
        handlers=[stream_handler]
    )

    # Configure a timeout for the sensor startup phase
    if args.init_timeout is None:
        init_timeout = None
    else:
        init_timeout = timedelta(seconds=args.init_timeout)

    logger.debug("Initialize the necessary FieldLine API communication instances")
    fConnector = FieldLineConnector()
    fService = FieldLineService(fConnector, prefix="")

    logger.info("Start listening for FieldLine devices")
    fService.start()
    # Don't enable data streaming yet! In this scenario, we do this after initializing the sensors
    # fService.start_data()

    # Add a signal handler that performs an orderly shutdown of fService
    signal.signal(signal.SIGINT, lambda frame, signal: signal_stop_fService(frame, signal, fService))

    logger.debug("Wait for devices to be discovered")
    time.sleep(2)

    # Obtain list of IPs of discovered chassis
    discovered_chassis = fService.get_chassis_list()
    logger.info(f"Discovered chassis list: {discovered_chassis}")

    logger.debug(f"Start initialization of sensors @{datetime.now()}")
    init_starttime = datetime.now()

    chassis_list = []
    if args.chassis is not None:
        logger.info(f"Expected chassis list: {args.chassis}")
        all_found = True
        if not all(ip in discovered_chassis for ip in args.chassis):
            logger.error("Not all expected chassis discovered")
            fService.stop()
            sys.exit(1)
        logger.info(f"Connecting to chassis: {args.chassis}")
        chassis_list = args.chassis
    else:
        chassis_list = discovered_chassis

    logger.info(f"Connecting to chassis: {chassis_list}")
    fService.connect(chassis_list)

    logger.debug("Wait to establish connection")
    time.sleep(1)

    while fService.is_service_running():
        if fConnector.has_sensors_ready():
            sensors = fConnector.get_sensors_ready()
            for chassis_id, sensor_ids in sensors.items():
                logger.info(f"Chassis {chassis_id} has sensors {sensor_ids} available/ready")
                for sensor_id in sensor_ids:
                    if expected_sensors is None or (chassis_id, sensor_id) in expected_sensors:
                        fConnector.set_sensor_valid(chassis_id, sensor_id)
                        logger.info(f"Set sensor {chassis_id:02}:{sensor_id:02} valid, restarting")
                        fService.restart_sensor(chassis_id, sensor_id)
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
            if expected_sensors is None or all(sensor_id in sensors[chassis_id] for (chassis_id, sensor_id) in expected_sensors):
                logger.info("Success! All expected sensors are up and running")
                break

        elif expected_sensors is not None and fConnector.num_valid_sensors() < len(expected_sensors):
            logger.error(f"An error occured. There are fewer valid sensors than expected.")
            fService.stop()
            sys.exit(1)

        if expected_sensors is not None and len(expected_sensors) == 0:
            logger.info(f"No Sensors expected, skipping initialization")
            break

        if init_timeout and (datetime.now() - init_starttime) > init_timeout:
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

    logger.debug(f"Wait to ensure that all sensors started streaming data")
    time.sleep(0.5)

    # Currently, the FieldLineStreamOutlet needs a sample from the chassis to determine the proper data structure
    structure_sample = fConnector.data_q.queue[-1]['samples'][0]
    outlet = FieldLineStreamOutlet(structure_sample, fConnector, adc=args.adc)

    fConnector.clear_queue()
    streaming_start = datetime.now()

    while fService.is_service_running() and (duration is None or datetime.now()-streaming_start <= duration):
        try:
            data = fConnector.data_q.get(True, 0.001)
            logger.debug(f"Received data from fConnector: {data}")

            outlet.push_flchunk(data['samples'], timestamp=data['timestamp'])
        except queue.Empty:
            logger.debug("Queue empty")
            continue

    logger.inf("Finished streaming, shut down data streams")
    if args.adc:
        for chassis_id in fConnector.get_chassis_ids():
            fService.stop_adc(chassis_id)
    fService.stop_data()
    fService.stop()