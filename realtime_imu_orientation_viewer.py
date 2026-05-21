#!/usr/bin/env python3
import argparse
import json
import socket
import time


DEFAULT_PORT = 50514
NODE_ORDER = ("pelvis", "right_thigh", "left_thigh")
AXIS_COLORS = {"x": "r", "y": "g", "z": "b"}


class OrientationSceneState:
    def __init__(self):
        self.sample = None
        self.time_sec = None
        self.nodes = {}
        self.metrics = {}

    def update_from_packet(self, packet):
        payload = json.loads(packet.decode("utf-8").strip())
        self.sample = payload.get("sample")
        self.time_sec = payload.get("time_sec")
        self.nodes = payload.get("nodes", {})
        self.metrics = payload.get("metrics", {})
        return payload


class MatplotlibOrientationViewer:
    def __init__(self, state):
        import matplotlib.pyplot as plt

        self.state = state
        self.plt = plt
        self.figure = plt.figure("IMU Orientation Debug")
        self.axis = self.figure.add_subplot(111, projection="3d")
        plt.ion()

    def draw(self):
        self.axis.clear()
        self.axis.set_xlim(-1.8, 5.8)
        self.axis.set_ylim(-1.8, 1.8)
        self.axis.set_zlim(-1.8, 1.8)
        self.axis.set_xlabel("X")
        self.axis.set_ylabel("Y")
        self.axis.set_zlabel("Z")
        self.axis.set_box_aspect((7.6, 3.6, 3.6))

        for node_index, node_name in enumerate(NODE_ORDER):
            node = self.state.nodes.get(node_name)
            if not node:
                continue
            origin = (node_index * 2.5, 0.0, 0.0)
            self.axis.text(origin[0], origin[1], origin[2] - 0.35, node_name)
            for axis_name, vector in node.get("axes", {}).items():
                self.axis.quiver(
                    origin[0],
                    origin[1],
                    origin[2],
                    vector[0],
                    vector[1],
                    vector[2],
                    length=1.0,
                    normalize=True,
                    color=AXIS_COLORS.get(axis_name, "k"),
                )

        title = "sample={}".format(self.state.sample)
        if self.state.time_sec is not None:
            title += " time={:.3f}s".format(self.state.time_sec)
        if "right_Hip_ext" in self.state.metrics:
            title += " right_Hip_ext={:.2f}".format(self.state.metrics["right_Hip_ext"])
        self.axis.set_title(title)
        self.plt.pause(0.001)


def make_udp_socket(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    return sock


def should_stop_after_idle(last_packet_time, now, idle_timeout):
    if idle_timeout <= 0 or last_packet_time is None:
        return False
    return now - last_packet_time > idle_timeout


def run_viewer(host, port, idle_timeout=0):
    state = OrientationSceneState()
    viewer = MatplotlibOrientationViewer(state)
    sock = make_udp_socket(host, port)
    sock.settimeout(0.2)
    last_packet_time = None
    print("Listening for IMU orientation UDP on {}:{}".format(host, port))
    try:
        while True:
            try:
                packet, _ = sock.recvfrom(65535)
            except socket.timeout:
                if should_stop_after_idle(last_packet_time, time.time(), idle_timeout):
                    print("No UDP packets for {:.1f}s; exiting viewer.".format(idle_timeout))
                    break
                continue
            last_packet_time = time.time()
            state.update_from_packet(packet)
            viewer.draw()
    except KeyboardInterrupt:
        print("Viewer interrupted; closing.")
    finally:
        sock.close()
        viewer.plt.close(viewer.figure)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Show SageMotion IMU orientation axes from v1.4 UDP debug packets."
    )
    parser.add_argument("--host", default="0.0.0.0", help="UDP bind host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="UDP port")
    parser.add_argument(
        "--idle-timeout",
        type=float,
        default=0,
        help="Exit after this many seconds without UDP packets. 0 keeps listening.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_viewer(args.host, args.port, idle_timeout=args.idle_timeout)
