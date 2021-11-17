#!/usr/bin/env python

"""
FieldLine LabStreamingLayer module
The class contained in this module can be used to automatically stream sensor data from FieldLine OPMs via LSL.
For more information and requirements, please refer to the readme in
[https://github.com/jzerfowski/fieldline_lsl](https://github.com/jzerfowski/fieldline_lsl]
"""

__author__ = "Jan Zerfowski"
__email__ = "research@janzerfowski.de"
__url__ = "https://github.com/jzerfowski/fieldline_lsl"
__license__ = "GPL-3.0-only"
__version__ = "0.3.1"

from enum import Enum
from queue import Queue, Empty
from typing import Union, List
import logging
from threading import Event, Thread
import importlib.metadata

from fieldline_api.fieldline_service import FieldLineService
from fieldline_api.pycore.sensor import ChannelInfo

import pylsl

logger = logging.getLogger(__name__)


class FieldLineDataType(Enum):
    """
    Represent the three known datatypes in sensor data (the last element XX in sensor names, e.g. 00:01:XX)
    """
    ADC = '0'
    OPEN_LOOP = '28'
    CLOSED_LOOP = '50'


class Unit_T_Factor(Enum):
    """
    Represent common orders of magnitude and their factors relative to SI unit Tesla
    """
    T = 1
    mT = 1E3
    uT = 1E6
    nT = 1E9
    pT = 1E12
    fT = 1E15


class FieldLineLSL2(FieldLineService):
    """
    Instance of FieldLineService to facilitate streaming of data via LSL
    """
    def __init__(self, ip_list: List[str], stream_name: str = "FieldLineOPM", source_id: str = "FieldLineOPM_Stream",
                 prefix: str = "", stream_type='MEG', log_heartbeat: int = 60, unit_T: Unit_T_Factor = Unit_T_Factor.fT):
        super().__init__(ip_list=ip_list, prefix=prefix)

        # LSL Information provided by user
        self.stream_name: str = stream_name
        self.source_id: str = source_id

        # LSL Information filled after zeroing
        self.channel_count: int = None
        self.stream_type: str = stream_type
        self.stream_info: pylsl.StreamInfo = None
        self.stream_outlet: pylsl.StreamOutlet = None

        self._channel_names: list = None

        if unit_T not in Unit_T_Factor:
            logger.warning(f"{unit_T=} is not a known unit. Please provide an instance of {Unit_T_Factor}")
            self.unit_T: Unit_T_Factor = Unit_T_Factor.T
        else:
            self.unit_T: Unit_T_Factor = unit_T
        self.unit_T_factor = self.unit_T.value

        self.done: Event = Event()
        self.data_queue: Queue = Queue()

        self.streaming_thread: Thread = None
        self.running: bool = False

        self._calibration_dict: dict = None

        self.t_stream_start: int = None
        self.log_heartbeat: int = log_heartbeat

        self.first_lsl_timestamp = None  # Timestamp of pylsl.local_clock() to sync with chassis_timestamps
        self.first_chassis_timestamp = None  # FieldLine chassis system's timestamp of first dataframe to arrive

    def init_sensors(self, skip_restart=True, skip_zeroing=True, closed_loop_mode=True,
                     adcs: Union[bool, List] = False):
        connect_to_sensor_dict = self.load_sensors()

        logger.info(f"Initializing sensors {connect_to_sensor_dict}")
        if not skip_restart:
            self.restart_sensors(connect_to_sensor_dict)

        self.set_closed_loop(closed_loop_mode)  # This is blocking until closed_loop is set

        if not skip_zeroing:
            self.zero_sensors(connect_to_sensor_dict)

        self.init_adcs(adcs)

        self._set_channel_names()
        self._set_calibration_dict()

    def restart_sensors(self, sensors: dict):
        logger.info(f"Restarting sensors {sensors}")
        super().restart_sensors(sensors, on_next=self.callback_restarted, on_error=self.callback_error,
                                on_completed=lambda: self.callback_completed("Restart"))
        logger.info(f"Waiting for restart to be complete")

        self.done.wait()
        self.done.clear()

    def turn_off_sensors(self, sensors: dict):
        logger.info(f"Turning off sensors {sensors}")
        super().turn_off_sensors(sensors)
        logger.info(f"Turned off sensors {sensors}")

    def zero_sensors(self, sensors: dict):
        logger.info(f"Coarse zeroing sensors {sensors}")
        self.coarse_zero_sensors(sensors, on_next=self.callback_coarse_zeroed, on_error=self.callback_error,
                                 on_completed=lambda: self.callback_completed("Coarse zeroing"))
        logger.info(f"Waiting for coarse zeroing to be complete")
        self.done.wait()
        self.done.clear()

        logger.info(f"Fine zeroing sensors {sensors}")
        self.fine_zero_sensors(sensors, on_next=self.callback_fine_zeroed, on_error=self.callback_error,
                               on_completed=lambda: self.callback_completed("Fine zeroing"))
        logger.info("Waiting for fine zeroing to be complete")
        self.done.wait()
        self.done.clear()

    def init_adcs(self, adcs: Union[bool, List]):
        chassis_list = [chassis_dict['chassis_id'] for chassis_dict in self.get_chassis_desc_dicts()]
        start_adc_on_chassis = []

        if isinstance(adcs, bool):
            if adcs:
                start_adc_on_chassis = chassis_list
        elif isinstance(adcs, list):
            start_adc_on_chassis = [chassis_id for chassis_id in adcs if chassis_id in chassis_list]

        if start_adc_on_chassis: logger.info(f"Starting ADCs on chassis {start_adc_on_chassis}")
        for chassis_id in start_adc_on_chassis:
            super().start_adc(chassis_id)

        stop_adc_on_chassis = list(set(chassis_list) - set(start_adc_on_chassis))
        if stop_adc_on_chassis: logger.info(f"Stopping ADCs on chassis {stop_adc_on_chassis}")
        for chassis_id in stop_adc_on_chassis:
            super().stop_adc(chassis_id)

        return start_adc_on_chassis

    def thread_stream_data(self):
        self.t_stream_start = pylsl.local_clock()
        last_heartbeat = self.t_stream_start
        logger.info(f"Starting to stream data on {self.stream_name} at t_local={self.t_stream_start}")

        while self.running:
            now = pylsl.local_clock()

            if self.log_heartbeat and last_heartbeat + self.log_heartbeat <= now:
                last_heartbeat = now
                logger.info(
                    f"Streaming data on {self.stream_name} since {now - self.t_stream_start:.1f} seconds (t_local={now})")
            try:
                data = self.data_queue.get(block=True, timeout=1)
            except Empty as e:
                logger.warning(
                    f"No data was received in time by streaming Thread after {now - self.t_stream_start:.1f} (t_local={now})")
                continue

            sample_timestamp = data['timestamp']  # We don't use this because LSL generates its own timestamps
            data_frames = data['data_frames']
            sample = [data_frames[channel_name]['data'] * self._calibration_dict[channel_name] for channel_name in
                      self.channel_names]

            try:
                timestamp = self.get_timestamp(sample_timestamp)
                self.stream_outlet.push_sample(sample, timestamp)
            except ValueError as e:
                logger.warning(f"Incoming sample had wrong dimensions:\n{e}")
                # Simply continue after an error because proper stream might come back

        stream_stop = pylsl.local_clock()

        logger.info(f"Stopping to stream on {self.stream_name} after {stream_stop - self.t_stream_start} seconds"
                    f" at t_local={stream_stop}")
        self.t_stream_start = None

    def get_timestamp(self, chassis_timestamp):
        return self.first_lsl_timestamp + (chassis_timestamp - self.first_chassis_timestamp) / 25000.0

    def start_streaming(self):
        if self.stream_outlet is None:
            self.init_stream()

        logger.info(f"Starting to read data from chassis")
        self.read_data(self.callback_data_available)

        logger.info(f"Starting streaming Thread")
        self.running = True
        self.streaming_thread = Thread(target=self.thread_stream_data,
                                       name=f"FieldLine LSL Streaming ({self.stream_name})")
        self.streaming_thread.start()

    def stop_streaming(self):
        if self.running:
            self.running = False
            self.read_data(data_callback=None)
            self.streaming_thread.join()
            logger.info(f"Stopped streaming")
        else:
            logger.warning(f"Streaming not running. Nothing to stop.")

    def init_stream(self):
        logger.info(f"Initializing LSL stream")
        self.build_stream_info()  # Will automatically set self.stream_info
        self.stream_outlet = pylsl.StreamOutlet(self.stream_info)

    def close(self):
        if self.running:
            self.stop_streaming()
        self.stream_info = None
        self.stream_outlet = None
        super().close()

    def get_sensors(self):
        return self.data_source.get_sensors()

    def get_channels(self):
        return [channel for sensor in self.get_sensors() for channel in sensor.get_channels()]

    def _set_channel_names(self):
        self._channel_names = [channel.name for channel in self.get_channels()]

    @property
    def channel_names(self):
        return self._channel_names

    def _set_calibration_dict(self):
        calibration_dict = dict()
        for channel in self.get_channels():
            calibration_value = channel.calibration
            if self.is_OPM_type(channel):
                calibration_value *= self.unit_T_factor

            calibration_dict[channel.name] = calibration_value
        self._calibration_dict = calibration_dict

    def build_stream_info(self):
        # Obtain the information we need to open an LSL stream:

        self.channel_count = len(self.get_channels())

        self.stream_info = pylsl.StreamInfo(self.stream_name, type=self.stream_type, channel_count=self.channel_count,
                                            nominal_srate=1000, channel_format=pylsl.cf_float32,
                                            source_id=self.source_id)

        desc = self.stream_info.desc()
        desc.append_child_value('manufacturer', "FieldLine Inc.")
        desc.append_child_value('fieldline_api-version', importlib.metadata.version('fieldline_api'))

        desc_chassis_all = desc.append_child("chassis")
        for chassis_dict in self.get_chassis_desc_dicts():
            desc_chassis_id = desc_chassis_all.append_child("chassis")
            for key, value in chassis_dict.items():
                desc_chassis_id.append_child_value(key, str(value))

        desc_channels = desc.append_child("channels")
        for channel_dict in self.get_channel_desc_dicts():
            desc_channel = desc_channels.append_child('channel')
            for key, value in channel_dict.items():
                desc_channel.append_child_value(key, str(value))

    def get_chassis_desc_dicts(self):
        chassis_dicts = []
        for chassis_name in self.data_source.get_chassis_names():
            chassis_id = self.data_source.chassis_name_to_id[chassis_name]
            chassis_dicts.append(self.get_chassis_desc_dict(chassis_id))

        chassis_dicts.sort(key=lambda chassis_dict: chassis_dict['chassis_id'])
        return chassis_dicts

    def get_chassis_desc_dict(self, chassis_id):
        return dict(
            name=self.data_source.get_chassis_name_from_id(chassis_id),
            chassis_id=chassis_id,
            serial=self.get_chassis_serial_number(chassis_id),
            version=self.get_version(chassis_id)
        )

    def get_channel_desc_dict(self, channel: ChannelInfo):
        chassis_id = channel.chassis_id
        sensor_id = channel.sensor_id

        channel_dict = dict(label=channel.name,
                            chassis_id=chassis_id,
                            sensor_id=sensor_id,
                            calibration=channel.calibration,
                            )

        if self.get_data_type(channel) == FieldLineDataType.ADC:
            channel_dict.update(unit="V", mode="ADC")
        elif self.get_data_type(channel) == FieldLineDataType.CLOSED_LOOP:
            channel_dict.update(unit=self.unit_T.name, mode="Closed Loop")
        elif self.get_data_type(channel) == FieldLineDataType.OPEN_LOOP:
            channel_dict.update(unit=self.unit_T.name, mode="Open Loop")
        else:
            channel_dict.update(unit="?", mode="Unknown")

        if self.is_OPM_type(channel):
            serial_card, serial_sensor = self.get_serial_numbers(chassis_id, sensor_id)
            field_X, field_Y, field_Z = self.get_fields(chassis_id, sensor_id)

            channel_dict.update(serial_card=serial_card,
                                serial_sensor=serial_sensor,
                                field_X=field_X, field_Y=field_Y, field_Z=field_Z,
                                location=channel.location,
                                unit_T_factor=self.unit_T_factor)

        return channel_dict

    def get_data_type(self, channel):
        try:
            return FieldLineDataType(channel.data_type)
        except ValueError:
            return None

    def is_OPM_type(self, channel):
        return self.get_data_type(channel) in [FieldLineDataType.CLOSED_LOOP, FieldLineDataType.OPEN_LOOP]

    def get_channel_desc_dicts(self):
        return [self.get_channel_desc_dict(channel) for channel in self.get_channels()]

    def callback_restarted(self, chassis_id, sensor_id):
        logger.debug(f"Sensor {chassis_id:02}:{sensor_id:02} restarted")

    def callback_coarse_zeroed(self, chassis_id, sensor_id):
        logger.debug(f"Sensor {chassis_id:02}:{sensor_id:02} coarse-zeroed")

    def callback_fine_zeroed(self, chassis_id, sensor_id):
        logger.debug(f"Sensor {chassis_id:02}:{sensor_id:02} fine-zeroed")

    def callback_error(self, chassis_id, sensor_id, err):
        logger.warning(f"Sensor {chassis_id:02}:{sensor_id:02} failed with {hex(err)}")

    def callback_completed(self, initialization_step_name: str):
        logger.info(f"{initialization_step_name} completed")
        self.done.set()

    def callback_data_available(self, data):
        # logger.debug(f"Received data: {data}")
        if self.first_lsl_timestamp is None:
            # In case we never received a data packet before, save the
            # chassis system timestamp of the sample as well as this device's
            # reference time
            self.first_lsl_timestamp = pylsl.local_clock()
            self.first_chassis_timestamp = data['timestamp']

        self.data_queue.put(data)
