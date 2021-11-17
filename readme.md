# FieldLine LabStreamingLayer module

This is a script to automatically start and calibrate the FieldLine Optically Pumped Magnetometers and stream the data via [LabStreamingLayer](https://labstreaminglayer.readthedocs.io/). It requires python 3.9, the FieldLine API module (and all its requirements) as
well as [pylsl](https://pypi.org/project/pylsl/) for the streaming (see [requirements.txt](requirements.txt)).

Since version 0.3.0 there is no automatic discovery anymore so the ip addresses of the chassis have to be known (e.g., retrieve them from FieldLine Recorder).
The FieldLine Recorder can be used in parallel (from version 1.4.44), also for restarting and zeroing the sensors. Keep in mind that streaming will be interrupted when restarting or re-zeroing sensors during runtime.

There is not yet a way to selectively stream from some sensors. Sensors can be turned off in the FieldLine Recorder and streaming must be stopped, then they will not appear on the LSL stream when restart is skipped. A regular heartbeat is printed (default = 60 seconds). WHen multiple chassis are daisy-chained, all their IPs have to be provided (probably in order of chaining, not documented in FieldLine API).

Here is an example call to use the script:
```
python .\start_lsl_stream.py --chassis=192.168.2.43 --adc -t 600
```
This will connect only to the chassis at IP address 192.168.2.43 and stream all sensors as well as the analog channel 
data (`--adc`) for 600 seconds.
 

## Requirements
***If you use code from this repository in your publication or project, I ask you to give credit for my work by citing our paper and 
link to this repo so others can benefit too:***

J. Zerfowski, T. H. Sander, M. Tangermann, S. R. Soekadar, and T. Middelmann (2021). Real-Time Data Processing for Brain-Computer Interfacing using Optically Pumped Magnetometers. International Journal of Bioelectromagnetism. Vol. 23, No. 1, pp. 14/1 - 6.
[link to pdf](http://www.ijbem.org/volume23/number2/14.pdf)

- Requirements are listed in [requirements.txt](requirements.txt)
- python >= 3.9
- fieldline_api >= 0.3.1
- [pylsl](https://pypi.org/project/pylsl/)


## Command line arguments
Use `python .\start_lsl_stream.py -h` to view this

```
usage: start_lsl_stream.py [-h] -c CHASSIS [--not-skip-restart]
                           [--not-skip-zeroing] [--adc] [-n STREAM_NAME]
                           [-id STREAM_ID] [-t DURATION]
                           [--heartbeat HEARTBEAT] [-v]

optional arguments:
  -h, --help            show this help message and exit
  -c CHASSIS, --chassis CHASSIS
                        Connect to chassis ip(s).
  --not-skip-restart    If set, all sensors will be restarted automatically
  --not-skip-zeroing    If set, all sensors will be coarse- and fine-zeroed
                        automatically before streaming
  --adc                 Activate ADC Streams
  -n STREAM_NAME, --stream_name STREAM_NAME
                        Name of the LSL Stream
  -id STREAM_ID, --stream_id STREAM_ID
                        Unique ID of the LSL Stream
  -t DURATION, --duration DURATION
                        Duration (in seconds) for the stream to run. Infinite
                        if not given
  --heartbeat HEARTBEAT
                        Heartbeat to print every n seconds when streaming data
  -v, --verbose         Logging verbosity. Repeat up to three times. Defaults
                        to only script info being printed
```

## Good to know
Sensors != Channels. In principle, there is currently a 1:1 association, but a sensor (e.g. 00:01) can have different channels (:28 or :50) depending on the mode it's run in.