#!/usr/bin/env python

"""Module documentation goes here"""

from pylsl import StreamInfo, StreamOutlet, cf_int32

from fieldline_api.fieldline_datatype import FieldLineDataType

class FieldLineStreamOutlet(StreamOutlet):
    nominal_srate = 1000
    chunk_size = 10
    type = 'MEG'
    channel_format = cf_int32

    def __init__(self, structure_sample, fConnector, name="FieldLineStream", source_id='flopm', adc=None, max_buffered=360):
        self.name = name
        self.source_id = source_id
        self.fConnector = fConnector

        self.channel_count = len(structure_sample.keys())

        chassis_ids = fConnector.get_chassis_ids()

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
        return f'FieldLine LSL-Stream "{self.streamName}" (source_id: {self.streamSourceId}) ' \
               f'{self.channel_count} channels'


    def getStreamInfo(self, sample):
        """
        Needs a data sample to determine channel names.
        Watch out, the Queue in fConnector usually returns a list of 10 data samples!
        """

        self.channel_count = len(sample.keys())

        stream_info = StreamInfo(name=self.name,
                                type=self.type, channel_count=self.channel_count,
                                nominal_srate=self.nominal_srate, channel_format=self.channel_format,
                                source_id=self.source_id)

        stream_info.desc().append_child_value('manufacturer', "FieldLine")

        channels = stream_info.desc().append_child("channels")

        for channel_name, channel_data in sample.items():
            ch = channels.append_child('channel')
            ch.append_child_value('label', channel_name)
            ch.append_child_value('unit', '?')
            ch.append_child_value('type', str(channel_data['data_type']))
            ch.append_child_value('data_type', str(channel_data['data_type']))
            ch.append_child_value('calibration', str(channel_data['calibration']))
            ch.append_child_value('sensor_idx', str(channel_data['idx']))
            ch.append_child_value('sensor_id', str(channel_data['sensor_id']))

        return stream_info

    def push_flchunk(self, samples, timestamp, pushthrough=True):
        x = [[ch_data['data'] for ch_data in sample.values()] for sample in samples]
        self.push_chunk(x, timestamp=timestamp, pushthrough=pushthrough)

