import json
import math


AXES = (
    ("x", (1.0, 0.0, 0.0)),
    ("y", (0.0, 1.0, 0.0)),
    ("z", (0.0, 0.0, 1.0)),
)


def _clean_float(value, digits=6):
    rounded = round(float(value), digits)
    return 0.0 if abs(rounded) < 10 ** -digits else rounded


def normalize_quaternion(quaternion):
    w, x, y, z = [float(value) for value in quaternion]
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm == 0:
        raise ValueError("Quaternion norm cannot be zero")
    return [w / norm, x / norm, y / norm, z / norm]


def quaternion_to_rotation_matrix(quaternion):
    w, x, y, z = normalize_quaternion(quaternion)
    return [
        [
            1 - 2 * (y * y + z * z),
            2 * (x * y - z * w),
            2 * (x * z + y * w),
        ],
        [
            2 * (x * y + z * w),
            1 - 2 * (x * x + z * z),
            2 * (y * z - x * w),
        ],
        [
            2 * (x * z - y * w),
            2 * (y * z + x * w),
            1 - 2 * (x * x + y * y),
        ],
    ]


def quaternion_to_axes(quaternion):
    matrix = quaternion_to_rotation_matrix(quaternion)
    axes = {}
    for index, (name, _) in enumerate(AXES):
        axes[name] = [
            _clean_float(matrix[0][index]),
            _clean_float(matrix[1][index]),
            _clean_float(matrix[2][index]),
        ]
    return axes


def quaternion_to_euler_zyx_deg(quaternion):
    w, x, y, z = normalize_quaternion(quaternion)
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    pitch_arg = 2 * (w * y - z * x)
    pitch_arg = max(-1.0, min(1.0, pitch_arg))
    pitch = math.asin(pitch_arg)
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    return {
        "yaw": _clean_float(math.degrees(yaw)),
        "pitch": _clean_float(math.degrees(pitch)),
        "roll": _clean_float(math.degrees(roll)),
    }


def build_orientation_payload(sample_index, time_sec, node_quaternions, hip_metrics=None):
    nodes = {}
    for node_name, quaternion in node_quaternions.items():
        normalized = normalize_quaternion(quaternion)
        nodes[node_name] = {
            "quaternion": [_clean_float(value) for value in normalized],
            "euler_deg": quaternion_to_euler_zyx_deg(normalized),
            "axes": quaternion_to_axes(normalized),
        }
    return {
        "sample": int(sample_index),
        "time_sec": _clean_float(time_sec),
        "nodes": nodes,
        "metrics": hip_metrics or {},
    }


def encode_orientation_packet(payload):
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def should_emit_debug(iteration, datarate, debug_hz):
    if debug_hz <= 0:
        return False
    interval = max(1, int(round(float(datarate) / float(debug_hz))))
    return int(iteration) % interval == 0


def format_orientation_summary(payload):
    parts = [
        "orientation_debug",
        "sample={}".format(payload["sample"]),
        "time={:.3f}s".format(payload["time_sec"]),
    ]
    for node_name, node_payload in payload["nodes"].items():
        euler = node_payload["euler_deg"]
        parts.append(
            "{} yaw={:.2f} pitch={:.2f} roll={:.2f} x={} y={} z={}".format(
                node_name,
                euler["yaw"],
                euler["pitch"],
                euler["roll"],
                node_payload["axes"]["x"],
                node_payload["axes"]["y"],
                node_payload["axes"]["z"],
            )
        )
    return " | ".join(parts)
