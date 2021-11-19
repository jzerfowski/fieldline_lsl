#!/usr/bin/env python

"""Example script with minimal configuration to start a LabStreamingLayer stream
from FieldLine's Optically Pumped Magnetometers"""
from FieldLineLSL import FieldLineLSL, logger as fieldline_logger

import logging
fieldline_logger.setLevel(logging.INFO)


if __name__ == '__main__':
    ip_list = ['192.168.2.43', '192.168.2.44']

    fLSL = FieldLineLSL(ip_list, stream_name="FieldLineOPM", source_id="FieldlineLSL_1_4_41")

    fLSL.open()
    fLSL.init_sensors(skip_restart=False, skip_zeroing=False, closed_loop_mode=True, adcs=False)
    fLSL.init_stream()

    fLSL.start_streaming()