#!/usr/bin/env python

"""Module documentation goes here"""

import numpy as np
import matplotlib.pyplot as plt
import pickle

with open('../data/samples_queue_v13.pkl', 'rb') as fp:
    chunks = pickle.load(fp)

##
t = np.array([d['timestamp'] for d in chunks])
x = np.arange(len(t))

# plt.plot(x, t)
plt.scatter(x[:-1], np.diff(t), s=0.3)
plt.axhline(0.01, label="10ms", c='k')
plt.legend()

## Check if timestamps for each sensor sample are the same
def check_sensor_timestamps_equal(sample):
    keys = list(sample.keys())
    t0 = sample[keys[0]]['timestamp']
    for key in keys[1:]:
        if t0 != sample[key]['timestamp']:
            print(False)

t_samples = []
for d in chunks[:100]:
    samples = d['samples']
    for sample in samples:
        check_sensor_timestamps_equal(sample)

        t_samples.append(sample[list(sample.keys())[0]]['timestamp'])
