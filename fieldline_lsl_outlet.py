#!/usr/bin/env python

"""Module documentation goes here"""

from pylsl import StreamInfo, StreamOutlet, cf_int32, cf_float32

from fieldline_api.fieldline_datatype import FieldLineDataType
import numpy as np


class FieldLineStreamOutlet(StreamOutlet):
    nominal_srate = 1000
    chunk_size = 10
    type = 'MEG'
    # channel_format = cf_int32
    channel_format = cf_float32

    def __init__(self, structure_sample, fConnector, fService, name="FieldLineStream", source_id='flopm', adc=None, max_buffered=360):
        self.name = name
        self.source_id = source_id
        self.fConnector = fConnector
        self.fService = fService

        self.channel_count = len(structure_sample.keys())

        chassis_ids = list(fConnector.chassis_id_to_name.keys())

        if adc is None or adc is False:
            self.chassis_adcs = []
        elif adc is True or adc == 'all':
            self.chassis_adcs = chassis_ids
        else:
            self.chassis_adcs = adc

        self.structure_sample = structure_sample
        self.streamInfo = self.getStreamInfo(structure_sample)

        super().__init__(self.streamInfo, chunk_size=self.chunk_size, max_buffered=max_buffered)


    def __str__(self):
        return f'FieldLine LSL-Stream "{self.name}" (source_id: {self.source_id}) ' \
               f'{self.channel_count} channels'


    def getStreamInfo(self, sample):
        """
        Needs a data sample to determine channel names.
        Watch out, the Queue in fConnector usually returns a list of 10 data samples!
        """

        self.channel_count = len(sample.keys())
        # sample_timestamps = sample['timestamp']
        # sample_timestamp_lsl = sample['timestamp_lsl']
        sample_data_frames = sample['data_frames']

        self.channel_count = len(sample_data_frames)

        stream_info = StreamInfo(name=self.name,
                                type=self.type, channel_count=self.channel_count,
                                nominal_srate=self.nominal_srate, channel_format=self.channel_format,
                                source_id=self.source_id)

        stream_info.desc().append_child_value('manufacturer', "FieldLine")

        channels = stream_info.desc().append_child("channels")

        scaling_factors = []

        for data_frame_name, data_frame_data in sample_data_frames.items():
            ch = channels.append_child('channel')
            ch.append_child_value('label', data_frame_data['sensor'])
            # ch.append_child_value('unit', '?')

            type = data_frame_data['data_type']

            calibration_value = self.fService.get_calibration_value(data_frame_name)['calibration']  # for value in T/V

            if type == 0:
                # ADC channel
                scaling_factor = calibration_value
                unit = 'V'
                type_str = 'adc'
            elif type == 28 or type == 50:
                if type == 28:
                    type_str = 'opm_open'
                elif type == 50:
                    type_str = 'opm_closed'

                scaling_factor = calibration_value*1e12  # To unit fT
                unit = 'fT'

            ch.append_child_value('type', type_str)
            ch.append_child_value('unit', unit)
            scaling_factors.append(scaling_factor)

        self.scaling_factors = np.array(scaling_factors)

        return stream_info

    def push_flchunk(self, data_frames, timestamp, pushthrough=True):
        x = ([[frame['data'] for frame in data_frames.values()]]*self.scaling_factors).astype(np.float32).tolist()
        # x = [[ch_data['data'] for ch_data in sample.values()] for sample in samples]
        self.push_chunk(x, timestamp=timestamp, pushthrough=pushthrough)

