"""A small synchronous rcon client: one zmq DEALER connection per request.

Same wire protocol as qlsm's own rcon service (qlsm/rcon_service/
instance_connection.py, itself ported from the reference Windows rcon tool):
DEALER socket, PLAIN auth as user "rcon" in ZAP domain "rcon", a fresh UUID
identity per connection (the engine ignores a reconnect under an identity it
has seen), `register` first, then plain console commands as single frames.

Why not the rcon service: it is a one-way pipe (Redis channel in, socket.io
room out) built for a console. A settings tab needs a request/response: send
`set`, read the value back, return both to the operator in one HTTP call. The
protocol is twenty lines, so the addon carries its own copy rather than
teaching the service a second mode.

Everything here raises RconError with a message safe to show the operator;
the password never appears in a message or a log line.
"""
import time
import uuid
from dataclasses import dataclass

from .cvar_reply import frames_to_lines, parse_cvar_lines

READY_STATUSES = ('running', 'updated')
CONNECT_SETTLE_S = 0.3   # let the PLAIN handshake finish before `register`
IDLE_MS = 400            # a quiet gap this long means the engine is done answering
MAX_WAIT_S = 3.0         # hard cap per round trip, however chatty the server is
SEND_TIMEOUT_MS = 3000


class RconError(Exception):
    """A failure safe to return to the operator verbatim."""


@dataclass(frozen=True)
class RconTarget:
    ip: str
    port: int
    password: str
    self_host: bool = False

    @property
    def endpoint(self):
        return f'tcp://{self.ip}:{self.port}'


def resolve_target(instance):
    """Where this instance's rcon listens, or RconError saying why not."""
    status = getattr(instance.status, 'value', instance.status)
    if str(status).lower() not in READY_STATUSES:
        raise RconError(f'Instance is not running (status: {status}). Live values need a running server.')
    port, password = instance.zmq_rcon_port, instance.zmq_rcon_password
    if isinstance(port, bool) or not isinstance(port, int) or port <= 0 or not password:
        raise RconError('RCON is not configured for this instance.')
    host = instance.host
    if host is None:
        raise RconError('Instance has no host.')
    self_host = getattr(host, 'provider', None) == 'self'
    if self_host:
        ip = _self_host_ip()
    else:
        ip = (getattr(host, 'ip_address', None) or '').strip()
    if not ip:
        raise RconError('Host address unavailable.')
    return RconTarget(ip=ip, port=port, password=password, self_host=self_host)


def _self_host_ip():
    try:
        from ui.task_logic.self_host_network import resolve_self_host_management_target
        return (resolve_self_host_management_target() or '').strip() or '127.0.0.1'
    except Exception:
        return '127.0.0.1'


class RconSession:
    """`with RconSession(target) as s: s.send('status'); frames = s.collect()`."""

    def __init__(self, target, settle_s=CONNECT_SETTLE_S):
        self.target = target
        self.settle_s = settle_s
        self._context = None
        self._socket = None

    def __enter__(self):
        import zmq

        self._context = zmq.Context()
        sock = self._context.socket(zmq.DEALER)
        sock.plain_username = b'rcon'
        sock.plain_password = self.target.password.encode('utf-8')
        sock.zap_domain = b'rcon'
        sock.identity = str(uuid.uuid4()).encode('utf-8')
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.SNDTIMEO, SEND_TIMEOUT_MS)
        # Fail fast on an unreachable host instead of queueing forever; the
        # self-host case keeps the default because its loopback peer may
        # still be connecting (same choice as the rcon service).
        sock.setsockopt(zmq.IMMEDIATE, 0 if self.target.self_host else 1)
        sock.connect(self.target.endpoint)
        self._socket = sock
        time.sleep(self.settle_s)
        self.send('register')
        self.collect(idle_ms=200, max_wait_s=0.6)  # the engine's greeting, if any
        return self

    def __exit__(self, *exc):
        try:
            if self._socket is not None:
                self._socket.close()
        finally:
            self._socket = None
            if self._context is not None:
                self._context.term()
                self._context = None
        return False

    def send(self, command):
        import zmq

        try:
            self._socket.send_string(command)
        except zmq.error.Again:
            raise RconError('Server is offline or unreachable (rcon port did not accept the command).')
        except zmq.error.ZMQError as e:
            raise RconError(f'RCON send failed: {e}')

    def collect(self, idle_ms=IDLE_MS, max_wait_s=MAX_WAIT_S):
        """Every frame the engine sends until it goes quiet for `idle_ms`."""
        import zmq

        frames = []
        deadline = time.monotonic() + max_wait_s
        while time.monotonic() < deadline:
            if not self._socket.poll(idle_ms):
                break
            try:
                frames.append(self._socket.recv(zmq.NOBLOCK))
            except zmq.error.Again:
                continue
        return frames


def query_cvars(target, names):
    """Ask the engine for each name. Returns ({lower name: entry}, lines)."""
    names = [n for n in names if n]
    if not names:
        return {}, []
    with RconSession(target) as session:
        for name in names:
            session.send(name)
        frames = session.collect()
    lines = frames_to_lines(frames)
    return parse_cvar_lines(lines), lines


def set_cvars(target, changes):
    """`set name "value"` for each change, then read every name back in the
    same session. Returns ({lower name: entry}, lines) where the entries are
    what the engine reports *after* the set -- a latched cvar still shows the
    old value and a `latched` field."""
    changes = list(changes)
    if not changes:
        return {}, []
    with RconSession(target) as session:
        for name, value in changes:
            session.send(f'set {name} "{value}"')
        set_frames = session.collect(idle_ms=300, max_wait_s=2.0)
        for name, _value in changes:
            session.send(name)
        frames = session.collect()
    lines = frames_to_lines(set_frames) + frames_to_lines(frames)
    return parse_cvar_lines(lines), lines
