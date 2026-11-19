"""Interactive, camera-guided YAM simulation. Run with python -m camera_env."""
import argparse
import hashlib
import json
import math
import sys
import socket
import tempfile
import time
from importlib.metadata import version
from pathlib import Path

import mujoco
import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation

from labbench.sim import STEP_S, TABLE_Z
from labbench.take import code_id, set_bench
from labbench.tasks import TASKS
from labbench.video import Mp4, tile

SIDES = ("left", "right")


def finite(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be a finite number between {low} and {high}.")
    return float(value)


class TopCamera:
    """Project raw, cropped image pixels using the actual renderer frustum."""
    def __init__(self, env):
        env.renderer.update_scene(env.data, camera="top")
        left, right = env.renderer.scene.camera
        self.origin = (left.pos + right.pos) * 0.5
        self.forward = left.forward.astype(float)
        self.up = left.up.astype(float)
        self.right = np.cross(self.forward, self.up)
        # MuJoCo renders a monoscopic view from the midpoint of the eye pair.
        span = float(left.frustum_top - left.frustum_bottom)
        self.fx = self.fy = 480 * left.frustum_near / span
        self.cx = 319.5 - 480 * ((left.frustum_center + right.frustum_center) * 0.5) / span
        self.cy = 179.5 + 480 * (left.frustum_top + left.frustum_bottom) * 0.5 / span

    def world(self, uv, plane):
        u, v = uv
        ray = self.forward + (u - self.cx) / self.fx * self.right - (v - self.cy) / self.fy * self.up
        if abs(ray[2]) < 1e-7 or (TABLE_Z + plane - self.origin[2]) / ray[2] <= 0:
            raise ValueError("The camera ray does not intersect that plane in front of the lens.")
        return self.origin + (TABLE_Z + plane - self.origin[2]) / ray[2] * ray

    def pixel(self, xyz):
        d = xyz - self.origin
        depth = d @ self.forward
        if depth <= 1e-5:
            return None
        return np.round([self.cx + self.fx * (d @ self.right) / depth,
                         self.cy - self.fy * (d @ self.up) / depth], 1).tolist()


class Arm:
    """Robot-only forward and inverse kinematics for one six-joint arm."""
    def __init__(self, model, side):
        self.model, self.data = model, mujoco.MjData(model)
        self.site = model.site(f"{side}_tcp").id
        joints = [model.joint(f"{side}_joint{i}") for i in range(1, 7)]
        self.qidx = np.array([j.qposadr[0] for j in joints])
        self.didx = np.array([j.dofadr[0] for j in joints])
        self.lo, self.hi = np.array([j.range for j in joints]).T
        self.jp = np.zeros((3, model.nv))
        self.jr = np.zeros_like(self.jp)

    def pose(self, q):
        self.data.qpos[self.qidx] = q[:6]
        mujoco.mj_kinematics(self.model, self.data)
        mujoco.mj_comPos(self.model, self.data)
        xyz = self.data.site_xpos[self.site].copy()
        rot = Rotation.from_matrix(self.data.site_xmat[self.site].reshape(3, 3))
        return xyz, rot

    def solve(self, xyz, rot, q):
        for _ in range(32):
            pos, actual_rot = self.pose(q)
            residual = np.r_[xyz - pos, (rot * actual_rot.inv()).as_rotvec()]
            if np.linalg.norm(residual[:3]) < .00025 and np.linalg.norm(residual[3:]) < .0015:
                break
            mujoco.mj_jacSite(self.model, self.data, self.jp, self.jr, self.site)
            jac = np.vstack([self.jp[:, self.didx], self.jr[:, self.didx]])
            update = jac.T @ np.linalg.solve(jac @ jac.T + .0004 * np.eye(6), residual)
            q = np.clip(q + update / max(1, np.max(np.abs(update)) / .16), self.lo, self.hi)
        return q


class Episode:
    def __init__(self, args):
        self.args = args
        self.out = args.out.resolve()
        self.out.mkdir(parents=True, exist_ok=False)
        self.started = time.monotonic()
        self.bench = set_bench(args.task, args.seed)
        self.env = self.bench.env
        self.tracker = self.bench.tracker
        # Match the frozen run's nine-frame pre-roll at four control steps per sample.
        for _ in range(33):
            state = self.env.state()
            self.env.step(state["left"], state["right"])
            self.tracker.update()
        self.tracker.t0 = self.bench.world.time
        self.limit = round(self.bench.task.seconds / STEP_S)
        self.step = self.seq = 0
        self.arms = {s: Arm(self.env.model, s) for s in SIDES}
        self.targets = self.env.state()
        images = self.env.images()
        self.camera = TopCamera(self.env)
        self.video = Mp4(self.out / "take.mp4", 640, 566, 4)
        self.video.add(tile(images, self.bench.task.prompt, "0.0 s"))
        self.trace = (self.out / "actions.jsonl").open("x")
        self.ended = False
        self.config = {"actor": args.actor, "task": args.task, "seed": args.seed, "prompt": self.bench.task.prompt,
                       "seconds_allowed": self.limit * STEP_S, "bench_code": code_id(),
                       "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       "mujoco": mujoco.__version__, "dreamlabs": version("dreamlabs")}
        (self.out / "config.json").write_text(json.dumps(self.config, indent=2))

    def observation(self):
        images = self.env.images()
        record = self.out / f"obs-{self.seq:03d}"
        record.mkdir()
        paths = {}
        for name, rgb in images.items():
            path = record / f"{name}.png"
            Image.fromarray(rgb).save(path)
            paths[name] = str(path)
        montage = record / "cameras.jpg"
        Image.fromarray(tile(images, self.bench.task.prompt, f"{self.step * STEP_S:.2f} s")).save(montage, quality=92)
        arms = {}
        for side, state in self.env.state().items():
            pos, _ = self.arms[side].pose(state)
            arms[side] = {"xyz": np.round(pos - [0, 0, TABLE_Z], 4).tolist(), "top_uv": self.camera.pixel(pos),
                          "q_rad": np.round(state[:6], 4).tolist(), "grip": round(float(state[-1]), 3)}
        return {"observation_index": self.seq, "prompt": self.bench.task.prompt, "sim_s": round(self.step * STEP_S, 2),
                "seconds_allowed": self.limit * STEP_S, "hands": arms, "images": paths, "montage": str(montage)}

    def plan_arm(self, side, cmd):
        if not isinstance(cmd, dict) or set(cmd) - {"xyz", "uv", "plane", "z", "yaw", "grip"}:
            raise ValueError("Arm fields are xyz or uv/plane/z, plus yaw and grip.")
        if "xyz" in cmd and any(k in cmd for k in ("uv", "plane", "z")):
            raise ValueError("Choose xyz or a pixel target.")
        if "plane" in cmd and "uv" not in cmd:
            raise ValueError("plane requires uv.")
        arm, source = self.arms[side], self.targets[side]
        start, rot = arm.pose(source)
        desired = start.copy()
        if "xyz" in cmd:
            if not isinstance(cmd["xyz"], list) or len(cmd["xyz"]) != 3:
                raise ValueError("xyz needs [x,y,height above table], in metres.")
            desired = np.array([finite(v, -1.2, 1.2, "xyz") for v in cmd["xyz"]])
            desired[2] += TABLE_Z
        if "uv" in cmd:
            uv = cmd["uv"]
            if not isinstance(uv, list) or len(uv) != 2:
                raise ValueError("uv needs [column,row] on the raw overhead image.")
            uv = [finite(uv[0], 0, 639, "u"), finite(uv[1], 0, 359, "v")]
            plane = finite(cmd.get("plane", 0), -.05, .9, "plane")
            desired[:2] = self.camera.world(uv, plane)[:2]
        if "z" in cmd:
            desired[2] = TABLE_Z + finite(cmd["z"], -.05, .9, "z")
        if "yaw" in cmd:
            yaw = math.radians(finite(cmd["yaw"], -360, 360, "yaw"))
            c, s = math.cos(yaw), math.sin(yaw)
            endrot = Rotation.from_matrix([[-c, -s, 0], [-s, c, 0], [0, 0, -1]])
        else:
            endrot = rot
        relative = (endrot * rot.inv()).as_rotvec()
        grip = finite(cmd.get("grip", source[6]), 0, 1, "grip")
        moves = any(key in cmd for key in ("xyz", "uv", "yaw", "z"))
        def target(u):
            q = self.targets[side][:6]
            if moves:
                q = arm.solve(start + u * (desired - start), Rotation.from_rotvec(relative * u) * rot, q)
            return np.r_[q, source[6] + u * (grip - source[6])]
        return target

    def apply(self, cmd):
        if not isinstance(cmd, dict) or set(cmd) - {"left", "right", "seconds", "done"}:
            raise ValueError("Send left/right maps, seconds, or done:true.")
        if "done" in cmd and (cmd != {"done": True} or not isinstance(cmd["done"], bool)):
            raise ValueError("Send done:true alone to hold until the terminal condition.")
        finish = cmd.get("done", False)
        steps = self.limit - self.step if finish else max(1, round(finite(cmd.get("seconds", 1), .05, 30, "seconds") / STEP_S))
        plans = {s: self.plan_arm(s, cmd[s]) for s in SIDES if s in cmd}
        self.trace.write(json.dumps({"i": self.seq, "sim_s": round(self.step * STEP_S, 2), "action": cmd}) + "\n")
        self.trace.flush()
        self.seq += 1
        for i in range(1, min(steps, self.limit - self.step) + 1):
            u = i / steps
            smooth = u**3 * (10 - 15*u + 6*u*u)
            for s, plan in plans.items():
                self.targets[s] = plan(smooth)
            self.env.step(self.targets["left"], self.targets["right"])
            self.tracker.update()
            self.step += 1
            if self.step % 5 == 0:
                self.video.add(tile(self.env.images(), self.bench.task.prompt, f"{self.step * STEP_S:.2f} s"))
            if self.tracker.success_at is not None and self.step * STEP_S - self.tracker.success_at >= 1 - 1e-7:
                break
        if self.step >= self.limit or self.tracker.success_at is not None and self.step * STEP_S - self.tracker.success_at >= 1 - 1e-7:
            self.ended = True
        return self.observation()

    def close(self, reason):
        self.video.close()
        self.env.close()
        self.trace.close()
        summary = {**self.config, "status": reason, "sim_s": round(self.step * STEP_S, 2),
                   "actions": self.seq, "wall_s": round(time.monotonic() - self.started, 2)}
        if reason == "complete":
            summary.update(self.tracker.summary())
        (self.out / "summary.json").write_text(json.dumps(summary, indent=2))
        return summary


def emit(data):
    print(json.dumps(data, allow_nan=False), flush=True)



def serve(take):
    """Offer the same interface to agents whose shell calls are stateless."""
    def publish(value):
        pending = take.out / ".pending.json"
        pending.write_text(json.dumps(value))
        pending.replace(take.out / "latest.json")
    with tempfile.TemporaryDirectory(prefix="yam-camera-", dir="/tmp") as tmp:
        endpoint = str(Path(tmp) / "sim.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(endpoint)
            server.listen(4)
            (take.out / "socket.txt").write_text(endpoint)
            publish(take.observation())
            while not take.ended:
                conn, _ = server.accept()
                with conn, conn.makefile("rb") as incoming:
                    try:
                        message = json.loads(incoming.readline(8192))
                        if message["after"] != take.seq:
                            raise ValueError("Observation changed; read current state before deciding again.")
                        reply = take.apply(message["action"])
                        if take.ended:
                            reply["terminal"] = take.close("complete")
                        publish(reply)
                    except (TypeError, ValueError, KeyError) as error:
                        reply = {"error": str(error)}
                    try:
                        conn.sendall((json.dumps(reply) + "\n").encode())
                    except (BrokenPipeError, ConnectionResetError):
                        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=TASKS, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--out", type=Path, required=True, help="New directory, never overwritten")
    parser.add_argument("--listen", action="store_true", help="Serve a local socket for camera_env.client")
    args = parser.parse_args()
    take = Episode(args)
    if args.listen:
        try:
            serve(take)
        finally:
            if not take.ended:
                take.close("interrupted")
        return
    reason = "interrupted"
    try:
        emit(take.observation())
        for line in sys.stdin:
            try:
                cmd = json.loads(line)
                obs = take.apply(cmd)
            except (ValueError, TypeError, OverflowError) as error:
                emit({"error": str(error)})
                continue
            emit(obs)
            if take.ended:
                reason = "complete"
                break
    finally:
        emit({"terminal": take.close(reason)})


if __name__ == "__main__":
    main()
