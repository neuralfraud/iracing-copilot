"""Default telemetry channels to log for driving/setup-feedback analysis.

Names come from pyirsdk's documented var list:
https://github.com/kutu/pyirsdk/blob/master/vars.txt

Some cars expose additional car-specific channels (brake bias, wing
adjustments, etc.) that aren't in this base list - inspect
`ir.var_headers_names` at runtime to discover those for a given car.
"""

DEFAULT_CHANNELS = [
    # session / timing
    "SessionTime", "SessionNum", "Lap", "LapCompleted", "LapDist", "LapDistPct",
    "OnPitRoad", "IsOnTrack",

    # driver inputs
    "Speed", "RPM", "Gear", "Throttle", "Brake", "BrakeABSactive", "SteeringWheelAngle",

    # chassis/handling signature
    "LatAccel", "LongAccel", "VertAccel", "YawRate",

    # fuel
    "FuelLevel",

    # tire carcass temps (handling balance proxy)
    "LFtempCL", "LFtempCM", "LFtempCR",
    "RFtempCL", "RFtempCM", "RFtempCR",
    "LRtempCL", "LRtempCM", "LRtempCR",
    "RRtempCL", "RRtempCM", "RRtempCR",

    # tire pressures as set in the garage (cold)
    "LFcoldPressure", "RFcoldPressure", "LRcoldPressure", "RRcoldPressure",
]
