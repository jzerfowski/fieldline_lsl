#!/usr/bin/env python

"""Module documentation goes here"""

import numpy as np
import matplotlib.pyplot as plt
from pylsl import StreamInfo, StreamOutlet

from fieldline_api.fieldline_datatype import FieldLineDataType

class FieldLineLSL(StreamOutlet):
    streamSamplingRate = 1000
    streamType = 'MEG'
    channel_format = 'int32'

    def __init__(self, fConnector, sample, name="FieldLineStream", source_id='flopm', adc=False, chunk_size=10, max_buffered=360):
        self.fConnector = fConnector
        self.streamName = name
        self.streamSourceId = source_id
        self.adc = adc

        self.channel_count = len(sample.keys())

        self.streamInfo = self.getStreamInfo(sample)

        super().__init__(self.streamInfo, chunk_size=chunk_size, max_buffered=max_buffered)

    def __str__(self):
        return f'FieldLine LSL-Stream "{self.streamName}" (source_id: {self.streamSourceId}) ' \
               f'{self.channel_count} Channels. ADC {"On" if self.adc else "Off"}'

    def getStreamInfo(self, sample):
        """
        Needs a data sample to determine channel names.
        Watch out, the Queue in fConnector usually returns a list of 10 data samples!
        """
        streamInfo = StreamInfo(name=self.streamName, type=self.streamType, channel_count=self.channel_count, nominal_srate=self.streamSamplingRate,
                                channel_format=self.channel_format, source_id=self.streamSourceId)
        streamInfo.desc().append_child_value('manufacturer', "FieldLine")

        channels = streamInfo.desc().append_child("channels")

        for channel_name, channel_data in sample.items():
            ch = channels.append_child('channel')
            ch.append_child_value('label', channel_name)
            ch.append_child_value('unit', '?')
            ch.append_child_value('type', str(channel_data['data_type']))
            ch.append_child_value('data_type', str(channel_data['data_type']))
            ch.append_child_value('calibration', str(channel_data['calibration']))
            ch.append_child_value('sensor_idx', str(channel_data['idx']))
            ch.append_child_value('sensor_id', str(channel_data['sensor_id']))

        return streamInfo


