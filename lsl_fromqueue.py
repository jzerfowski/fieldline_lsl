#!/usr/bin/env python

"""Module documentation goes here"""

import time
import pickle
import queue
import logging
logging.basicConfig(level=logging.INFO)

from pylsl import StreamInfo, StreamOutlet, local_clock
import numpy as np
import matplotlib.pyplot as plt

data = pickle.load(open('sample_queue_content.pkl', 'rb'))
data_q = queue.Queue()


for samples in data:
    data_q.put(samples)

srate = 1000
name = 'FieldLineOPM'
type = 'MEG'
# channel_names = fConnector.all_sensors_list()
channel_names = ['00:01:28', '00:02:28', '00:03:28']

info = StreamInfo(name=name, type=type, channel_count=len(channel_names), nominal_srate=srate, channel_format='int32', source_id='flopm')
info.desc().append_child_value('manufacturer', "FieldLine")
chns = info.desc().append_child("channels")
for label in channel_names:
    ch = chns.append_child('channel')
    ch.append_child_value('label', label)
    ch.append_child_value('unit', '?')
    ch.append_child_value('type', 'MEG')
    ch.append_child_value('data_type', '28')

outlet = StreamOutlet(info, chunk_size=1, max_buffered=50)

while True:
    try:
        samples = data_q.get(True, 0.01)
        logging.info("DATA %s" % samples)

        stamp = local_clock()
        lsldata = [[ch_data['data'] for ch_data in sample.values()] for sample in samples]
        outlet.push_chunk(lsldata, stamp)

        time.sleep(0.01)
        time.sleep(0.01)

    except queue.Empty:
        continue

    data_q.put(samples)