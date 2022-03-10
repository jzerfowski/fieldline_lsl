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

import time
from enum import Enum
from queue import Queue, Empty
from typing import Union, List
import logging
from threading import Event, Thread
import importlib.metadata

import pylsl

from fieldline.fieldline_api.fieldline_service import FieldLineService
from fieldline.pycore.sensor import ChannelInfo

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
    T = 1  # Tesla
    mT = 1E3  # milliTesla
    uT = 1E6  # microTesla
    nT = 1E9  # nanoTesla
    pT = 1E12  # picoTesla
    fT = 1E15  # femtoTesla


class FieldLineLSL(FieldLineService):
    """
    Instance of FieldLineService to enable streaming of data via LSL
    Initialized with all relevant information for connecting to one or multiple (daisy-chained) chassis.
    See the readme for further information
    """
    def __init__(self, ip_list: List[str], stream_name: str = "FieldLineOPM", source_id: str = "FieldLineOPM_sid",
                 stream_type='MAG', log_heartbeat: int = 60, unit_T: Unit_T_Factor = Unit_T_Factor.fT, prefix: str = "",):
        """
        Initialize the FieldLineLSL instance
        :param ip_list: List of ip addresses as strings (without ports)
        :param stream_name: Name of the LSL Stream to open
        :param source_id: Source id of the LSL Stream to open
        :param stream_type: Type of LSL Stream, default (some software can only properly handle "EEG" streams)
        :param log_heartbeat: How often a "heartbeat" should be logged to the console, in seconds. Logs nothing if set to 0
        :param unit_T: Unit of the streamed OPM data (default is femtoTesla (fT))
        :param prefix: prefix for use in FieldLineService (not documented in FieldLine API)
        """
        super().__init__(ip_list=ip_list, prefix=prefix)

        # LSL Information provided by user
        self.stream_name: str = stream_name
        self.source_id: str = source_id

        # LSL Information filled after zeroing
        self.channel_count: int = None
        self.stream_type: str = stream_type
        self.stream_info: pylsl.StreamInfo = None
        self.stream_outlet: pylsl.StreamOutlet = None

        self._channel_names: list = None  # set in self._build_channel_names()

        if unit_T not in Unit_T_Factor:
            logger.warning(f"{unit_T=} is not a known unit. Please provide an instance of {Unit_T_Factor}")
            self.unit_T: Unit_T_Factor = Unit_T_Factor.T
        else:
            self.unit_T: Unit_T_Factor = unit_T
        self.unit_T_factor = self.unit_T.value

        # Internal flags and objects for multithreading
        self.done: Event = Event()
        self.data_queue: Queue = Queue()

        self.streaming_thread: Thread = None
        self.running: bool = False

        self._calibration_dict: dict = None  # Calibration values of all channels to compute data in correct unit

        self.log_heartbeat: int = log_heartbeat
        self.t_stream_start: int = None

        self.first_lsl_timestamp = None  # Timestamp of pylsl.local_clock() to sync with chassis_timestamps
        self.first_chassis_timestamp = None  # FieldLine chassis system's timestamp of first dataframe to arrive

    def init_sensors(self, skip_restart: bool = True, skip_zeroing: bool = True, closed_loop_mode: bool = True,
                     adcs: Union[bool, List[int]] = False):
        """
        Initialize the sensors. Steps can be skipped if the sensors already are zeroed or this is done in parallel using
        the FieldLine Recorder
        :param skip_restart: Skip the restart of the sensors
        :param skip_zeroing: Skip both zeroing steps of the sensors (only skip when restart is also skipped!)
        :param closed_loop_mode: If true, sets the sensors to closed loop mode
        :param adcs: If True: turn on all ADCs. if list of integers (chassis_ids): Turn ADCs on for these ids. if False:
            Do not turn on adcs.
        """
        connect_to_sensor_dict = self.load_sensors()

        logger.info(f"Initializing sensors {connect_to_sensor_dict}")
        if not skip_restart:
            self.restart_sensors(connect_to_sensor_dict)

        self.set_closed_loop(closed_loop_mode)  # This is blocking until closed_loop is set

        if not skip_zeroing:
            self.zero_sensors(connect_to_sensor_dict)

        self.init_adcs(adcs)

        self._build_channel_names()
        self._set_calibration_dict()

    def init_adcs(self, adcs: Union[bool, List[int]]):
        """
        Initialize the ADCs, called automatically by init_sensors()
        :param adcs:
        :return:
        """
        chassis_list = [chassis_dict['chassis_id'] for chassis_dict in self.get_chassis_desc_dicts()]
        start_adc_on_chassis = []

        if isinstance(adcs, bool):
            if adcs:
                start_adc_on_chassis = chassis_list
        elif isinstance(adcs, list):
            start_adc_on_chassis = [chassis_id for chassis_id in adcs if chassis_id in chassis_list]

        for chassis_id in start_adc_on_chassis:
            logger.info(f"Starting ADCs on chassis {chassis_id}")
            super().start_adc(chassis_id)

        stop_adc_on_chassis = list(set(chassis_list) - set(start_adc_on_chassis))

        for chassis_id in stop_adc_on_chassis:
            logger.info(f"Stopping ADCs on chassis {chassis_id}")
            super().stop_adc(chassis_id)

        if start_adc_on_chassis or stop_adc_on_chassis:
            # starting and stopping adcs seems to be non-blocking
            time.sleep(0.5)

        return start_adc_on_chassis

    def init_stream(self):
        """
        Initialize the LSL stream
        """
        logger.info(f"Initializing LSL stream")
        self.build_stream_info()  # Will automatically set self.stream_info
        self.stream_outlet = pylsl.StreamOutlet(self.stream_info)

    def restart_sensors(self, sensors: dict):
        """
        Dictionary of sensors to restart
        :param sensors: dictionary of {chassis_id: [list of sensor_ids], ...}
        """
        logger.info(f"Restarting sensors {sensors}")
        super().restart_sensors(sensors, on_next=self.callback_restarted, on_error=self.callback_error,
                                on_completed=lambda: self.callback_completed("Restart"))
        logger.info(f"Waiting for restart to be complete")

        self.done.wait()
        self.done.clear()

    def turn_off_sensors(self, sensors: dict):
        """
        Dictionary of sensors to turn off
        :param sensors: dictionary of {chassis_id: [list of sensor_ids], ...}
        """
        logger.info(f"Turning off sensors {sensors}")
        super().turn_off_sensors(sensors)
        logger.info(f"Turned off sensors {sensors}")

    def zero_sensors(self, sensors: dict):
        """
        Dictionary of sensors to perform field-zeroing on
        :param sensors: dictionary of {chassis_id: [list of sensor_ids], ...}
        """
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

    def start_streaming(self):
        """
        Start the LSL streaming. Non-blocking!
        :return:
        """
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
        """
        Stop the LSL streaming. Blocks until streaming is stopped
        :return:
        """
        if self.running:
            self.running = False
            self.read_data(data_callback=None)
            self.streaming_thread.join()
            logger.info(f"Stopped streaming")
        else:
            logger.warning(f"Streaming not running. Nothing to stop.")

    def close(self):
        """
        Close the StreamOutlet and FieldLineService
        :return:
        """
        if self.running:
            self.stop_streaming()
        self.stream_info = None
        self.stream_outlet = None
        super().close()

    def thread_stream_data(self):
        """
        Stream the incoming data on the LSL stream until self.running is set to False
        :return:
        """
        self.t_stream_start = pylsl.local_clock()
        next_heartbeat = self.t_stream_start
        logger.info(f"Starting to stream data on {self.stream_name} at t_local={self.t_stream_start}")

        while self.running:
            now = pylsl.local_clock()

            if self.log_heartbeat and now >= next_heartbeat:
                next_heartbeat += self.log_heartbeat
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

    def _set_calibration_dict(self):
        calibration_dict = dict()
        for channel in self.get_channels():
            calibration_value = channel.calibration
            if self.is_OPM_type(channel):
                calibration_value *= self.unit_T_factor

            calibration_dict[channel.name] = calibration_value
        self._calibration_dict = calibration_dict

    def build_stream_info(self):
        """
        Obtain the information needed to open an lsl stream and write a
        StreamInfo object immediately into self.stream_info.
        """
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
        """
        Return a list of all chassis_desc dictionaries (see get_chassis_desc_dict()) connected to this service
        """
        chassis_dicts = []
        for chassis_name in self.data_source.get_chassis_names():
            chassis_id = self.data_source.chassis_name_to_id[chassis_name]
            chassis_dicts.append(self.get_chassis_desc_dict(chassis_id))

        chassis_dicts.sort(key=lambda chassis_dict: chassis_dict['chassis_id'])
        return chassis_dicts

    def get_chassis_desc_dict(self, chassis_id):
        """
        Return a dictionary containing name, id, serial and version of the chassis with id chassis_id
        """
        return dict(
            name=self.data_source.get_chassis_name_from_id(chassis_id),
            chassis_id=chassis_id,
            serial=self.get_chassis_serial_number(chassis_id),
            version=self.get_version(chassis_id)
        )

    def get_channel_desc_dict(self, channel: ChannelInfo):
        """
        Return a  dictionary containing name (label), data type, calibration values and more of a sensor.
        :param channel: ChannelInfo object as returned by self.data_source.get_sensors()[].get_channels()[]
        :return: dictionary with information about a channel
        """
        chassis_id = channel.chassis_id
        sensor_id = channel.sensor_id

        channel_dict = dict(label=channel.name,
                            chassis_id=chassis_id,
                            sensor_id=sensor_id,
                            calibration=channel.calibration,
                            )

        if self.get_data_type(channel) == FieldLineDataType.ADC:
            channel_dict.update(type='misc', unit="V", mode="ADC")
        elif self.get_data_type(channel) == FieldLineDataType.CLOSED_LOOP:
            channel_dict.update(type='mag', unit=self.unit_T.name, mode="Closed Loop")
        elif self.get_data_type(channel) == FieldLineDataType.OPEN_LOOP:
            channel_dict.update(type='mag', unit=self.unit_T.name, mode="Open Loop")
        else:
            channel_dict.update(type='misc', unit="?", mode="Unknown")

        if self.is_OPM_type(channel):
            serial_card, serial_sensor = self.get_serial_numbers(chassis_id, sensor_id)
            field_X, field_Y, field_Z = self.get_fields(chassis_id, sensor_id)

            channel_dict.update(serial_card=serial_card,
                                serial_sensor=serial_sensor,
                                field_X=field_X, field_Y=field_Y, field_Z=field_Z,
                                location=channel.location,
                                unit_T_factor=self.unit_T_factor)

        return channel_dict

    def get_data_type(self, channel: ChannelInfo):
        """
        Return the datatype according to channel.data_type
        :param channel:
        :return:
        """
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
        if self.first_lsl_timestamp is None:
            # If this is the first sample, save the chassis system timestamp and this device's reference time
            # this is used in self.get_timestamp()
            self.first_lsl_timestamp = pylsl.local_clock()
            self.first_chassis_timestamp = data['timestamp']

        self.data_queue.put(data)

    def get_timestamp(self, chassis_timestamp):
        """
        Transform a chassis system timestamp into an pylsl.local_clock() timestamp
        Uses 25000 because the clock on FieldLine chassis is 25 MHz and sfreq is 1 kHz.
        :param chassis_timestamp:
        :return:
        """
        return self.first_lsl_timestamp + (chassis_timestamp - self.first_chassis_timestamp) / 25000.0

    def get_sensors(self):
        return self.data_source.get_sensors()

    def get_channels(self):
        return [channel for sensor in self.get_sensors() for channel in sensor.get_channels()]

    def _build_channel_names(self):
        """
        Sets self._channel_names to have a fixed list of channels
        :return:
        """
        self._channel_names = [channel.name for channel in self.get_channels()]

    @property
    def channel_names(self):
        return self._channel_names
