#!/usr/bin/env python3
"""
Robustness test for leader (serial) and follower (TCP) data transmission.
Tests each subsystem independently to identify which causes the ~30s teleoperation stop.

Usage:
    python test_robustness.py --test leader --duration 120 --fps 30
    python test_robustness.py --test follower --duration 120 --fps 30
    python test_robustness.py --test both --duration 120 --fps 30 --log-file results.csv
"""

import argparse
import csv
import sys
import time
import traceback
from dataclasses import dataclass, field

sys.path.insert(0, "src")

from lerobot.motors.old_motors.servo_controller import FeetechController
from lerobot.robots.enpei_follower.episode_server import EpisodeAPP
from lerobot.utils.robot_utils import busy_wait

# ANSI colors
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"


@dataclass
class TestStats:
    total_cycles: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    max_consecutive_failures: int = 0
    connection_drops: int = 0
    latencies: list = field(default_factory=list)
    failure_timestamps: list = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_cycles == 0:
            return 0.0
        return (self.total_cycles - self.failures) / self.total_cycles * 100

    @property
    def avg_latency(self) -> float:
        return sum(self.latencies) / len(self.latencies) if self.latencies else 0.0
    @property
    def max_latency(self) -> float:
        return max(self.latencies) if self.latencies else 0.0

    def percentile(self, p: float) -> float:
        if not self.latencies:
            return 0.0
        sorted_lat = sorted(self.latencies)
        idx = int(len(sorted_lat) * p / 100)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]

    def record_success(self, latency_ms: float):
        self.total_cycles += 1
        self.latencies.append(latency_ms)
        self.consecutive_failures = 0

    def record_failure(self, elapsed: float, error_msg: str):
        self.total_cycles += 1
        self.failures += 1
        self.consecutive_failures += 1
        self.max_consecutive_failures = max(
            self.max_consecutive_failures, self.consecutive_failures
        )
        self.failure_timestamps.append((elapsed, error_msg))

    def latency_histogram(self) -> dict:
        buckets = {"<5ms": 0, "5-10ms": 0, "10-20ms": 0, "20-50ms": 0, "50-100ms": 0, ">100ms": 0}
        for lat in self.latencies:
            if lat < 5:
                buckets["<5ms"] += 1
            elif lat < 10:
                buckets["5-10ms"] += 1
            elif lat < 20:
                buckets["10-20ms"] += 1
            elif lat < 50:
                buckets["20-50ms"] += 1
            elif lat < 100:
                buckets["50-100ms"] += 1
            else:
                buckets[">100ms"] += 1
        return buckets


def color_for_failure_rate(rate: float) -> str:
    if rate == 0:
        return GREEN
    elif rate < 5:
        return YELLOW
    return RED


def print_periodic_stats(stats: TestStats, label: str, elapsed: float):
    rate = 100 - stats.success_rate
    color = color_for_failure_rate(rate)
    print(
        f"{color}[{elapsed:6.1f}s] {label} | "
        f"cycles: {stats.total_cycles} | "
        f"fail: {stats.failures} ({rate:.1f}%) | "
        f"consec: {stats.consecutive_failures} | "
        f"avg: {stats.avg_latency:.1f}ms | "
        f"max: {stats.max_latency:.1f}ms | "
        f"p95: {stats.percentile(95):.1f}ms{RESET}"
    )


def print_final_summary(stats: TestStats, label: str, duration: float):
    fail_rate = 100 - stats.success_rate
    color = color_for_failure_rate(fail_rate)
    hist = stats.latency_histogram()

    print(f"\n{'=' * 60}")
    print(f"{BOLD}  {label} TEST SUMMARY{RESET}")
    print(f"{'=' * 60}")
    print(f"  Duration:              {duration:.1f}s")
    print(f"  Total cycles:          {stats.total_cycles}")
    print(f"  Failures:              {color}{stats.failures} ({fail_rate:.1f}%){RESET}")
    print(f"  Max consec. failures:  {stats.max_consecutive_failures}")
    if stats.connection_drops > 0:
        print(f"  Connection drops:      {RED}{stats.connection_drops}{RESET}")
    print(f"  Avg latency:           {stats.avg_latency:.2f} ms")
    print(f"  Max latency:           {stats.max_latency:.2f} ms")
    print(f"  P95 latency:           {stats.percentile(95):.2f} ms")
    print(f"  P99 latency:           {stats.percentile(99):.2f} ms")
    print(f"\n  Latency histogram:")
    for bucket, count in hist.items():
        bar = "#" * min(count * 50 // max(stats.total_cycles, 1), 50)
        print(f"    {bucket:>8s}: {count:5d}  {bar}")

    if stats.failure_timestamps:
        print(f"\n  First 10 failures:")
        for t, err in stats.failure_timestamps[:10]:
            print(f"    {RED}[{t:6.1f}s] {err}{RESET}")
    print(f"{'=' * 60}\n")


# ---------------------------------------------------------------------------
# Leader serial test
# ---------------------------------------------------------------------------

def test_leader(args) -> TestStats:
    stats = TestStats()
    print(f"\n{BOLD}Starting LEADER serial test{RESET}")
    print(f"  Port: {args.port}, FPS: {args.fps}, Duration: {args.duration}s\n")

    try:
        controller = FeetechController(port=args.port, motor_range=(1, 7))
        controller.connect()
    except OSError as e:
        print(f"{RED}Cannot open serial port {args.port}: {e}{RESET}")
        print("Make sure no other process is using the port (e.g. teleoperate).")
        return stats

    csv_writer = None
    csv_file = None
    if args.log_file:
        path = args.log_file.replace(".csv", "_leader.csv") if args.test == "both" else args.log_file
        csv_file = open(path, "w", newline="")
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(
            ["timestamp", "cycle", "motor1", "motor2", "motor3", "motor4",
             "motor5", "motor6", "motor7", "latency_ms", "success", "error"]
        )

    start = time.perf_counter()
    last_stats_time = start

    try:
        while True:
            elapsed = time.perf_counter() - start
            if elapsed >= args.duration:
                break

            loop_start = time.perf_counter()
            positions = None
            error_msg = ""

            try:
                positions = controller.batch_read_positions()
                latency_ms = (time.perf_counter() - loop_start) * 1000
                stats.record_success(latency_ms)
            except Exception as e:
                latency_ms = (time.perf_counter() - loop_start) * 1000
                error_msg = str(e)
                stats.record_failure(elapsed, error_msg)
                print(f"{RED}[{elapsed:6.1f}s] LEADER read failed: {error_msg}{RESET}")

            if csv_writer:
                if positions:
                    vals = [positions.get(i, "") for i in range(1, 8)]
                else:
                    vals = [""] * 7
                csv_writer.writerow(
                    [f"{elapsed:.3f}", stats.total_cycles] + vals +
                    [f"{latency_ms:.2f}", "1" if positions else "0", error_msg]
                )

            if time.perf_counter() - last_stats_time >= 5.0:
                print_periodic_stats(stats, "LEADER", elapsed)
                last_stats_time = time.perf_counter()

            dt_s = time.perf_counter() - loop_start
            busy_wait(1 / args.fps - dt_s)

    except KeyboardInterrupt:
        print(f"\n{YELLOW}Leader test interrupted by user{RESET}")
    finally:
        controller.disconnect()
        if csv_file:
            csv_file.close()

    actual_duration = time.perf_counter() - start
    print_final_summary(stats, "LEADER", actual_duration)
    return stats


# ---------------------------------------------------------------------------
# Follower TCP test
# ---------------------------------------------------------------------------

FOLLOWER_HOLD_SPEED = [90, 40, 100, 100, 100, 10]


def test_follower(args) -> TestStats:
    stats = TestStats()
    print(f"\n{BOLD}Starting FOLLOWER TCP test{RESET}")
    print(f"  Server: {args.ip}:{args.tcp_port}, FPS: {args.fps}, Duration: {args.duration}s\n")

    try:
        controller = EpisodeAPP(ip=args.ip, port=args.tcp_port)
        controller._ensure_connected()
        controller._socket.settimeout(5.0)
    except ConnectionRefusedError:
        print(f"{RED}Cannot connect to episode server at {args.ip}:{args.tcp_port}{RESET}")
        print("Make sure the robot controller server is running.")
        return stats
    except Exception as e:
        print(f"{RED}Connection failed: {e}{RESET}")
        return stats

    csv_writer = None
    csv_file = None
    if args.log_file:
        path = args.log_file.replace(".csv", "_follower.csv") if args.test == "both" else args.log_file
        csv_file = open(path, "w", newline="")
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(
            ["timestamp", "cycle", "joint1", "joint2", "joint3", "joint4",
             "joint5", "joint6", "latency_ms", "success", "error", "command_type"]
        )

    last_angles = None
    start = time.perf_counter()
    last_stats_time = start

    try:
        while True:
            elapsed = time.perf_counter() - start
            if elapsed >= args.duration:
                break

            loop_start = time.perf_counter()
            angles = None
            error_msg = ""
            cmd_type = "get_motor_angles"

            try:
                angles = controller.get_motor_angles()
                latency_ms = (time.perf_counter() - loop_start) * 1000

                if angles is None:
                    error_msg = "server returned None (CAN bus blocked?)"
                    stats.record_failure(elapsed, error_msg)
                    print(f"{RED}[{elapsed:6.1f}s] FOLLOWER: {error_msg}{RESET}")
                else:
                    stats.record_success(latency_ms)
                    last_angles = angles
            except Exception as e:
                latency_ms = (time.perf_counter() - loop_start) * 1000
                error_msg = str(e)
                stats.record_failure(elapsed, error_msg)
                stats.connection_drops += 1
                print(f"{RED}[{elapsed:6.1f}s] FOLLOWER exception: {error_msg}{RESET}")
                if controller._socket:
                    try:
                        controller._socket.settimeout(5.0)
                    except Exception:
                        pass

            if stats.total_cycles % 10 == 0 and last_angles is not None:
                try:
                    cmd_type = "dynamic_move"
                    goal = {str(i + 1): last_angles[i] for i in range(6)}
                    pulses = [int(3200 * g * r / 360) for g, r in
                              zip(last_angles, [25, 20, 25, 10, 4, 1])]
                    controller.dynamic_move(goal, pulses, FOLLOWER_HOLD_SPEED)
                except Exception as e:
                    print(f"{YELLOW}[{elapsed:6.1f}s] dynamic_move failed: {e}{RESET}")

            if csv_writer:
                vals = list(angles) if angles else [""] * 6
                csv_writer.writerow(
                    [f"{elapsed:.3f}", stats.total_cycles] + vals +
                    [f"{latency_ms:.2f}", "1" if angles else "0", error_msg, cmd_type]
                )

            if time.perf_counter() - last_stats_time >= 5.0:
                print_periodic_stats(stats, "FOLLOWER", elapsed)
                last_stats_time = time.perf_counter()

            dt_s = time.perf_counter() - loop_start
            busy_wait(1 / args.fps - dt_s)

    except KeyboardInterrupt:
        print(f"\n{YELLOW}Follower test interrupted by user{RESET}")
    finally:
        controller._close_connection()
        if csv_file:
            csv_file.close()

    actual_duration = time.perf_counter() - start
    print_final_summary(stats, "FOLLOWER", actual_duration)
    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Test robustness of leader/follower data transmission"
    )
    parser.add_argument(
        "--test", required=True, choices=["leader", "follower", "both"],
        help="Which subsystem to test"
    )
    parser.add_argument("--duration", type=float, default=120, help="Test duration in seconds")
    parser.add_argument("--fps", type=int, default=30, help="Target read frequency")
    parser.add_argument("--port", default="/dev/ttyACM0", help="Serial port for leader")
    parser.add_argument("--ip", default="localhost", help="Follower server IP")
    parser.add_argument("--tcp-port", type=int, default=12345, help="Follower server TCP port")
    parser.add_argument("--log-file", default=None, help="CSV log file path")
    args = parser.parse_args()

    print(f"{BOLD}Robustness Test{RESET}")
    print(f"  Mode: {args.test}, Duration: {args.duration}s, FPS: {args.fps}")

    if args.test in ("leader", "both"):
        test_leader(args)
    if args.test in ("follower", "both"):
        test_follower(args)

    print("Done.")


if __name__ == "__main__":
    main()
