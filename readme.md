# FieldLine LSL module

This is a script to automatically startup the FieldLine OPM sensors (V2) and stream the data
via [LSL](https://labstreaminglayer.readthedocs.io/). It requires the FieldLine API module (and all its requirements) as
well as [pylsl](https://pypi.org/project/pylsl/) for the streaming.

If no additional arguments are provided, the script connects to all discovered chassis on the network and attempts to
restart->coarse-zero->fine-zero all sensors. When sensors fail during startup, the streaming is started with remaining
sensors. The stream runs forever if no `-t` argument is given.

During startup, the logging gives indications about the state of the system. Verbosity can be modified with `-v` 
such that more information is printed on the console.
After the startup is finished and the streaming started, every 10 seconds a 'heartbeat' is printed to inform the 
user that the stream is still running:

`Streaming data on FieldLineOPM (flopm) since ... seconds`

Here is an example call to use the script:
```
python .\start_lsl_stream.py --chassis=192.168.2.43 --adc -t 600
```
This will connect only to the chassis at IP address 192.168.2.43 and stream all sensors as well as the analog channel 
data (`--adc`) for 600 seconds.
 

## Command line arguments
Use `python .\start_lsl_stream.py -h` to view this

```
usage: start_lsl_stream.py [-h] [-v] [-c CHASSIS] [--init_timeout INIT_TIMEOUT] [--adc] [-n SNAME] [-id SID]
                           [-t DURATION] [--disable-restart]

optional arguments:
  -h, --help            show this help message and exit
  -v, --verbose         Logging verbosity. Repeat up to three times. Defaults to only script info being printed
  -c CHASSIS, --chassis CHASSIS
                        Connect to chassis ip(s). Can be omitted or given multiple times
  --init_timeout INIT_TIMEOUT
                        Timeout (in s) of initialization sequence (restart and coarse zeroing). Defaults to 1 hour
  --adc                 Activate ADC Streams
  -n SNAME, --sname SNAME
                        Name of the LSL Stream
  -id SID, --sid SID    Unique ID of the LSL Stream
  -t DURATION, --duration DURATION
                        Duration (in seconds) for the stream to run. Infinite if not given
  --disable-restart     Disables restarting sensors before zeroing to save time. Will fail if sensors were not already
                        started
```

## Requirements

- fieldline_api (0.0.13)
- [pylsl](https://pypi.org/project/pylsl/)

## Details

The restarting and zeroing of the sensors is mostly copied from the api-example scripts. However, restarting can be
disabled to save time when the sensors are already ready for field-zeroing.

When sensors fail during field-zeroing, often `soft error` appears somewhere in the console output (not necessarily 
the very last message).

Since it is unknown how many sensors are connected and started successfully, the script starts the data streaming from
the sensors before the LSL stream is opened. From the first samples it receives then the number of channel and meta data
of the stream can be inferred. This info is used to generate the LSL Info object with which the LSLOutput can be opened.

The fConnector-queue is then emptied after opening the LSL Outlet to avoid 'old' samples in the queue.
Approx. every 10 seconds (every 1000 chunks: 10 samples/chunk @1000 Hz sampling rate), the user is notified about 
the runtime and the remaining time. 

## TODO

- Only print script logging info to the console with speaking messages, rather than all API info messages
- Make sure that failing sensor messages are printed prominently to not pass unnoticed