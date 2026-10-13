"""Run console commands on a local QLDS over zmq rcon. Port and password are
read from the running process's launch arguments and are never printed.
Usage (on the game host): python3 - <net_port> <command> [<command> ...]"""
import subprocess, sys, time, uuid
import zmq

net_port, commands = sys.argv[1], sys.argv[2:]
pid = subprocess.check_output(["systemctl", "show", f"qlds@{net_port}", "-p", "MainPID", "--value"]).decode().strip()
args = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
if len(args) < 2:
    args = open(f"/proc/{pid}/cmdline", "rb").read().split()


def launch_arg(name):
    for i, a in enumerate(args):
        if a == name.encode() and i + 1 < len(args):
            return args[i + 1].decode()
    # the unit may start a wrapper: look at the children too
    out = subprocess.check_output(["pgrep", "-P", pid]).decode().split()
    for child in out:
        cargs = open(f"/proc/{child}/cmdline", "rb").read().split(b"\0")
        for i, a in enumerate(cargs):
            if a == name.encode() and i + 1 < len(cargs):
                return cargs[i + 1].decode()
    raise SystemExit(f"launch argument {name} not found")


port = launch_arg("zmq_rcon_port")
password = launch_arg("zmq_rcon_password")

ctx = zmq.Context()
s = ctx.socket(zmq.DEALER)
s.setsockopt(zmq.IDENTITY, uuid.uuid4().hex.encode())
s.plain_username = b"rcon"
s.plain_password = password.encode()
s.zap_domain = b"rcon"
s.setsockopt(zmq.LINGER, 0)
s.connect(f"tcp://127.0.0.1:{port}")
time.sleep(0.5)
s.send(b"register")
time.sleep(0.6)
while s.poll(100):
    s.recv()
for command in commands:
    s.send(command.encode())
    idle = 0
    out = []
    end = time.time() + 8
    while time.time() < end and idle < 6:
        if s.poll(400):
            out.append(s.recv().decode("utf-8", "replace"))
            idle = 0
        else:
            idle += 1
    text = "".join(out).strip()
    print(f"> {command}\n{text if text else '(no output)'}")
