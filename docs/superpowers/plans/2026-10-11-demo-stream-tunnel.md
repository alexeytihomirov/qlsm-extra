# demo-stream addon 1.2.0: host TLS tunnel - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Game instances stream their POV to stats-hub only through a per-host stunnel client (127.0.0.1:<tunnel port> -> TLS -> relay:27999) that pins the hub's self-signed certificate, set up from a new host panel in qlsm.

**Architecture:** New host panel `host_tunnel` (GET/PUT `hosts/{host_id}`) stores two AppSetting keys and, on enable, fetches the hub PEM from `GET <stats-hub url>/api/demo-stream/tls-cert` inside the request, then queues an addon task that runs `playbooks/install_demo_stream_tunnel.yml` over SSH (same pattern as `addons/telemetry-relay/relay_ops.py`). Instance enable refuses (400) until the host tunnel is on, writes `sv_demoStreamHost 127.0.0.1` + the tunnel port, and reuses telemetry's server_id when there is one.

**Tech Stack:** Python 3 / Flask blueprint inside qlsm, SQLAlchemy `AppSetting`, RQ via qlsm `ui.tasks.enqueue_task`, Ansible (`ansible-core>=2.17,<2.18` in the qlsm image), stunnel4 + systemd on Ubuntu game hosts, pytest with a qlsm checkout.

**Spec:** `D:/QuakeLiveData/QL Server/docs/superpowers/specs/2026-10-11-demo-stream-relay-hardening-design.md`, section 4.3 (all of it) and the first bullet of 4.5. Read both before starting.

## Global Constraints

- Worktree: `D:/QuakeLiveData/QL Server/qlsm-extra/.claude/worktrees/demo-stream-tunnel`, branch `feat/demo-stream-tunnel`. First command of every session: `git -C "<worktree>" branch --show-current`, stop if it is not `feat/demo-stream-tunnel`. Never edit `D:/QuakeLiveData/QL Server/qlsm-extra` (shared checkout) or other worktrees.
- Addon id `demo-stream`, version `1.2.0` in `addons/demo-stream/qlsm-addon.json`; `ui_api` stays `1` (`host_menu` + `kind: form` already work at ui_api 1, see `addons/telemetry-relay/qlsm-addon.json`).
- AppSetting keys (exact): `demo_stream_tunnel_enabled:<host_id>` (value `'1'` or row absent), `demo_stream_tunnel_port:<host_id>` (digits string; absent means default `27999`).
- Telemetry's server_id key (exact, verified in `addons/telemetry-relay/stats_hub.py`, `_SERVER_ID_PREFIX`): `stats_hub_server_id:<instance_id>`. demo-stream's own key stays `demo_stream_stats_hub_server_id:<instance_id>`.
- Playbook `addons/demo-stream/playbooks/install_demo_stream_tunnel.yml`; extravars (exact names): `demo_stream_tunnel_enabled`, `demo_stream_tunnel_port`, `demo_stream_relay_host`, `demo_stream_relay_port`, `demo_stream_hub_cert_pem`.
- On host: directory `/home/ql/demo-stream-tunnel/`, `hub.pem` mode `0600` owner `ql`, `stunnel.conf`, unit `ql-demo-stream-tunnel.service` (`User=ql`, `Restart=always`), apt package `stunnel4`.
- stunnel.conf content per spec: `client = yes`, section `[demo-stream]`, `accept = 127.0.0.1:<local_port>`, `connect = <relay_host>:<relay_port>`, `verifyPeer = yes`, `CAfile = /home/ql/demo-stream-tunnel/hub.pem`, `sslVersionMin = TLSv1.2`. Plus `foreground = yes` (not in the spec; stunnel daemonizes by default and the unit runs it as a plain foreground service - see Open questions).
- Relay port placeholder in the manifest: `27999` (was `7788`).
- Cert endpoint: `GET <effective stats-hub url>/api/demo-stream/tls-cert`, PEM as `text/plain`, 404 when the hub has no TLS. 404 -> PUT fails with a clear message, nothing queued.
- Instance enable without the host tunnel -> HTTP 400. Plain TCP to the relay is no longer configured anywhere.
- Core helpers used (verified in the qlsm checkout `C:/Users/hellp/orca/workspaces/qlsm/QLSM` at `9016de2e`): `ui.task_logic.ansible_runner._run_host_ansible_playbook(host, playbook_name, extravars=None, capture_output=False) -> (bool, str, str)` (an absolute playbook path is kept as-is); `ui.tasks.enqueue_task(task_func, *args, on_failure=None, **kwargs)`; `ui.task_lock.acquire_lock(entity_type, entity_id, token, ttl) -> bool` / `release_lock`; `ui.task_logic.job_failure_handlers.host_job_failure_handler`; `ui.database.get_host(host_id)`, `ui.database.update_host(host_id, **fields)`; addon ctx `ctx.task(timeout=..., lock_scope='host')`, `ctx.on('host.delete')` (hook exists in `ui/addons/hooks.py`, scope None).
- **Not found:** core `ui/stats_hub.py` with a `feature` argument does not exist in the qlsm checkout (no file, no reference under `ui/`; both addons carry private `stats_hub.py` copies since the split). Telemetry server_id reuse is therefore done by reading the AppSetting key `stats_hub_server_id:<instance_id>` from inside demo-stream (Task 1), not through a core call.
- Addon module import name in tests: `qlsm_addon_demo_stream` (from `ui/addons/registry.py`: `qlsm_addon_<id with - as _>`).
- Tests: `tests/test_addon_demo_stream.py` (new, one file for the addon). Run from the worktree root:
  `QLSM_REPO="C:/Users/hellp/orca/workspaces/qlsm/QLSM" rtk proxy python -m pytest tests/test_addon_demo_stream.py -q -p no:cacheprovider`
  (rtk swallows pytest output without `rtk proxy`). conftest `chdir`s into the qlsm checkout, so any test that writes `configs/...` must `monkeypatch.chdir(tmp_path)` first.
- Redis is not stubbed by this repo's conftest: patch `ui.task_lock.acquire_lock` (return True) and `ui.tasks.enqueue_task` in endpoint tests; the backend imports them inside the function body, so patching the module attribute works.
- After any change under `addons/`: `python generate_manifest.py` then `python check_manifest_hashes.py`, and commit the refreshed `qlsm-repository.json` + `packages/demo-stream.zip` with the code.
- Commits: English, no AI attribution lines, authored as the user.

## Review Focus

1. Operator edits the tunnel port while the tunnel is already on -> the playbook re-runs with the new port and restarts stunnel; instances already wired keep the old port until re-enabled. Test: `test_put_port_change_on_enabled_tunnel_requeues_playbook` (Task 4). The stale-instance part is documented in the panel description, not fixed.
2. Disabling a tunnel on a host where it was never installed must not fail the playbook (unit file absent). Test: template/playbook check in Task 3 (`test_playbook_stops_unit_only_when_present`), plus `--syntax-check`.
3. Stats-hub returns 200 with something that is not a certificate (HTML error page, empty body) -> treated like "no TLS", not pinned. Test: `test_fetch_cert_rejects_non_pem_body` (Task 2).
4. Port values: `''` -> default `27999`; `'0'`, `'70000'`, `'27 999'`, `'abc'` -> 400 and nothing stored. Test: `test_put_rejects_bad_port` parametrized (Task 4).
5. Telemetry has a server_id that differs from demo-stream's stored one -> telemetry's wins and demo-stream's key is overwritten, route registered with telemetry's id. Test: `test_enable_prefers_telemetry_server_id_over_own` (Task 5).

---

### Task 1: Settings - tunnel keys and telemetry server_id accessor

**Files:**
- Modify: `addons/demo-stream/settings.py` (append after `set_instance_demo_stream_token`)
- Create: `tests/test_addon_demo_stream.py`

**Interfaces:**
- Produces (all in `qlsm_addon_demo_stream.settings`, none commit):
  - `DEFAULT_TUNNEL_PORT = '27999'`
  - `is_host_tunnel_enabled(host_id: int) -> bool`
  - `set_host_tunnel_enabled(host_id: int, enabled: bool) -> None`
  - `get_host_tunnel_port(host_id: int) -> str` (stored value or `DEFAULT_TUNNEL_PORT`)
  - `set_host_tunnel_port(host_id: int, value: str) -> None` (empty clears the row)
  - `get_telemetry_server_id(instance_id: int) -> int | None` (reads `stats_hub_server_id:<id>`)
  - `set_telemetry_server_id(instance_id: int, server_id: int | None) -> None`

- [ ] **Step 1: Write the failing tests**

Test module skeleton: `addon_id` fixture returns `'demo-stream'`; `auth` fixture as in `tests/test_addon_demo_management.py`; `host_id` fixture creates `Host(name='germany', ip_address='10.0.0.1', provider='vultr', status=HostStatus.ACTIVE)`; `instance_id` fixture adds `QLInstance(name='duel srv', port=27960, hostname='duel', host_id=..., status=InstanceStatus.RUNNING)`.

```python
def test_tunnel_port_defaults_to_27999(app, host_id):
    with app.app_context():
        from qlsm_addon_demo_stream.settings import get_host_tunnel_port, is_host_tunnel_enabled
        assert get_host_tunnel_port(host_id) == '27999'
        assert is_host_tunnel_enabled(host_id) is False

def test_tunnel_settings_use_the_spec_keys(app, host_id):
    # set_host_tunnel_enabled(host_id, True); set_host_tunnel_port(host_id, '28000'); commit
    # AppSetting.query.get(f'demo_stream_tunnel_enabled:{host_id}').value == '1'
    # AppSetting.query.get(f'demo_stream_tunnel_port:{host_id}').value == '28000'
    # set_host_tunnel_enabled(host_id, False); commit -> row absent

def test_telemetry_server_id_reads_telemetry_key(app, instance_id):
    # AppSetting(key=f'stats_hub_server_id:{instance_id}', value='42') -> get_telemetry_server_id == 42
    # no row -> None
```

- [ ] **Step 2: Run, expect FAIL** (`ImportError: cannot import name 'get_host_tunnel_port'`)

Run: the Global Constraints test command with `-k "tunnel_port or tunnel_settings or telemetry_server_id"`.

- [ ] **Step 3: Implement the seven names above in `addons/demo-stream/settings.py`** using the module's existing `_get` / `_set`. Prefixes as private constants `_TUNNEL_ENABLED_PREFIX = 'demo_stream_tunnel_enabled:'`, `_TUNNEL_PORT_PREFIX = 'demo_stream_tunnel_port:'`, `_TELEMETRY_SERVER_ID_PREFIX = 'stats_hub_server_id:'`. Add one docstring paragraph to the module: telemetry's key is read directly because the shared core `ui/stats_hub.py` no longer exists, and the key name must stay in step with `addons/telemetry-relay/stats_hub.py`.

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit**

```bash
git add addons/demo-stream/settings.py tests/test_addon_demo_stream.py
git commit -m "demo-stream: settings for the host tunnel and telemetry server_id"
```

---

### Task 2: `tunnel_ops.py` - cert fetch, extravars, playbook run

**Files:**
- Create: `addons/demo-stream/tunnel_ops.py`
- Test: `tests/test_addon_demo_stream.py`

**Interfaces:**
- Consumes: Task 1 settings; `.settings.get_effective_stats_hub_url`, `get_relay_host`, `get_relay_port`.
- Produces (in `qlsm_addon_demo_stream.tunnel_ops`):
  - `PLAYBOOK` - absolute path to `playbooks/install_demo_stream_tunnel.yml` next to the module (same construction as `relay_ops.PLAYBOOK`).
  - `class TunnelCertError(Exception)` - `str(exc)` is the operator-facing message.
  - `fetch_hub_tls_cert(host_id: int) -> str` - `requests.get(f"{url}/api/demo-stream/tls-cert", timeout=10)`; 404 -> `TunnelCertError("stats-hub has no TLS configured (GET /api/demo-stream/tls-cert returned 404); the tunnel was not set up.")`; other non-2xx or `requests.RequestException` -> `TunnelCertError(f"Could not fetch the stats-hub TLS certificate: {exc}")`; body without `-----BEGIN CERTIFICATE-----` -> `TunnelCertError("stats-hub returned something that is not a PEM certificate.")`. No URL configured -> `TunnelCertError("Set the demo-stream stats-hub URL in Settings first.")`.
  - `build_tunnel_extravars(enabled: bool, port: str, cert_pem: str) -> dict` - keys exactly the five Global Constraints names; `demo_stream_relay_host`/`_port` from `get_relay_host()`/`get_relay_port()` (`''` if None); when `enabled` is False, cert is `''`.
  - `configure_host_demo_stream_tunnel_logic(host_id: int, enabled: bool, port: str, cert_pem: str) -> bool` - runs `_run_host_ansible_playbook(host=..., playbook_name=PLAYBOOK, extravars=...)`; on success `set_host_tunnel_enabled(host_id, enabled)`, `host.status = HostStatus.ACTIVE`, log line prepended to `host.logs` ("Demo stream tunnel enabled on port N." / "Demo stream tunnel disabled."); on failure `host.status = HostStatus.ERROR`, "Demo stream tunnel configuration failed." prepended, enabled flag unchanged; commits; host missing -> False.

- [ ] **Step 1: Write the failing tests**

```python
PEM = '-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n'

def test_extravars_carry_the_five_spec_keys(app):
    # set relay host '70.34.223.191', port '27999'
    # build_tunnel_extravars(True, '27999', PEM) == {
    #   'demo_stream_tunnel_enabled': True, 'demo_stream_tunnel_port': '27999',
    #   'demo_stream_relay_host': '70.34.223.191', 'demo_stream_relay_port': '27999',
    #   'demo_stream_hub_cert_pem': PEM}

def test_extravars_drop_cert_when_disabling(app):
    # build_tunnel_extravars(False, '27999', PEM)['demo_stream_hub_cert_pem'] == ''

def test_fetch_cert_404_says_hub_has_no_tls(app, host_id):
    # stats-hub url set; patch qlsm_addon_demo_stream.tunnel_ops.requests.get -> Mock(status_code=404)
    # pytest.raises(TunnelCertError, match='no TLS configured')

def test_fetch_cert_rejects_non_pem_body(app, host_id):
    # 200 with text '<html>oops</html>' -> TunnelCertError match 'not a PEM'

def test_fetch_cert_returns_pem(app, host_id):
    # 200 with text PEM -> returns PEM; requests.get called with
    #   'https://stats.example/api/demo-stream/tls-cert'

def test_configure_success_sets_flag_and_active(app, host_id):
    # patch tunnel_ops._run_host_ansible_playbook -> (True, '', '')
    # configure_host_demo_stream_tunnel_logic(host_id, True, '27999', PEM) is True
    # is_host_tunnel_enabled(host_id) is True; host.status == HostStatus.ACTIVE
    # playbook kwargs: playbook_name endswith 'install_demo_stream_tunnel.yml'

def test_configure_failure_keeps_flag_and_sets_error(app, host_id):
    # (False, '', 'boom') -> False; flag still False; HostStatus.ERROR
```

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError: qlsm_addon_demo_stream.tunnel_ops`).

- [ ] **Step 3: Implement `addons/demo-stream/tunnel_ops.py`** with the names above. Import `_run_host_ansible_playbook` at module top (as `relay_ops.py` does) so tests can patch `qlsm_addon_demo_stream.tunnel_ops._run_host_ansible_playbook`. `PLAYBOOK` may point at a file that does not exist yet (Task 3).

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit**

```bash
git add addons/demo-stream/tunnel_ops.py tests/test_addon_demo_stream.py
git commit -m "demo-stream: tunnel ops - hub cert fetch, extravars, playbook run"
```

---

### Task 3: Playbook and templates

**Files:**
- Create: `addons/demo-stream/playbooks/install_demo_stream_tunnel.yml`
- Create: `addons/demo-stream/playbooks/templates/stunnel.conf.j2`
- Create: `addons/demo-stream/playbooks/templates/ql-demo-stream-tunnel.service.j2`
- Test: `tests/test_addon_demo_stream.py`

(Templates sit under `playbooks/templates/`, matching `addons/telemetry-relay/playbooks/templates/`; the spec's "templates/" is read as relative to the playbook.)

**Interfaces:**
- Consumes: the five extravars from Task 2.
- Produces: unit name `ql-demo-stream-tunnel`, files under `/home/ql/demo-stream-tunnel/`.

- [ ] **Step 1: Write the failing tests** (render with plain `jinja2`, which Flask already brings in; the templates must use no Ansible-only filters)

```python
def _render(name, **vars):
    # jinja2.Environment(loader=FileSystemLoader(ADDONS_DIR/'demo-stream'/'playbooks'/'templates'),
    #                    keep_trailing_newline=True).get_template(name).render(**vars)

def test_stunnel_conf_matches_spec():
    text = _render('stunnel.conf.j2', demo_stream_tunnel_port='27999',
                   demo_stream_relay_host='70.34.223.191', demo_stream_relay_port='27999')
    for line in ('client = yes', '[demo-stream]', 'accept = 127.0.0.1:27999',
                 'connect = 70.34.223.191:27999', 'verifyPeer = yes',
                 'CAfile = /home/ql/demo-stream-tunnel/hub.pem',
                 'sslVersionMin = TLSv1.2', 'foreground = yes'):
        assert line in text.splitlines()

def test_unit_runs_as_ql_and_restarts_always():
    text = _render('ql-demo-stream-tunnel.service.j2')
    # 'User=ql', 'Restart=always', ExecStart line ends with
    # ' /home/ql/demo-stream-tunnel/stunnel.conf', 'WantedBy=multi-user.target'

def test_playbook_stops_unit_only_when_present():
    # yaml.safe_load the playbook; assert a task uses ansible.builtin.stat on
    # /etc/systemd/system/ql-demo-stream-tunnel.service and the stop/disable task
    # has a `when` that references both `not demo_stream_tunnel_enabled` and the stat result
```

- [ ] **Step 2: Run, expect FAIL** (`TemplateNotFound`).

- [ ] **Step 3: Write the three files.**
  - Playbook header comment in the style of `install_telemetry_relay.yml` (who calls it, bare run is a no-op disable). `hosts: all`, `become: yes`, `gather_facts: false`. `vars` defaults: enabled `false`, port `'27999'`, relay host `''`, relay port `'27999'`, cert `''`.
  - Enabled branch (`when: demo_stream_tunnel_enabled | bool`, use a `block`): `ansible.builtin.assert` that relay host and cert are non-empty; `ansible.builtin.apt: name=stunnel4 state=present update_cache=yes cache_valid_time=3600`; `file` dir `/home/ql/demo-stream-tunnel` `ql:ql` `0750`; `copy` `content: "{{ demo_stream_hub_cert_pem }}"` to `hub.pem` `ql:ql` `0600`; `template` `stunnel.conf.j2` -> `stunnel.conf` `ql:ql` `0600`; `template` unit -> `/etc/systemd/system/ql-demo-stream-tunnel.service` `root:root` `0644`; the three file tasks `notify` a handler that does `daemon_reload: yes` + `state: restarted`; `meta: flush_handlers`; `ansible.builtin.systemd: name=ql-demo-stream-tunnel enabled=yes state=started daemon_reload=yes`.
  - Disabled branch: `stat` the unit file, then `systemd: name=ql-demo-stream-tunnel state=stopped enabled=no` when not enabled and the file exists. Leave the package and files in place.
  - Unit: `[Unit] Description=QL demo stream TLS tunnel (stunnel client to stats-hub)`, `After=network-online.target`, `Wants=network-online.target`; `[Service] User=ql`, `Group=ql`, `ExecStart=/usr/bin/stunnel /home/ql/demo-stream-tunnel/stunnel.conf`, `Restart=always`, `RestartSec=5`, journal output; `[Install] WantedBy=multi-user.target`. The binary path is an assumption - see Open questions.

- [ ] **Step 4: Run tests, expect PASS.**

- [ ] **Step 5: Ansible syntax check.** `ansible-playbook` is not on this Windows PATH and not installed in the WSL Ubuntu distro (checked). Use a throwaway venv in WSL with the qlsm image's pin:

```bash
wsl -e sh -c 'python3 -m venv /tmp/ans && /tmp/ans/bin/pip install -q "ansible-core>=2.17,<2.18" && cd "/mnt/d/QuakeLiveData/QL Server/qlsm-extra/.claude/worktrees/demo-stream-tunnel/addons/demo-stream" && /tmp/ans/bin/ansible-playbook --syntax-check -i localhost, playbooks/install_demo_stream_tunnel.yml'
```

Expected: `playbook: playbooks/install_demo_stream_tunnel.yml`, exit 0. If `python3 -m venv` is missing in WSL, stop and ask the operator rather than skipping the check.

- [ ] **Step 6: Commit**

```bash
git add addons/demo-stream/playbooks tests/test_addon_demo_stream.py
git commit -m "demo-stream: stunnel playbook and systemd unit for the host tunnel"
```

---

### Task 4: Host endpoints, task registration, host cleanup

**Files:**
- Modify: `addons/demo-stream/backend.py` (new routes after `update_stats_hub`; `register()`)
- Test: `tests/test_addon_demo_stream.py`

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces:
  - `GET /api/addons/demo-stream/hosts/<int:host_id>` -> `{"data": {"enabled": bool, "local_port": str}}`; 404 for unknown host.
  - `PUT /api/addons/demo-stream/hosts/<int:host_id>` body `{"enabled": bool, "local_port": str}`.
  - `TASKS['configure_host_tunnel']` - `ctx.task(timeout=300, lock_scope='host')` wrapper of `configure_host_demo_stream_tunnel_logic(host_id, enabled, port, cert_pem)`.
  - `ctx.on('host.delete')` handler `forget_host(host_id)` clearing both tunnel keys.

PUT decision order (each line is one test):
1. Unknown host -> 404.
2. `local_port` not a string, or not `''` and not digits in 1..65535 -> 400 `"local_port must be a port number (1-65535)."`, nothing stored.
3. Store port (`''` clears to default), commit.
4. `wanted = bool(enabled)`. If `not wanted and not is_host_tunnel_enabled` -> 200 `{"data": {...}, "message": "Tunnel settings saved."}`, nothing queued.
5. If `wanted`: relay not configured -> 409 `"Set the demo-stream relay host and port in Settings first."`; then `fetch_hub_tls_cert(host_id)`; `TunnelCertError` -> 409 with `str(exc)` as message, nothing queued.
6. Host not `HostStatus.ACTIVE` -> 400 (same wording as telemetry-relay's).
7. Lock: `acquire_lock('host', host.id, token, ttl=180)` false -> 409; else `update_host(host.id, status=HostStatus.CONFIGURING)` and `enqueue_task(TASKS['configure_host_tunnel'], host.id, wanted, port, cert_pem, lock_token=token, on_failure=host_job_failure_handler)`; exception -> release lock, 500. Success -> 202 `{"data": {"enabled": wanted, "local_port": port}, "message": "Demo stream tunnel configuration started."}`.

Enabled-and-wanted always re-queues (idempotent playbook): that is what makes a port edit reach the host.

- [ ] **Step 1: Write the failing tests**

```python
def test_get_host_tunnel_defaults(client, auth, host_id):
    # 200, data == {'enabled': False, 'local_port': '27999'}

def test_get_host_tunnel_unknown_host_404(client, auth): ...

@pytest.mark.parametrize('bad', ['0', '70000', '27 999', 'abc', 27999])
def test_put_rejects_bad_port(client, auth, host_id, bad):
    # 400; get_host_tunnel_port still '27999'

def test_put_enable_without_relay_is_409(client, auth, host_id): ...

def test_put_enable_when_hub_has_no_tls_is_409_and_queues_nothing(client, auth, host_id):
    # relay + stats-hub url set; patch tunnel_ops.fetch_hub_tls_cert side_effect=TunnelCertError('stats-hub has no TLS configured ...')
    # patch ui.tasks.enqueue_task -> assert_not_called; message contains 'no TLS'

def test_put_enable_queues_playbook_with_cert(client, auth, host_id):
    # fetch -> PEM; acquire_lock -> True; enqueue mocked
    # 202; enqueue.call_args.args[1:] == (host_id, True, '28000', PEM) for local_port '28000'
    # host status CONFIGURING

def test_put_port_change_on_enabled_tunnel_requeues_playbook(client, auth, host_id):
    # set_host_tunnel_enabled True first; PUT enabled True, local_port '28001' -> 202, enqueue called

def test_put_disable_when_already_off_saves_only(client, auth, host_id):
    # 200; enqueue not called; fetch not called

def test_put_disable_when_on_queues_disable(client, auth, host_id):
    # enabled flag on; PUT enabled False -> 202; args (host_id, False, '27999', '')

def test_host_delete_forgets_tunnel_keys(app, host_id):
    # set both keys; ui.addons dispatch of 'host.delete' (or call core host delete helper) -> rows gone
```

For the last test use the same dispatch call core uses for `host.delete`; find it with `grep -rn "'host.delete'" C:/Users/hellp/orca/workspaces/qlsm/QLSM/ui` before writing the test. If no test-friendly entry point exists, test `forget_host` through the registry's subscriber list instead and say so in the commit message.

- [ ] **Step 2: Run, expect FAIL** (404 on the new routes).

- [ ] **Step 3: Implement the two routes, `TASKS['configure_host_tunnel']` and `forget_host` in `addons/demo-stream/backend.py`.** Add `_host_or_404(host_id)` copied from telemetry-relay's backend. Import `fetch_hub_tls_cert` / `TunnelCertError` inside the handler from `.tunnel_ops` (so the test patch target is `qlsm_addon_demo_stream.tunnel_ops.fetch_hub_tls_cert`).

- [ ] **Step 4: Run, expect PASS** (whole file).

- [ ] **Step 5: Commit**

```bash
git add addons/demo-stream/backend.py tests/test_addon_demo_stream.py
git commit -m "demo-stream: host tunnel endpoints and playbook task"
```

---

### Task 5: Instance enable through the tunnel, telemetry server_id reuse

**Files:**
- Modify: `addons/demo-stream/instance_ops.py` (`enable_instance_demo_stream_logic`, module docstring)
- Modify: `addons/demo-stream/backend.py` (`enable_instance_stream`, `get_instance_stream_status`)
- Test: `tests/test_addon_demo_stream.py`

**Interfaces:**
- Consumes: Task 1 (`is_host_tunnel_enabled`, `get_host_tunnel_port`, `get_telemetry_server_id`, `set_telemetry_server_id`).
- Produces: new private helper `_resolve_server_id(instance, host_id) -> int` in `instance_ops.py` (raises the same exceptions `reserve_server_id` raises).

Behaviour:
- Endpoint `enable_instance_stream`: after the existing relay check (409), `not is_host_tunnel_enabled(instance.host_id)` -> 400 `"Enable the Demo Stream Tunnel on this instance's host first (Hosts -> Demo Stream Tunnel). Plain TCP to the relay is no longer configured."`.
- Task logic: same check first thing after relay/stats-hub checks -> `_finish(instance, False, <same text>)`.
- `_resolve_server_id`: telemetry id if set -> also `set_instance_server_id(instance.id, tid)` when it differs; else own id if set; else `reserve_server_id(instance.name, host_id)` and write it to **both** `demo_stream_stats_hub_server_id:` and `stats_hub_server_id:` (spec 4.3; see Open questions for why the second write may not stick).
- cvars written: `sv_demoStream '1'`, `sv_demoStreamHost '127.0.0.1'`, `sv_demoStreamPort get_host_tunnel_port(host_id)`, `sv_demoStreamToken token`.
- Status endpoint: after the relay check, tunnel off -> `{'ok': False, 'label': 'Tunnel not enabled on host'}`.

- [ ] **Step 1: Write the failing tests** (every test that runs the logic does `monkeypatch.chdir(tmp_path)` first, and patches `qlsm_addon_demo_stream.instance_ops._register_route` and `ui.tasks.enqueue_task` -> `Mock(id='job1')`)

```python
def test_enable_endpoint_400_without_host_tunnel(client, auth, instance_id):
    # relay set, tunnel off -> 400, message mentions 'Demo Stream Tunnel'

def test_enable_writes_loopback_and_tunnel_port(app, instance_id, tmp_path, monkeypatch):
    # tunnel on, port '28000', relay '70.34.223.191:27999', stats-hub set, own server_id 7
    # ok is True; configs/germany/<id>/server.cfg contains
    #   'set sv_demoStreamHost "127.0.0.1"' and 'set sv_demoStreamPort "28000"'
    # and does NOT contain '70.34.223.191'

def test_enable_logic_refuses_without_tunnel(app, instance_id, tmp_path, monkeypatch):
    # tunnel off -> (False, msg) and no server.cfg written

def test_enable_reuses_telemetry_server_id(app, instance_id, ...):
    # stats_hub_server_id:<id> = 42; reserve_server_id patched -> assert_not_called
    # _register_route called with server_id 42; demo_stream_stats_hub_server_id:<id> == '42'

def test_enable_prefers_telemetry_server_id_over_own(app, instance_id, ...):
    # own = 7, telemetry = 42 -> route uses 42, own key now '42'

def test_enable_reserves_and_writes_both_keys_without_telemetry(app, instance_id, ...):
    # no ids; reserve -> 99; both AppSetting keys == '99'

def test_status_reports_tunnel_off(client, auth, instance_id):
    # relay set, tunnel off -> data == {'ok': False, 'label': 'Tunnel not enabled on host'}
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement** the behaviour above. Update the `instance_ops.py` docstring: the instance now points at the local stunnel, server_id comes from telemetry when present.

- [ ] **Step 4: Run, expect PASS** (whole file).

- [ ] **Step 5: Commit**

```bash
git add addons/demo-stream/instance_ops.py addons/demo-stream/backend.py tests/test_addon_demo_stream.py
git commit -m "demo-stream: stream through the host tunnel, reuse telemetry server_id"
```

---

### Task 6: Manifest 1.2.0, host panel, package

**Files:**
- Modify: `addons/demo-stream/qlsm-addon.json`
- Modify (generated): `qlsm-repository.json`, `packages/demo-stream.zip`
- Modify: `README.md` (Addons table row for `demo-stream`)
- Test: `tests/test_addon_demo_stream.py`

**Interfaces:**
- Consumes: routes from Task 4.

Manifest changes:
- `"version": "1.2.0"`.
- `description`: drop "nothing to install per host"; say each game host runs a stunnel client (set up from the host's Demo Stream Tunnel panel) that carries the stream to stats-hub over TLS with the hub's certificate pinned.
- `ui.host_menu`: `[{ "id": "demo-stream-tunnel", "label": "Demo Stream Tunnel", "icon": "share", "panel": "host_tunnel" }]`.
- `ui.panels.host_tunnel`: `kind: form`, `load: "GET hosts/{host_id}"`, `submit: "PUT hosts/{host_id}"`, description "Installs stunnel on this host and pins the stats-hub TLS certificate, so instances stream to 127.0.0.1 and the tunnel carries it to the relay over TLS. Changing the port re-runs the setup; re-enable streaming on each instance afterwards so its server.cfg picks up the new port.", fields: `{ "key": "enabled", "type": "bool", "label": "Enabled", "default": false, "description": "Installs and starts the tunnel on this host." }`, `{ "key": "local_port", "type": "string", "label": "Local port", "placeholder": "27999", "description": "Port the tunnel listens on at 127.0.0.1. Leave blank for 27999." }`.
- `relay_settings.fields[port].placeholder`: `"27999"`; its description: TLS ingest port of stats-hub.
- `instance_stream.description`: mention it requires the host tunnel.

- [ ] **Step 1: Write the failing test**

```python
def test_manifest_declares_host_tunnel_panel():
    m = json.loads((ADDONS_DIR / 'demo-stream' / 'qlsm-addon.json').read_text(encoding='utf-8'))
    assert m['version'] == '1.2.0'
    assert m['ui']['host_menu'][0]['panel'] == 'host_tunnel'
    p = m['ui']['panels']['host_tunnel']
    assert (p['load'], p['submit']) == ('GET hosts/{host_id}', 'PUT hosts/{host_id}')
    assert [f['key'] for f in p['fields']] == ['enabled', 'local_port']
    assert next(f for f in p['fields'] if f['key'] == 'local_port')['placeholder'] == '27999'
    relay_port = next(f for f in m['ui']['panels']['relay_settings']['fields'] if f['key'] == 'port')
    assert relay_port['placeholder'] == '27999'
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Edit the manifest and the README row.** The `app` fixture loads the addon through qlsm's manifest validator, so the whole test file passing also proves the manifest validates.

- [ ] **Step 4: Run the whole file, expect PASS.** Then:

```bash
python generate_manifest.py
python check_manifest_hashes.py
```

Expected: the second prints no mismatch and exits 0; `git diff qlsm-repository.json` shows the `demo-stream` entry at `1.2.0` with a new sha256 and the new description.

- [ ] **Step 5: Run the full qlsm-extra suite once** (`... python -m pytest tests/ -q -p no:cacheprovider`), expect no new failures versus `main`.

- [ ] **Step 6: Commit**

```bash
git add addons/demo-stream/qlsm-addon.json qlsm-repository.json packages/demo-stream.zip README.md tests/test_addon_demo_stream.py
git commit -m "demo-stream 1.2.0: host tunnel panel, relay port 27999"
```

---

### Task 7: Monolith docs - `skills/qlsm-dev/reference/telemetry-and-stats-hub.md` (separate repo, separate commit)

This file belongs to the monolith git at `D:/QuakeLiveData/QL Server` (branch `master`, no remote), not to qlsm-extra. Per `docs/policies/concurrency.md`, do not edit the shared monolith checkout directly: create a monolith worktree (`git -C "D:/QuakeLiveData/QL Server" worktree add .claude/worktrees/docs-demo-stream-tunnel -b docs/demo-stream-tunnel master`), edit there, commit, then merge into `master` from the main checkout only after `git diff` shows only this file. Do it after Tasks 1-6 are merged, so the doc describes shipped code.

**Files:**
- Modify: `skills/qlsm-dev/reference/telemetry-and-stats-hub.md` (monolith)

Content (spec 4.5, first bullet - only the parts this plan delivers are stated as facts; the stats-hub and engine parts are written as "per spec 4.1/4.2" until those land, verify each against `ql-stats-hub` code before stating it as shipped):
- Section "Where stats-hub settings live in qlsm": replace the stale `ui/stats_hub.py` ... `feature` paragraph - core module is gone; each addon has a private `stats_hub.py`; demo-stream reads telemetry's `stats_hub_server_id:<instance_id>` directly to share the id.
- Section "Live demo stream": addon paths (`qlsm-extra/addons/demo-stream/`: `backend.py`, `instance_ops.py`, `tunnel_ops.py`, `playbooks/install_demo_stream_tunnel.yml`); host panel Demo Stream Tunnel and its two AppSetting keys; on-host layout (`/home/ql/demo-stream-tunnel/{hub.pem,stunnel.conf}`, `ql-demo-stream-tunnel.service`); instance cvars `sv_demoStreamHost 127.0.0.1` + tunnel port; cert from `GET /api/demo-stream/tls-cert`, pinned via `CAfile` + `verifyPeer`; ingest port 27999; `STATS_HUB_DEMO_STREAM_ENABLED`; keyframe `sv_demoStreamKeyframeSec` (engine, spec 4.1). Remove the obsolete endpoint list `GET/POST /api/instances/<id>/demo-stream`, `GET/PUT /api/settings/demo-stream-relay`.

- [ ] **Step 1: Check every env/cvar name you write against its source** (`grep -rn STATS_HUB_DEMO_STREAM_ENABLED "D:/QuakeLiveData/QL Server/ql-stats-hub"`, fork source for `sv_demoStreamKeyframeSec`). Not found -> write "planned (spec 4.x), not yet in code".
- [ ] **Step 2: Edit the file.**
- [ ] **Step 3: Commit in the monolith worktree**

```bash
git add skills/qlsm-dev/reference/telemetry-and-stats-hub.md
git commit -m "docs: qlsm-dev telemetry reference - demo-stream tunnel and TLS"
```

---

## Open questions (need the operator, do not guess)

1. **Second server_id write gets undone.** Spec 4.3 says a freshly reserved id is written to both keys. But telemetry-relay's `instance.config_applied` hook (`addons/telemetry-relay/backend.py` `resync_server_id` -> `instance_ops.sync_instance_server_id_from_config`) re-derives `stats_hub_server_id:<id>` from `qlx_statsHubServerId`/`qlx_statsHubUnifiedEnabled` in server.cfg and clears it when telemetry is not wired - and demo-stream's own enable queues exactly that config apply. So with telemetry-relay installed, the shared write lasts until the restart, and a later telemetry enable reserves a different id. Options: (a) keep the spec behaviour (harmless, just ineffective); (b) also have telemetry's enable prefer `demo_stream_stats_hub_server_id:` (a telemetry-relay change, out of this plan). Plan implements (a).
2. **stunnel binary path and foreground.** `ExecStart=/usr/bin/stunnel` and `foreground = yes` are from general stunnel4/Debian knowledge, not verified on a game host. Before the live check run on germany: `dpkg -L stunnel4 | grep bin/` and `stunnel -version`; adjust the unit if the binary is only `/usr/bin/stunnel4`.
3. **pid file.** Whether stunnel (version on the hosts) tries to write a default pid file that user `ql` cannot write is unverified; if the unit fails, add `pid =` (empty) to the template.
4. **Live check** (spec section 6, step 2) needs the stats-hub TLS side (spec 4.2) deployed first; it is not part of this plan's done criteria but is required before the addon is called done.
