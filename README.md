# DDoS Attack — Simulation, Detection and Prevention

### Phase 1: Attack Simulation on a Web Server

**CS559 — Network Security | Binghamton University, Watson School of Engineering**

> Implement a DDoS attack on a web server that incorporates an ML-based defense mechanism. Whenever a DDoS attack is detected, the ML model will identify and prevent it in real time — demonstrating both the attack vector and an automated, intelligent countermeasure.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Infrastructure](#infrastructure)
- [Repository Structure](#repository-structure)
- [Setup Guide](#setup-guide)
  - [1. Provision GCP VMs](#1-provision-gcp-vms)
  - [2. GCP Firewall Rules](#2-gcp-firewall-rules)
  - [3. Server VM Setup](#3-server-vm-setup)
  - [4. Botmaster VM Setup](#4-botmaster-vm-setup)
  - [5. Bot VM Setup](#5-bot-vm-setup)
  - [6. Legitimate Traffic VM Setup](#6-legitimate-traffic-vm-setup)
- [Running the Lab](#running-the-lab)
  - [Start the Server](#start-the-server)
  - [Start Legitimate Traffic](#start-legitimate-traffic)
  - [Launch the Attack](#launch-the-attack)
  - [Stop the Attack](#stop-the-attack)
- [Attack Phases](#attack-phases)
- [Monitoring Stack](#monitoring-stack)
- [How It Works](#how-it-works)
- [Phase 2 — ML-Based Detection (Upcoming)](#phase-2--ml-based-detection-upcoming)
- [License](#license)

---

## Overview

This project builds a **complete DDoS attack simulation lab on Google Cloud Platform (GCP)** for educational purposes. A botnet of three geographically distributed VMs launches an escalating **Layer 7 HTTP flood attack** against a target web server running a Flask application behind an nginx reverse proxy. The attack is monitored in real time using a Grafana dashboard powered by Prometheus and Loki.

**Key design decisions:**
- **Layer 7 (Application Layer)** — GCP's Cloud Armor already handles Layer 3/4 (SYN floods, UDP amplification). This lab targets the application layer, which bypasses network-level protections entirely.
- **Synchronous Flask/Gunicorn with 3 workers** — Intentionally limited to create a demonstrable bottleneck. Three persistent connections saturate the entire server.
- **`/heavy` endpoint** — Performs 500,000 CPU iterations + 0.5s sleep per request, simulating a real database-backed API call.
- **Full observability stack** — Prometheus, Loki, Grafana, and exporters provide real-time attack visibility and generate labelled traffic data for ML training in Phase 2.

---

## Architecture

```
                        ┌─────────────────────────────────────────────────────┐
                        │              ddos-server (us-central1-a)            │
                        │         Ubuntu 22.04 | 4 vCPU | 8 GB RAM           │
                        │                                                     │
  ┌──────────┐          │  ┌───────────┐    ┌──────────────┐                  │
  │ Bot-1    │──────┐   │  │   nginx   │───▶│ Flask/Gunicorn│                 │
  │ us-c1-a  │      │   │  │  :80      │    │ 3 workers     │                 │
  └──────────┘      │   │  └───────────┘    └──────────────┘                  │
                    │   │        │                                             │
  ┌──────────┐      ├──▶│        ▼ logs                                       │
  │ Bot-2    │──────┤   │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
  │ us-c1-b  │      │   │  │ Promtail │─▶│   Loki   │◀─│ Grafana  │          │
  └──────────┘      │   │  └──────────┘  └──────────┘  │  :3000   │          │
                    │   │                               └──────────┘          │
  ┌──────────┐      │   │  ┌───────────┐  ┌────────────┐     ▲               │
  │ Bot-3    │──────┘   │  │  Node     │─▶│ Prometheus │─────┘               │
  │ na-ne1-c │          │  │  Exporter │  │   :9090    │                      │
  └──────────┘          │  └───────────┘  └────────────┘                      │
                        └─────────────────────────────────────────────────────┘
  ┌──────────────┐                │
  │ Botmaster    │────SSH────────▶│ (controls all 3 bots)
  │ us-c1-b      │                │
  └──────────────┘

  ┌──────────────┐
  │ Legit Traffic│──── HTTP ─────▶ :80 (simulated students from Finland)
  │ eu-north1-c  │
  └──────────────┘
```

---

## Infrastructure

### GCP Virtual Machines

| VM Name | Role | Machine Type | vCPU | RAM | Disk | Zone |
|---------|------|-------------|------|-----|------|------|
| `ddos-server` | Target web server | e2-custom-4-8192 | 4 | 8 GB | 50 GB SSD | us-central1-a |
| `ddos-botmaster` | Attack orchestrator | e2-medium | 2 | 4 GB | 10 GB | us-central1-b |
| `ddos-bot-1` | Attack bot node | e2-micro | 0.25 | 1 GB | 10 GB | us-central1-a |
| `ddos-bot-2` | Attack bot node | e2-micro | 0.25 | 1 GB | 10 GB | us-central1-b |
| `ddos-bot-3` | Attack bot node | e2-micro | 0.25 | 1 GB | 10 GB | northamerica-northeast1-c |
| `legittraffic` | Simulated student users | e2-micro | 0.25 | 1 GB | 10 GB | europe-north1-c |

### Docker Container Stack (Server VM)

| Container | Image | Port | Purpose |
|-----------|-------|------|---------|
| `ddos-flask` | python:3.11-slim + Gunicorn | 5000 (internal) | Target Flask web app — 3 sync workers |
| `ddos-nginx` | nginx:1.25-alpine | 80 (public) | Reverse proxy with rate limiting and IP blocking |
| `ddos-loki` | grafana/loki:2.9.0 | 3100 | Log aggregation from Promtail |
| `ddos-promtail` | grafana/promtail:2.9.0 | Internal | Tails nginx access logs → Loki |
| `ddos-prometheus` | prom/prometheus:latest | 9090 | Metrics collection (CPU, RAM, network) |
| `ddos-grafana` | grafana/grafana:latest | 3000 | Real-time monitoring dashboard |
| `ddos-node-exporter` | prom/node-exporter:latest | 9100 (internal) | Host OS metrics exporter |
| `ddos-nginx-exporter` | nginx/nginx-prometheus-exporter | Internal | nginx stub_status → Prometheus |

---

## Repository Structure

```
.
├── README.md
├── .gitignore
├── server/                          # Target web server (ddos-server VM)
│   ├── docker-compose.yml           # Full 8-container stack
│   ├── flask_app/
│   │   ├── Dockerfile               # Python 3.11-slim + Gunicorn
│   │   ├── app.py                   # Flask app with /heavy endpoint
│   │   ├── requirements.txt         # flask==3.0.0, gunicorn==21.2.0
│   │   └── templates/
│   │       ├── index.html           # Westbrook University homepage
│   │       └── pages/
│   │           ├── about.html
│   │           ├── admissions.html
│   │           ├── programs.html
│   │           └── research.html
│   ├── nginx/
│   │   └── nginx.conf               # Rate limiting, proxy, custom error pages
│   ├── prometheus/
│   │   └── prometheus.yml            # Scrape configs for node + nginx exporters
│   ├── promtail/
│   │   └── promtail.yml              # Log pipeline with regex label extraction
│   ├── grafana/
│   │   └── provisioning/
│   │       ├── dashboards/
│   │       │   ├── dashboard.yml     # Auto-provisioning config
│   │       │   └── ddos_monitor.json # Pre-built DDoS monitoring dashboard
│   │       └── datasources/
│   │           └── all.yml           # Loki + Prometheus datasources
│   ├── defense/
│   │   └── cache/
│   │       ├── blocked_ips.conf      # Dynamic nginx IP blocklist
│   │       └── ip_cache.json         # Defense system state
│   ├── website/                      # Static HTML fallback copies
│   │   ├── 503.html
│   │   ├── index.html
│   │   └── pages/
│   └── logs/                         # nginx access/error logs (gitignored)
│       └── .gitkeep
├── botmaster/
│   └── attack.sh                     # Three-phase DDoS attack script
└── legittraffic/
    └── traffic_gen.py                # Realistic student browsing simulator
```

---

## Setup Guide

### 1. Provision GCP VMs

Create 6 VMs in the Google Cloud Console (**Compute Engine → VM instances → Create Instance**) with the specs listed in the [Infrastructure](#infrastructure) table above.

**Server VM (`ddos-server`):**
- **Image:** Ubuntu 22.04 LTS
- **Machine type:** e2-custom (4 vCPU, 8 GB memory)
- **Boot disk:** 50 GB SSD
- **Zone:** us-central1-a
- **Firewall:** Check both ✅ *Allow HTTP traffic* and ✅ *Allow HTTPS traffic*
- **Networking → External IPv4 address:** Select *Reserve a static external IP address* — this gives the server a permanent public IP that persists across reboots

**Botmaster VM (`ddos-botmaster`):**
- **Image:** Ubuntu 22.04 LTS
- **Machine type:** e2-medium (2 vCPU, 4 GB memory)
- **Boot disk:** 10 GB
- **Zone:** us-central1-b

**Bot VMs (`ddos-bot-1`, `ddos-bot-2`, `ddos-bot-3`):**
- **Image:** Ubuntu 22.04 LTS
- **Machine type:** e2-micro (shared-core, 1 GB memory)
- **Boot disk:** 10 GB
- **Zones:** us-central1-a, us-central1-b, northamerica-northeast1-c (distributed across regions to simulate real botnet geography)

**Legitimate Traffic VM (`legittraffic`):**
- **Image:** Ubuntu 22.04 LTS
- **Machine type:** e2-micro (shared-core, 1 GB memory)
- **Boot disk:** 10 GB
- **Zone:** europe-north1-c (Finland — simulates overseas student traffic)

### 2. GCP Firewall Rules

Navigate to **VPC Network → Firewall → Create Firewall Rule** and create the following rules:

**Rule 1 — `allow-internal-ssh`**
```
Direction:        Ingress
Targets:          Specified target tags → ddos-bot
Source filters:   IP ranges → 0.0.0.0/0
Protocols/ports:  tcp:22
Priority:         1000
Logs:             On
```
This allows the botmaster to SSH into all bot VMs over the internal network.

**Rule 2 — `allow-server-ports`**
```
Direction:        Ingress
Targets:          Specified target tags → ddos-server
Source filters:   IP ranges → 0.0.0.0/0
Protocols/ports:  tcp:80, 443, 3000, 3100, 6443, 9080, 9090
Priority:         1000
```
This opens HTTP (80), HTTPS (443), Grafana (3000), Loki (3100), Prometheus (9090), and Promtail (9080) on the server VM.

**Rule 3 — `default-allow-http`**
```
Direction:        Ingress
Targets:          Specified target tags → http-server
Source filters:   IP ranges → 0.0.0.0/0
Protocols/ports:  tcp:80
Priority:         1000
```
Standard GCP rule for public HTTP access.

### 3. Server VM Setup

SSH into `ddos-server` and run the following commands:

```bash
# ── Update system packages ──
sudo apt update && sudo apt upgrade -y

# ── Install Docker Engine ──
sudo apt install -y ca-certificates curl gnupg lsb-release

# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker apt repository
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker CE + Compose plugin
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

# Add your user to the docker group (avoids needing sudo for every docker command)
sudo usermod -aG docker $USER

# ── Install utility tools ──
sudo apt install -y \
  htop          \
  net-tools     \
  curl          \
  jq            \
  tree          \
  git

# ── Verify installations ──
docker --version
docker compose version
```

> **Important:** Log out and SSH back in after `usermod -aG docker` for the group change to take effect.

Now clone the repo and start the Docker stack:

```bash
git clone <repo-url>
cd ddos-lab/server

# Build and start all 8 containers
docker compose up -d --build

# Verify everything is running
docker ps
```

You should see 8 containers: `ddos-flask`, `ddos-nginx`, `ddos-loki`, `ddos-promtail`, `ddos-prometheus`, `ddos-grafana`, `ddos-node-exporter`, `ddos-nginx-exporter`.

### 4. Botmaster VM Setup

SSH into `ddos-botmaster` and run:

```bash
# ── Update system packages ──
sudo apt update && sudo apt upgrade -y

# ── Install required tools ──
sudo apt install -y \
  openssh-client   \
  apache2-utils    \
  htop             \
  net-tools        \
  curl             \
  git

# ── Generate Ed25519 SSH key pair ──
ssh-keygen -t ed25519 -f ~/.ssh/botkey -N "" -C "ddos-botmaster"

# View the public key (you'll need this in the next step)
cat ~/.ssh/botkey.pub
```

Copy the entire output of `cat ~/.ssh/botkey.pub` — you will paste this into each bot VM's `authorized_keys` file in the next step.

### 5. Bot VM Setup

SSH into **each** bot VM (`ddos-bot-1`, `ddos-bot-2`, `ddos-bot-3`) and run the following:

```bash
# ── Update system packages ──
sudo apt update && sudo apt upgrade -y

# ── Install Apache Benchmark (the HTTP flood tool) ──
sudo apt install -y apache2-utils curl
```

Then authorize the botmaster's SSH key on each bot:

```bash
# Create the .ssh directory if it doesn't exist
mkdir -p ~/.ssh
chmod 700 ~/.ssh

# Open authorized_keys and paste the botmaster's public key
nano ~/.ssh/authorized_keys
```

Paste the entire public key string from the botmaster's `~/.ssh/botkey.pub` (starts with `ssh-ed25519 AAAA...`) into the file, save, and exit. Then set the correct permissions:

```bash
chmod 600 ~/.ssh/authorized_keys
```

Repeat this on all three bot VMs (`ddos-bot-1`, `ddos-bot-2`, `ddos-bot-3`).

**How it works:** The botmaster holds the private key (`~/.ssh/botkey`) and each bot has the matching public key in its `authorized_keys`. This creates a passwordless SSH trust relationship — the botmaster can execute commands on all three bots simultaneously without prompts, which is critical for coordinated attack execution.

```
                    ┌──────────────────┐
                    │    Botmaster     │
                    │  ~/.ssh/botkey   │ (private key)
                    │  ~/.ssh/botkey.pub│ (public key)
                    └────────┬─────────┘
                             │ SSH (passwordless)
                ┌────────────┼────────────┐
                ▼            ▼            ▼
          ┌──────────┐ ┌──────────┐ ┌──────────┐
          │  Bot-1   │ │  Bot-2   │ │  Bot-3   │
          │ 10.128.0.4│ │ 10.128.0.5│ │ 10.162.0.2│
          └──────────┘ └──────────┘ └──────────┘
               │            │            │
          ~/.ssh/       ~/.ssh/       ~/.ssh/
          authorized_   authorized_   authorized_
          keys          keys          keys
          (botmaster    (botmaster    (botmaster
           pub key)      pub key)      pub key)
```

Verify connectivity from the botmaster:

```bash
ssh -i ~/.ssh/botkey -o StrictHostKeyChecking=no 10.128.0.4 'hostname'  # Bot-1
ssh -i ~/.ssh/botkey -o StrictHostKeyChecking=no 10.128.0.5 'hostname'  # Bot-2
ssh -i ~/.ssh/botkey -o StrictHostKeyChecking=no 10.162.0.2 'hostname'  # Bot-3
```

All three should return their hostname without asking for a password.

### 6. Legitimate Traffic VM Setup

SSH into `legittraffic` and run:

```bash
# ── Update system packages ──
sudo apt update && sudo apt upgrade -y

# ── Install Python 3 and the requests library ──
sudo apt install -y python3 python3-pip curl
pip3 install requests --break-system-packages

# ── Verify Python installation ──
python3 --version

# ── Test connectivity to the target server ──
curl -s http://<server-external-ip>/ping
```

You should get `{"status":"ok"}` confirming the server is reachable from Finland.

---

## Running the Lab

### Start the Server

On `ddos-server`:

```bash
cd ddos-lab/server
docker compose up -d --build

# Verify all containers are healthy
docker ps

# Test the website
curl http://localhost/
curl http://localhost/heavy
curl http://localhost/status
```

Access the web interface at `http://<server-external-ip>/`

### Start Legitimate Traffic

On `legittraffic` (europe-north1-c):

```bash
python3 legittraffic/traffic_gen.py
```

This simulates realistic student browsing with randomized user agents, browsing journeys, referrers, and reading delays. Output shows success/failure per request with running statistics.

Optional arguments: `python3 traffic_gen.py [students_per_wave] [wave_interval_sec]`

### Launch the Attack

On `ddos-botmaster`:

```bash
chmod +x botmaster/attack.sh
./botmaster/attack.sh
```

The attack executes in three escalating phases automatically.

### Stop the Attack

Press `Ctrl+C` at any time. The SIGINT trap immediately kills all `ab` processes on all three bot VMs. The server recovers within ~10 seconds.

---

## Attack Phases

| Phase | Duration | Concurrent Requests | Server Behavior | User Experience |
|-------|----------|-------------------|-----------------|-----------------|
| **Phase 1** | 0–30s | 9 (3 per bot) | Workers available; normal responses | Fully accessible; <100ms |
| **Phase 2** | 30–60s | 30 (10 per bot) | Worker queue filling; latency rising | Slow (500ms–2s); occasional timeouts |
| **Phase 3** | 60s+ | 300 (100 per bot) | All 3 workers saturated; 503 for all | Completely inaccessible |
| **Recovery** | After Ctrl+C | 0 | Workers clear in <10s | Fully accessible |

**Why it works:** Flask/Gunicorn with synchronous workers blocks one worker per in-flight request. The `/heavy` endpoint holds each worker for ~0.5 seconds. With only 3 workers, 3 persistent connections permanently deny service. 300 concurrent connections guarantee total saturation.

---

## Monitoring Stack

Access the **Grafana dashboard** at `http://<server-ip>:3000`

- **Username:** `admin`
- **Password:** `ddoslab123`

The pre-provisioned dashboard (`ddos_monitor.json`) displays:

- **Requests per second** — real-time request rate from nginx
- **HTTP status code distribution** — 200 vs 503 ratio during attack
- **CPU and memory utilization** — system resource consumption via node-exporter
- **Per-IP request rates** — identify attacking IPs in Loki logs
- **Response time distribution** — latency degradation during each phase

**Data flow:**

```
nginx access.log → Promtail → Loki → Grafana (LogQL queries)
node-exporter → Prometheus → Grafana (PromQL queries)
nginx-exporter → Prometheus → Grafana (connection metrics)
```

---

## How It Works

### The Vulnerability

The attack exploits **application-layer resource exhaustion** in a synchronous web framework:

| Server Type | Architecture | Max Concurrent | DDoS Vulnerability |
|------------|-------------|----------------|---------------------|
| Static nginx | Event-driven, non-blocking | 10,000+ | Very low |
| Flask/Gunicorn (sync) | 1 worker = 1 blocked request | 3 workers | **High** — 3 connections saturate everything |

### Attack Vector

- **Tool:** Apache Benchmark (`ab`)
- **Target:** `http://<server-ip>/heavy` (CPU-intensive endpoint)
- **Method:** HTTP/1.0 GET flood from 3 geographically distributed VMs
- **Concurrency:** Up to 100 per bot (300 total)
- **Bypass:** GCP Cloud Armor only protects Layer 3/4 — valid HTTP requests pass through

### Attack Surface

1. **`/heavy` endpoint** — Unauthenticated, CPU-intensive, no rate limiting
2. **3-worker Gunicorn pool** — Trivially low denial-of-service threshold
3. **Public static IP** — Accessible from any machine on the internet
4. **No application-layer WAF** — No per-IP throttling at the app level

---

## Phase 2 — ML-Based Detection (Upcoming)

Phase 2 will implement an ML-based detection system that automatically identifies and blocks DDoS traffic in real time, replacing threshold-based defenses.

**Planned approach:**
- Train classification models (SVM, Random Forest, Gradient Boosting) on labelled traffic from Phase 1 logs combined with the CIC-DDoS2019 dataset
- Feature extraction: request rate, inter-arrival time, URL entropy, user-agent diversity, status code ratios, response time distributions
- Integration with the existing nginx `blocked_ips.conf` pipeline for automated IP blocking
- Real-time inference loop querying Loki for traffic features

---

## License

This project was developed for **CS559 — Network Security** at Binghamton University, Watson School of Engineering. It is intended for **educational and research purposes only**.

> **Disclaimer:** This lab is designed for controlled educational environments. Running DDoS attacks against systems you do not own or have explicit permission to test is illegal. All attacks in this project target infrastructure provisioned and controlled by the project author on GCP.
