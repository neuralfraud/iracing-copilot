"""Turns a lap's raw telemetry samples (from TelemetryLogger) into compact,
labeled evidence for the LLM diagnosis step - not a raw time-series dump.

The signals here are well-known, practical driver/engineer heuristics
(corner segmentation off lateral G, brake lock-up detection, steering-vs-
rotation "tells" for under/oversteer, tire temp spread). They are
simplified proxies, not a vehicle-dynamics model - treat the output as
evidence for an LLM (or a human) to reason over, not ground truth.
"""

from dataclasses import asdict, dataclass, field
from typing import List, Optional

LAT_ACCEL_CORNER_THRESHOLD = 4.0    # m/s^2, sustained above this = "in a corner"
MIN_CORNER_SAMPLES = 5              # drop single-tick noise blips
STEERING_REVERSAL_THRESHOLD = 0.02  # rad, ignore tiny steering noise when counting reversals
THROTTLE_REVERSAL_THRESHOLD = 0.05  # 0-1 scale


@dataclass
class CornerFeatures:
    start_idx: int
    end_idx: int
    lap_dist_pct_start: Optional[float]
    lap_dist_pct_end: Optional[float]
    entry_speed: Optional[float]
    apex_speed: Optional[float]
    exit_speed: Optional[float]
    max_lat_accel: Optional[float]
    brake_peak: float
    lockup_detected: bool
    trail_braking: bool
    steering_reversals: int
    throttle_reversals: int
    balance_hint: str  # "possible_understeer" | "possible_oversteer" | "neutral"


@dataclass
class TireTempFeatures:
    lf_avg: Optional[float]
    rf_avg: Optional[float]
    lr_avg: Optional[float]
    rr_avg: Optional[float]
    # Spread across each tire's two tread-edge carcass temps (CL vs CR).
    # A nonzero spread is a real camber/pressure-balance tell either way,
    # but iRacing's CL/CR -> inboard/outboard mapping differs between the
    # left and right side of the car, so don't assume which sign means
    # "too much" vs "too little" camber without checking for this specific car.
    lf_spread: Optional[float]
    rf_spread: Optional[float]
    lr_spread: Optional[float]
    rr_spread: Optional[float]
    front_rear_balance: Optional[float]  # avg(front) - avg(rear)
    left_right_balance: Optional[float]  # avg(left) - avg(right)


@dataclass
class LapFeatures:
    lap_number: Optional[int]
    sample_count: int
    corners: List[CornerFeatures] = field(default_factory=list)
    tire_temps: Optional[TireTempFeatures] = None

    def to_dict(self):
        return asdict(self)


def extract_lap_features(samples):
    """samples: list of TelemetrySample dicts for one lap, in order (as
    returned by TelemetryLogger.get_lap/get_current_lap/get_last_completed_lap)."""
    if not samples:
        return LapFeatures(lap_number=None, sample_count=0)

    return LapFeatures(
        lap_number=samples[0].get("Lap"),
        sample_count=len(samples),
        corners=_segment_corners(samples),
        tire_temps=_tire_temp_features(samples),
    )


def _segment_corners(samples):
    """Split the lap into corner regions using sustained lateral G."""
    regions = []
    in_corner = False
    start = None

    for i, s in enumerate(samples):
        lat = s.get("LatAccel")
        magnitude = abs(lat) if lat is not None else 0.0

        if magnitude >= LAT_ACCEL_CORNER_THRESHOLD:
            if not in_corner:
                in_corner = True
                start = i
        elif in_corner:
            in_corner = False
            if i - start >= MIN_CORNER_SAMPLES:
                regions.append((start, i - 1))
            start = None

    if in_corner and len(samples) - start >= MIN_CORNER_SAMPLES:
        regions.append((start, len(samples) - 1))

    return [_corner_features(samples, start, end) for start, end in regions]


def _corner_features(samples, start, end):
    window = samples[start:end + 1]

    speeds = _values(window, "Speed")
    lat_accels = [abs(v) for v in _values(window, "LatAccel")]
    brakes = _values(window, "Brake")
    steering = _values(window, "SteeringWheelAngle")
    throttle = _values(window, "Throttle")
    lockups = [bool(s["BrakeABSactive"]) for s in window if "BrakeABSactive" in s]

    return CornerFeatures(
        start_idx=start,
        end_idx=end,
        lap_dist_pct_start=window[0].get("LapDistPct"),
        lap_dist_pct_end=window[-1].get("LapDistPct"),
        entry_speed=speeds[0] if speeds else None,
        apex_speed=min(speeds) if speeds else None,
        exit_speed=speeds[-1] if speeds else None,
        max_lat_accel=max(lat_accels) if lat_accels else None,
        brake_peak=max(brakes) if brakes else 0.0,
        lockup_detected=any(lockups),
        trail_braking=_has_trail_braking(window),
        steering_reversals=_count_reversals(steering, STEERING_REVERSAL_THRESHOLD),
        throttle_reversals=_count_reversals(throttle, THROTTLE_REVERSAL_THRESHOLD),
        balance_hint=_balance_hint(window),
    )


def _values(window, key):
    return [s[key] for s in window if s.get(key) is not None]


def _has_trail_braking(window):
    """True if the brake is still applied while the car is already committed
    to the corner (steering held off-center) - i.e. braking into the turn
    rather than only in a straight line before it."""
    for s in window:
        brake = s.get("Brake")
        steering = s.get("SteeringWheelAngle")
        if brake is not None and steering is not None and brake > 0.05 and abs(steering) > 0.1:
            return True
    return False


def _count_reversals(values, threshold):
    """Counts direction reversals in a trace above a noise threshold - a
    proxy for how much the driver is correcting/modulating (steering), or
    how unsettled the car is (throttle)."""
    reversals = 0
    direction = 0
    prev = None
    for v in values:
        if prev is not None:
            delta = v - prev
            if abs(delta) >= threshold:
                new_direction = 1 if delta > 0 else -1
                if direction != 0 and new_direction != direction:
                    reversals += 1
                direction = new_direction
        prev = v
    return reversals


def _balance_hint(window):
    """Simplified understeer/oversteer tell (not a vehicle-dynamics model):

    - oversteer tell: steering crosses to the opposite sign from how the
      corner started (a countersteer correction) while yaw rate is still at
      or above where it started - the car rotated more than commanded and
      the driver caught a slide.
    - understeer tell: steering magnitude grows through the corner while yaw
      rate magnitude does not grow with it - the car isn't turning as much
      as asked, so the driver keeps adding lock.
    """
    steering = [s.get("SteeringWheelAngle") for s in window]
    yaw = [s.get("YawRate") for s in window]

    if len(steering) < 2 or any(v is None for v in steering) or any(v is None for v in yaw):
        return "neutral"

    initial_steering_positive = steering[0] >= 0

    for i in range(1, len(steering)):
        crossed = (steering[i] >= 0) != initial_steering_positive and abs(steering[i]) > 0.05
        if crossed and abs(yaw[i]) >= abs(yaw[0]):
            return "possible_oversteer"

    steering_growth = abs(steering[-1]) - abs(steering[0])
    yaw_growth = abs(yaw[-1]) - abs(yaw[0])
    if steering_growth > 0.05 and yaw_growth <= 0.0:
        return "possible_understeer"

    return "neutral"


def _tire_temp_features(samples):
    last = samples[-1]

    lf_avg = _mean_ignore_none(last.get("LFtempCL"), last.get("LFtempCM"), last.get("LFtempCR"))
    rf_avg = _mean_ignore_none(last.get("RFtempCL"), last.get("RFtempCM"), last.get("RFtempCR"))
    lr_avg = _mean_ignore_none(last.get("LRtempCL"), last.get("LRtempCM"), last.get("LRtempCR"))
    rr_avg = _mean_ignore_none(last.get("RRtempCL"), last.get("RRtempCM"), last.get("RRtempCR"))

    if all(v is None for v in (lf_avg, rf_avg, lr_avg, rr_avg)):
        return None

    return TireTempFeatures(
        lf_avg=lf_avg, rf_avg=rf_avg, lr_avg=lr_avg, rr_avg=rr_avg,
        lf_spread=_subtract_if_both(last.get("LFtempCL"), last.get("LFtempCR")),
        rf_spread=_subtract_if_both(last.get("RFtempCL"), last.get("RFtempCR")),
        lr_spread=_subtract_if_both(last.get("LRtempCL"), last.get("LRtempCR")),
        rr_spread=_subtract_if_both(last.get("RRtempCL"), last.get("RRtempCR")),
        front_rear_balance=_subtract_if_both(
            _mean_ignore_none(lf_avg, rf_avg), _mean_ignore_none(lr_avg, rr_avg)
        ),
        left_right_balance=_subtract_if_both(
            _mean_ignore_none(lf_avg, lr_avg), _mean_ignore_none(rf_avg, rr_avg)
        ),
    )


def _mean_ignore_none(*values):
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _subtract_if_both(a, b):
    return a - b if a is not None and b is not None else None
