"""Local web dashboard integrating the simulated network, monitoring, troubleshooting, and digital twin.

Uses Python's built-in http.server to provide a zero-dependency, real-time web dashboard
with automated 10-second refresh and interactive fault injection / recovery controls.
"""

from __future__ import annotations

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

from ..automation.deploy import AutomationDeployer
from ..core.state_engine import StateEngine
from ..simulation.sim_network import SimulatedNetwork
from ..twin.engine import DigitalTwinEngine
from .service import MonitoringService

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Network Digital Twin & Monitoring Dashboard</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --card-border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --primary: #38bdf8;
      --success: #22c55e;
      --warning: #f59e0b;
      --danger: #ef4444;
      --font-mono: 'Consolas', 'Courier New', monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      padding: 1.5rem;
      line-height: 1.5;
    }
    header {
      margin-bottom: 1.5rem;
      padding-bottom: 1rem;
      border-bottom: 1px solid var(--card-border);
    }
    .badge-sim {
      display: inline-block;
      background: rgba(56, 189, 248, 0.15);
      color: var(--primary);
      border: 1px solid rgba(56, 189, 248, 0.3);
      padding: 0.25rem 0.6rem;
      border-radius: 4px;
      font-size: 0.8rem;
      font-weight: 600;
      letter-spacing: 0.5px;
      text-transform: uppercase;
      margin-bottom: 0.5rem;
    }
    h1 { font-size: 1.75rem; font-weight: 700; color: #fff; margin-bottom: 0.25rem; }
    .subtitle { color: var(--text-muted); font-size: 0.9rem; }
    .alert-banner {
      background: rgba(56, 189, 248, 0.1);
      border-left: 4px solid var(--primary);
      padding: 0.75rem 1rem;
      border-radius: 4px;
      margin-top: 0.75rem;
      font-size: 0.85rem;
      color: #cbd5e1;
    }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.25rem; margin-bottom: 1.5rem; }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 1.25rem;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
    }
    .card h2 { font-size: 1.1rem; margin-bottom: 0.75rem; color: #e2e8f0; display: flex; justify-content: space-between; align-items: center; }
    .status-badge {
      font-size: 0.75rem;
      padding: 0.2rem 0.5rem;
      border-radius: 9999px;
      font-weight: 600;
      text-transform: uppercase;
    }
    .badge-up { background: rgba(34, 197, 94, 0.2); color: var(--success); border: 1px solid var(--success); }
    .badge-down { background: rgba(239, 68, 68, 0.2); color: var(--danger); border: 1px solid var(--danger); }
    .badge-warn { background: rgba(245, 158, 11, 0.2); color: var(--warning); border: 1px solid var(--warning); }
    
    .gauge-container {
      text-align: center;
      padding: 1rem 0;
    }
    .gauge-score {
      font-size: 3.5rem;
      font-weight: 800;
      line-height: 1;
      font-family: var(--font-mono);
      transition: color 0.3s;
    }
    .gauge-score.healthy { color: var(--success); }
    .gauge-score.degraded { color: var(--warning); }
    .gauge-msg { font-size: 0.95rem; font-weight: 600; margin-top: 0.5rem; }

    .btn-group { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-top: 1rem; }
    button {
      background: #334155;
      color: #fff;
      border: 1px solid #475569;
      padding: 0.5rem 1rem;
      border-radius: 6px;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
    }
    button:hover { background: #475569; }
    button.btn-danger { background: #dc2626; border-color: #ef4444; }
    button.btn-danger:hover { background: #b91c1c; }
    button.btn-success { background: #16a34a; border-color: #22c55e; }
    button.btn-success:hover { background: #15803d; }
    button.btn-primary { background: #0284c7; border-color: #38bdf8; }
    button.btn-primary:hover { background: #0369a1; }

    .table-container { max-height: 220px; overflow-y: auto; margin-top: 0.5rem; }
    table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
    th, td { padding: 0.45rem 0.6rem; text-align: left; border-bottom: 1px solid var(--card-border); }
    th { background: #0f172a; color: var(--text-muted); font-weight: 600; position: sticky; top: 0; }
    tr:hover { background: rgba(255, 255, 255, 0.02); }

    .cli-box {
      background: #090d16;
      border: 1px solid var(--card-border);
      border-radius: 6px;
      padding: 0.75rem;
      font-family: var(--font-mono);
      font-size: 0.8rem;
      color: #38bdf8;
      max-height: 240px;
      overflow-y: auto;
      white-space: pre-wrap;
    }
    .cli-tabs { display: flex; gap: 0.25rem; margin-bottom: 0.5rem; }
    .cli-tab-btn {
      background: #1e293b;
      font-size: 0.75rem;
      padding: 0.35rem 0.75rem;
      border-radius: 4px 4px 0 0;
      border-bottom: none;
    }
    .cli-tab-btn.active {
      background: #090d16;
      border-color: var(--primary);
      color: var(--primary);
    }
    .refresh-pill {
      font-size: 0.8rem;
      color: var(--text-muted);
      font-family: var(--font-mono);
    }
    .alerts-container {
      margin-top: 0.5rem;
      padding: 0.5rem;
      background: rgba(239, 68, 68, 0.1);
      border: 1px solid rgba(239, 68, 68, 0.3);
      border-radius: 6px;
    }
    .alert-item { color: #fca5a5; font-family: var(--font-mono); font-size: 0.8rem; padding: 0.25rem 0; }
  </style>
</head>
<body>

  <header>
    <div>
      <span class="badge-sim">Pure Software Simulation</span>
      <h1>Network Digital Twin & Monitoring Dashboard</h1>
      <p class="subtitle">Autonomous Network Management, SNMP Telemetry, Troubleshooting & Golden State Verification</p>
      <div class="alert-banner">
        <strong>Notice:</strong> This environment is 100% simulated in-process in Python. All Cisco devices, SSH sessions, and SNMP agents run offline on the shared state model without accessing physical hardware.
      </div>
    </div>
  </header>

  <div class="grid">
    <!-- Digital Twin Integrity Card -->
    <div class="card">
      <h2>
        <span>Digital Twin Integrity</span>
        <span id="dt-badge" class="status-badge badge-up">HEALTHY</span>
      </h2>
      <div class="gauge-container">
        <div id="dt-score" class="gauge-score healthy">100%</div>
        <div id="dt-msg" class="gauge-msg" style="color: var(--success);">SYSTEM HEALTHY - MATCHES TWIN MODEL</div>
        <div class="subtitle" style="margin-top: 0.25rem;" id="dt-ratio">50 / 50 monitored interfaces match Golden State</div>
      </div>
      <div id="dt-alerts-box" style="display: none;">
        <div class="alerts-container">
          <strong style="color: #f87171; font-size: 0.8rem;">Active Deviation Alerts:</strong>
          <div id="dt-alerts-list"></div>
        </div>
      </div>
    </div>

    <!-- Troubleshooting & Fault Injection Card -->
    <div class="card">
      <h2>Troubleshooting & Fault Injection (Part 4)</h2>
      <p class="subtitle">Simulate real-world link failure on Switch A and trigger remediation:</p>
      <div class="btn-group">
        <button id="btn-shutdown" class="btn-danger" onclick="triggerAction('shutdown')">
          Shutdown SW1 Gi1/0/17
        </button>
        <button id="btn-recover" class="btn-success" onclick="triggerAction('recover')">
          No Shutdown (Recover)
        </button>
        <button class="btn-primary" onclick="triggerAction('automate')">
          Redeploy Automation
        </button>
      </div>
      <div style="margin-top: 1rem; border-top: 1px solid var(--card-border); padding-top: 0.75rem;">
        <span class="refresh-pill" id="refresh-timer">Next update in: 10s</span>
        <button style="float: right; padding: 0.2rem 0.6rem; font-size: 0.75rem;" onclick="loadData()">Refresh Now</button>
      </div>
    </div>
  </div>

  <!-- Diagnostic Console -->
  <div class="card" style="margin-bottom: 1.5rem;">
    <h2>
      <span>Live Cisco IOS Diagnostic Console (SW1)</span>
      <span class="subtitle">Diagnostic verification matching Section 4.1.3</span>
    </h2>
    <div class="cli-tabs">
      <button class="cli-tab-btn active" onclick="switchDiagTab(this, 'show interfaces GigabitEthernet1/0/17')">show interfaces Gi1/0/17</button>
      <button class="cli-tab-btn" onclick="switchDiagTab(this, 'show interfaces status')">show interfaces status</button>
      <button class="cli-tab-btn" onclick="switchDiagTab(this, 'show ip interface brief')">show ip interface brief</button>
    </div>
    <div class="cli-box" id="cli-output">Loading diagnostics...</div>
  </div>

  <!-- Devices & Interfaces Grid -->
  <div class="grid">
    <!-- Router Card -->
    <div class="card">
      <h2>
        <span>ROUTER-GW (R1)</span>
        <span id="r1-badge" class="status-badge badge-up">REACHABLE</span>
      </h2>
      <p class="subtitle" style="margin-bottom: 0.5rem;">IP: <strong>192.168.10.1</strong> | Type: Router | Uptime: <span id="r1-uptime">-</span></p>
      <div class="table-container">
        <table>
          <thead>
            <tr><th>Interface</th><th>Mode</th><th>Status</th></tr>
          </thead>
          <tbody id="r1-tbody"></tbody>
        </table>
      </div>
    </div>

    <!-- Switch A Card -->
    <div class="card">
      <h2>
        <span>SWITCH-A (SW1)</span>
        <span id="swa-badge" class="status-badge badge-up">REACHABLE</span>
      </h2>
      <p class="subtitle" style="margin-bottom: 0.5rem;">IP: <strong>192.168.10.2</strong> | Management: VLAN 10 | Uptime: <span id="swa-uptime">-</span></p>
      <div class="table-container">
        <table>
          <thead>
            <tr><th>Interface</th><th>VLAN</th><th>Status</th></tr>
          </thead>
          <tbody id="swa-tbody"></tbody>
        </table>
      </div>
    </div>

    <!-- Switch B Card -->
    <div class="card">
      <h2>
        <span>SWITCH-B (SW2)</span>
        <span id="swb-badge" class="status-badge badge-up">REACHABLE</span>
      </h2>
      <p class="subtitle" style="margin-bottom: 0.5rem;">IP: <strong>192.168.30.2</strong> | Management: VLAN 30 | Uptime: <span id="swb-uptime">-</span></p>
      <div class="table-container">
        <table>
          <thead>
            <tr><th>Interface</th><th>VLAN</th><th>Status</th></tr>
          </thead>
          <tbody id="swb-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Recent Monitoring Events Card -->
  <div class="card">
    <h2>Recent Monitoring & Operational Events (SNMP)</h2>
    <div class="table-container" style="max-height: 180px;">
      <table>
        <thead>
          <tr><th>Timestamp</th><th>Level</th><th>Device</th><th>Event</th><th>Message</th></tr>
        </thead>
        <tbody id="events-tbody">
          <tr><td colspan="5" style="color: var(--text-muted);">No events recorded yet.</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <script>
    let countdown = 10;
    let currentDiagCommand = 'show interfaces GigabitEthernet1/0/17';

    async function loadData() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        renderDashboard(data);
        await updateDiagnostics(currentDiagCommand);
        countdown = 10;
      } catch (err) {
        console.error('Failed to load status:', err);
      }
    }

    function renderDashboard(data) {
      // 1. Digital Twin
      const score = data.digital_twin.score;
      const isHealthy = data.digital_twin.is_healthy;
      const scoreEl = document.getElementById('dt-score');
      const msgEl = document.getElementById('dt-msg');
      const badgeEl = document.getElementById('dt-badge');
      const ratioEl = document.getElementById('dt-ratio');
      const alertsBox = document.getElementById('dt-alerts-box');
      const alertsList = document.getElementById('dt-alerts-list');

      scoreEl.innerText = score + '%';
      msgEl.innerText = data.digital_twin.status_message;
      ratioEl.innerText = `${data.digital_twin.total_matching} / ${data.digital_twin.total_monitored} monitored interfaces match Golden State`;

      if (isHealthy) {
        scoreEl.className = 'gauge-score healthy';
        msgEl.style.color = 'var(--success)';
        badgeEl.className = 'status-badge badge-up';
        badgeEl.innerText = 'HEALTHY';
        alertsBox.style.display = 'none';
      } else {
        scoreEl.className = 'gauge-score degraded';
        msgEl.style.color = 'var(--warning)';
        badgeEl.className = 'status-badge badge-warn';
        badgeEl.innerText = 'DEVIATION DETECTED';
        alertsBox.style.display = 'block';
        alertsList.innerHTML = data.digital_twin.alerts.map(a => `<div class="alert-item">${a.message}</div>`).join('');
      }

      // 2. Devices
      data.devices.forEach(dev => {
        let tbody, uptimeEl, badge;
        if (dev.name === 'ROUTER-GW') {
          tbody = document.getElementById('r1-tbody');
          uptimeEl = document.getElementById('r1-uptime');
          badge = document.getElementById('r1-badge');
        } else if (dev.name === 'SWITCH-A') {
          tbody = document.getElementById('swa-tbody');
          uptimeEl = document.getElementById('swa-uptime');
          badge = document.getElementById('swa-badge');
        } else if (dev.name === 'SWITCH-B') {
          tbody = document.getElementById('swb-tbody');
          uptimeEl = document.getElementById('swb-uptime');
          badge = document.getElementById('swb-badge');
        }
        if (!tbody) return;

        uptimeEl.innerText = dev.sys_uptime + ' ticks';
        badge.className = dev.is_reachable ? 'status-badge badge-up' : 'status-badge badge-down';
        badge.innerText = dev.is_reachable ? 'REACHABLE' : 'UNREACHABLE';

        tbody.innerHTML = dev.interfaces.map(iface => {
          const isUp = iface.is_up;
          const statusBadge = isUp 
            ? '<span class="status-badge badge-up">UP</span>' 
            : '<span class="status-badge badge-down">DOWN</span>';
          const modeOrVlan = iface.mode || iface.vlan || '-';
          return `<tr>
            <td style="font-family: var(--font-mono); font-weight: ${iface.name.includes('17') ? '700; color: #38bdf8;' : 'normal'}">${iface.name}</td>
            <td>${modeOrVlan}</td>
            <td>${statusBadge}</td>
          </tr>`;
        }).join('');
      });

      // 3. Events
      const eventsTbody = document.getElementById('events-tbody');
      if (data.events && data.events.length > 0) {
        eventsTbody.innerHTML = data.events.slice(-8).reverse().map(e => `
          <tr>
            <td style="font-family: var(--font-mono); color: var(--text-muted);">${e.timestamp}</td>
            <td><span class="status-badge ${e.level === 'ERROR' ? 'badge-down' : e.level === 'WARNING' ? 'badge-warn' : 'badge-up'}">${e.level}</span></td>
            <td><strong>${e.device_name}</strong></td>
            <td>${e.event_type}</td>
            <td>${e.message}</td>
          </tr>
        `).join('');
      }
    }

    async function switchDiagTab(btn, cmd) {
      document.querySelectorAll('.cli-tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentDiagCommand = cmd;
      await updateDiagnostics(cmd);
    }

    async function updateDiagnostics(cmd) {
      try {
        const res = await fetch('/api/diagnostics', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ device: 'SWITCH-A', command: cmd })
        });
        const data = await res.json();
        document.getElementById('cli-output').innerText = data.output;
      } catch (err) {
        console.error('Diagnostics query failed:', err);
      }
    }

    async function triggerAction(action) {
      try {
        let endpoint = '/api/troubleshoot/' + action;
        if (action === 'automate') endpoint = '/api/automate';
        await fetch(endpoint, { method: 'POST' });
        await loadData();
      } catch (err) {
        console.error('Action failed:', err);
      }
    }

    // Timer loop for 10-second refresh
    setInterval(() => {
      countdown--;
      if (countdown <= 0) {
        loadData();
      } else {
        document.getElementById('refresh-timer').innerText = `Next update in: ${countdown}s`;
      }
    }, 1000);

    // Initial load
    loadData();
  </script>
</body>
</html>
"""


class DashboardRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request handler serving dashboard UI and REST API."""

    state_engine: StateEngine = None  # type: ignore
    monitoring_service: MonitoringService = None  # type: ignore
    twin_engine: DigitalTwinEngine = None  # type: ignore
    sim_net: SimulatedNetwork = None  # type: ignore

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress standard HTTP server access log to keep console clean."""
        pass

    def do_GET(self) -> None:
        """Handle dashboard HTML and status API requests."""
        parsed_url = urllib.parse.urlparse(self.path)

        if parsed_url.path == "/" or parsed_url.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
            return

        if parsed_url.path == "/api/status":
            self._handle_status_api()
            return

        self.send_error(404, "Endpoint not found")

    def do_POST(self) -> None:
        """Handle troubleshooting actions and diagnostics."""
        parsed_url = urllib.parse.urlparse(self.path)

        if parsed_url.path == "/api/status":
            self._handle_status_api()
            return

        if parsed_url.path == "/api/troubleshoot/shutdown":
            # Simulate failure: shutdown SW1 Gi1/0/17
            self.state_engine.set_interface_status("SWITCH-A", "GigabitEthernet1/0/17", "DOWN")
            self.monitoring_service.record_event(
                "FAULT_INJECTED",
                "SWITCH-A",
                "GigabitEthernet1/0/17",
                "Administrative shutdown invoked on SWITCH-A GigabitEthernet1/0/17 (Simulation).",
                level="WARNING",
            )
            self._send_json({"success": True, "action": "shutdown", "target": "SWITCH-A:GigabitEthernet1/0/17"})
            return

        if parsed_url.path == "/api/troubleshoot/recover":
            # Simulate recovery: no shutdown on SW1 Gi1/0/17
            self.state_engine.set_interface_status("SWITCH-A", "GigabitEthernet1/0/17", "UP")
            self.monitoring_service.record_event(
                "FAULT_RECOVERED",
                "SWITCH-A",
                "GigabitEthernet1/0/17",
                "Administrative 'no shutdown' applied to SWITCH-A GigabitEthernet1/0/17.",
                level="INFO",
            )
            self._send_json({"success": True, "action": "recover", "target": "SWITCH-A:GigabitEthernet1/0/17"})
            return

        if parsed_url.path == "/api/diagnostics":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                data = json.loads(body.decode("utf-8"))
            except Exception:
                data = {}
            cmd = data.get("command", "show interfaces GigabitEthernet1/0/17")
            device = data.get("device", "SWITCH-A")
            out = self.sim_net.execute_cisco_command(device, cmd)
            self._send_json({"device": device, "command": cmd, "output": out})
            return

        if parsed_url.path == "/api/automate":
            deployer = AutomationDeployer(state_engine=self.state_engine)
            actions = deployer.deploy_all()
            self._send_json({"success": True, "actions_count": len(actions)})
            return

        self.send_error(404, "Unknown action endpoint")

    def _handle_status_api(self) -> None:
        """Compile status across monitoring, digital twin, and devices."""
        # 1. Monitoring poll
        poll_results = self.monitoring_service.poll_all_devices(reload_state=True)
        devices_data = []

        for p in poll_results:
            dev = self.state_engine.get_device(p.device_name)
            if_list = []
            for iface_poll in p.interfaces:
                live_if = dev.get_interface(iface_poll.name) if dev else None
                mode_vlan = ""
                if live_if:
                    if live_if.mode == "access":
                        mode_vlan = f"VLAN {live_if.access_vlan}"
                    elif live_if.mode == "trunk":
                        mode_vlan = f"Trunk ({','.join(str(v) for v in live_if.allowed_vlans)})"
                    elif live_if.mode == "subinterface":
                        mode_vlan = f"dot1Q {live_if.dot1q_vlan}"
                    elif live_if.mode == "svi":
                        mode_vlan = "SVI"
                if_list.append({
                    "name": iface_poll.name,
                    "status_code": iface_poll.status_code,
                    "status_text": iface_poll.status_text,
                    "is_up": iface_poll.is_up,
                    "mode": mode_vlan,
                })
            devices_data.append({
                "name": p.device_name,
                "ip": p.device_ip,
                "is_reachable": p.is_reachable,
                "sys_uptime": p.sys_uptime,
                "interfaces": if_list,
            })

        # 2. Digital Twin
        dt_res = self.twin_engine.check_integrity()
        alerts_data = [
            {
                "device_name": a.device_name,
                "interface_name": a.interface_name,
                "actual_status": a.actual_status,
                "expected_status": a.expected_status,
                "message": a.message,
            }
            for a in dt_res.alerts
        ]

        # 3. Events
        events_data = [
            {
                "timestamp": e.timestamp,
                "level": e.level,
                "device_name": e.device_name,
                "event_type": e.event_type,
                "message": e.message,
            }
            for e in self.monitoring_service.events_log
        ]

        payload = {
            "devices": devices_data,
            "digital_twin": {
                "score": dt_res.score,
                "is_healthy": dt_res.is_healthy,
                "status_message": dt_res.status_message,
                "total_monitored": dt_res.total_monitored,
                "total_matching": dt_res.total_matching,
                "alerts": alerts_data,
            },
            "events": events_data,
        }
        self._send_json(payload)

    def _send_json(self, data: Dict[str, Any], status: int = 200) -> None:
        """Helper to return JSON response."""
        resp = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)


def create_dashboard_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    state_engine: Optional[StateEngine] = None,
    golden_path: Optional[Path] = None,
) -> HTTPServer:
    """Create and configure the dashboard HTTPServer instance."""
    engine = state_engine if state_engine is not None else StateEngine()
    golden_file = golden_path or Path("data") / "network_golden_state.json"
    if not golden_file.exists() and Path("network_golden_state.json").exists():
        golden_file = Path("network_golden_state.json")

    twin = DigitalTwinEngine(state_engine=engine, golden_state_path=golden_file)
    monitoring = MonitoringService(state_engine=engine)
    sim_net = SimulatedNetwork(state_engine=engine)

    # Attach instances to handler class
    DashboardRequestHandler.state_engine = engine
    DashboardRequestHandler.monitoring_service = monitoring
    DashboardRequestHandler.twin_engine = twin
    DashboardRequestHandler.sim_net = sim_net

    return HTTPServer((host, port), DashboardRequestHandler)
