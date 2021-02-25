#!/usr/bin/env python

"""Module documentation goes here"""

import numpy as np
import matplotlib.pyplot as plt
import pickle

filename = 'samples_pulseadc_sinopm1hz.pkl'
# filename = 'samples_pulseadc.pkl'
# filename = 'samples_pulse1hz_startup.pkl'

with open(filename, 'rb') as fp:
    data = pickle.load(fp)

# opm = [sample['00:01:28']['data'] for samples in data for sample in samples]
opm = []
analog_in = []

for samples in data:
    for sample in samples:
        if True:
        # if '00:01:28' in sample:
        #     opm.append(sample['00:01:28']['data'])
            analog_in.append(sample['00:00:0']['data'])

# datarr = np.array([opm, analog_in]).transpose()
datarr = np.array([analog_in]).transpose()

plt.plot(datarr)