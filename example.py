#!/usr/bin/env python

"""Example script with minimal configuration to start a LabStreamingLayer stream
from FieldLine's Optically Pumped Magnetometers"""
from FieldLineLSL import FieldLineLSL, logger as fieldline_logger

import logging
fieldline_logger.setLevel(logging.DEBUG)


if __name__ == '__main__':
    ip_list = ['192.168.2.43', '192.168.2.44']

    fLSL = FieldLineLSL(ip_list, stream_name="FieldLineOPM", source_id="FieldlineLSL_")

    fLSL.open()
    fLSL.init_sensors(skip_restart=True, skip_zeroing=True, closed_loop_mode=True, adcs=False)
    fLSL.init_stream()

    fLSL.start_streaming()