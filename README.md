# CS 553: Adaptive Reverse Proxy Load Balancer

--------------------
## 1. Project Overview
--------------------
This project implements and analyzes an HTTP reverse proxy load balancer written in Python. It is designed to distribute incoming client traffic among several backend servers. The load balancer supports two primary connection models for interacting with backend servers: persistent (reusing connections) and non-persistent (new connection per request). It also features three distinct routing algorithms:
* Round-Robin (RR): Distributes requests sequentially among servers.
* Adaptive Simple Moving Average (SMA): Selects servers based on the simple moving average of their recent response times.
* Adaptive Exponential Weighted Moving Average (EWMA): Selects servers based on an exponentially weighted moving average of their recent response times, giving more weight to recent data.

The system includes backend servers that emulate heterogeneous latency profiles. The primary tool for benchmarking and load generation is `wrk`. The project aims to compare the performance (throughput, mean latency, tail latency) of these different configurations. A real-time dashboard using Flask and JavaScript provides live monitoring capabilities.

![image](https://github.com/user-attachments/assets/813dc952-4fdf-47c5-953c-09f8c2234a91)

--------------------
## 2. Table of Contents
--------------------
1. Project Overview
2. Table of Contents
3. Project Structure
4. Prerequisites
5. Initial Setup (Virtual Environment & Dependencies)
6. Running Backend Servers (Using Docker)
7. Running the Proxy Server
8. Running the Dashboard Server (for Live Monitoring)
9. Running Test Scenarios (Load Generation with `wrk`)
    9.1. Persistent Proxy - Round Robin Mode
    9.2. Persistent Proxy - Adaptive SMA Mode
    9.3. Persistent Proxy - Adaptive EWMA Mode
    9.4. Non-Persistent Proxy - Round Robin Mode
    9.5. Non-Persistent Proxy - Adaptive SMA Mode
    9.6. Non-Persistent Proxy - Adaptive EWMA Mode
10. Stopping the Application
11. Analyzing Results
12. Authors
13. License

--------------------
## 3. Project Structure
--------------------
```
project_root/
|
|-- backend_server.py              # Python script for the backend servers (used by Docker)
|-- proxy_server_non_persistent.py # Python script for the proxy with non-persistent connections
|-- persistent_proxy_server.py     # Python script for the proxy with persistent connections
|-- dashboard.py                   # Python Flask script for the live dashboard
|-- dashboard.html                 # HTML template for the live dashboard
|-- Dockerfile                     # Dockerfile to containerize the backend server
|
|-- logs/                          # Directory for storing CSV logs and wrk output files
|   |-- *.csv                      # Per-request logs from the proxy
|   |-- *.txt                      # Console captures from servers, wrk outputs
|
|-- README.md                      # This file (changed from README.txt)
```

--------------------
## 4. Prerequisites
--------------------
Before you begin, ensure you have the following installed on your system:

* **Python:** Version 3.9 or higher (for proxy, dashboard, and if building Docker image locally).
* **pip:** Python package installer.
* **`wrk` HTTP Benchmarking Tool:** Version 4.1 or higher.
* **Docker:** Required for running backend servers.

----------------------------------------------------
## 5. Initial Setup (Virtual Environment & Dependencies)
----------------------------------------------------
It is highly recommended to use a Python virtual environment for the proxy and dashboard scripts.

1.  **Obtain Project Files:**
    Clone the repository or download and extract the project files to a local directory. Navigate to the project's root directory in your terminal.

2.  **Create `logs` Directory:**
    This directory will store output files.
    ```bash
    mkdir -p logs
    ```

3.  **Create and Activate a Virtual Environment (for proxy/dashboard):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
    *(On Windows, the activation command is `.\venv\Scripts\activate`)*

4.  **Install Python Dependencies (for proxy/dashboard):**
    With the virtual environment activated, install the required libraries:
    ```bash
    pip3 install aiohttp flask pandas
    ```

5.  **Verify `wrk` Installation:**
    ```bash
    wrk -v
    ```

6.  **Check for Port Conflicts:**
    Ensure these ports are free on your host machine:
    * Backend Servers (Host Ports mapped to Docker): `8081`, `8082`, `8083`
    * Proxy Server: `9090`
    * Dashboard Server: `5002`

---------------------------------------
## 6. Running Backend Servers (Using Docker)
---------------------------------------
You need three backend server instances running, each hosted in a Docker container.
**Each Docker `run` command should be executed in a separate terminal window/tab if you want to see their logs directly, or run them in detached mode (`-d`) and use `docker logs`.**

1.  **Build Docker Image (once per project update):**
    From the project root directory (where the `Dockerfile` is located):
    ```bash
    docker build -t backend-server:latest .
    ```
2.  **Run Containers:**
    * **Terminal 1 (Docker Backend A - Host Port 8081):**
        ```bash
        docker run --rm -p 8081:8080 -e PORT=8080 -e SERVER_ID=A backend-server:latest
        ```
    * **Terminal 2 (Docker Backend B - Host Port 8082):**
        ```bash
        docker run --rm -p 8082:8080 -e PORT=8080 -e SERVER_ID=B backend-server:latest
        ```
    * **Terminal 3 (Docker Backend C - Host Port 8083):**
        ```bash
        docker run --rm -p 8083:8080 -e PORT=8080 -e SERVER_ID=C backend-server:latest
        ```
    *Note: The container internally runs on port 8080 (as defined by `ENV PORT=8080` in Dockerfile and `-e PORT=8080` override). We map different host ports (8081, 8082, 8083) to the container's port 8080 for each instance. The `--rm` flag ensures containers are removed when stopped.*

---------------------------
## 7. Running the Proxy Server
---------------------------
With the backend servers running, start the proxy server. This runs on your host machine, typically within the activated virtual environment. **The proxy server needs its own terminal.**

* **Choose Proxy Variant and Routing Mode:**
    * **Persistent Proxy Example (EWMA):**
        ```bash
        python3 persistent_proxy_server.py adaptive_ewma
        ```
    * **Non-Persistent Proxy Example (Round Robin):**
        ```bash
        python3 proxy_server_non_persistent.py round-robin
        ```
* **Available Routing Modes:** `round-robin`, `adaptive_sma`, `adaptive_ewma`.
* The proxy will start generating a CSV log file (e.g., `adaptive_ewma_persistent.csv`).
* To save console output: `python3 persistent_proxy_server.py adaptive_ewma > logs/proxy_console.txt`

-------------------------------------------------
## 8. Running the Dashboard Server (for Live Monitoring)
-------------------------------------------------
Once the backend servers and the proxy server are running (and the proxy is generating logs), you can start the dashboard. This also runs on your host, typically in the virtual environment, and **needs its own terminal.**

* **Terminal (Dashboard Server):**
    ```bash
    python3 dashboard.py
    ```
    Open a web browser and navigate to `http://localhost:5002`. The dashboard reads from `proxy_log.csv` by default (ensure your proxy script generates this filename or adjust the dashboard script).

-------------------------------------------------------
## 9. Running Test Scenarios (Load Generation with `wrk`)
-------------------------------------------------------
With the Backend Servers, Proxy Server, and (optionally) Dashboard Server running, use `wrk` to generate load. This **needs its own terminal.**

**Important:**
* Each scenario below assumes you have already started the appropriate Proxy Server (from Section 7). If you change the proxy configuration (e.g., from persistent to non-persistent, or change routing mode), you must stop the current proxy and start the new one.
* It's recommended to redirect `wrk` output to a file in the `logs/` directory for analysis (e.g., `> logs/scenario_1_1_wrk.txt`).

### 9.1. Scenario 1.1: Persistent Proxy - Round Robin Mode
*(Ensure `python3 persistent_proxy_server.py round-robin` is running)*
* **Terminal (Load Generation):**
    ```bash
    wrk -t4 -c100 -d120s http://localhost:9090
    ```

### 9.2. Scenario 1.2: Persistent Proxy - Adaptive SMA Mode
*(Ensure `python3 persistent_proxy_server.py adaptive_sma` is running)*
* **Terminal (Load Generation):**
    ```bash
    wrk -t4 -c100 -d120s http://localhost:9090
    ```

### 9.3. Scenario 1.3: Persistent Proxy - Adaptive EWMA Mode
*(Ensure `python3 persistent_proxy_server.py adaptive_ewma` is running)*
* **Terminal (Load Generation):**
    ```bash
    wrk -t4 -c100 -d120s http://localhost:9090
    ```

### 9.4. Scenario 2.1: Non-Persistent Proxy - Round Robin Mode
*(Ensure `python3 proxy_server_non_persistent.py round-robin` is running)*
* **Terminal (Load Generation):**
    ```bash
    wrk -t4 -c100 -d120s http://localhost:9090
    ```

### 9.5. Scenario 2.2: Non-Persistent Proxy - Adaptive SMA Mode
*(Ensure `python3 proxy_server_non_persistent.py adaptive_sma` is running)*
* **Terminal (Load Generation):**
    ```bash
    wrk -t4 -c100 -d120s http://localhost:9090
    ```

### 9.6. Scenario 2.3: Non-Persistent Proxy - Adaptive EWMA Mode
*(Ensure `python3 proxy_server_non_persistent.py adaptive_ewma` is running)*
* **Terminal (Load Generation):**
    ```bash
    wrk -t4 -c100 -d120s http://localhost:9090
    ```

-----------------------------
## 10. Stopping the Application
-----------------------------
* **Proxy Server & Dashboard Server (Python):** Go to their respective terminal windows and press `Ctrl+C`.
* **`wrk` Benchmark:** Terminates automatically after the specified duration.
* **Docker Containers:** If run in the foreground (without `-d`, like in the examples), press `Ctrl+C` in their terminals. If run with `-d` (detached), use `docker stop <container_id_or_name>`. The `--rm` flag used in the examples will automatically remove the container once it is stopped.
* **Virtual Environment:** To deactivate, type `deactivate` in the terminal where it's active.

-------------------------
## 11. Analyzing Results
-------------------------
* **CSV Logs:** Detailed per-request logs are saved by the proxy server (e.g., in the `logs/` directory or project root).
* **`wrk` Output Files:** `wrk` output summaries are saved in `.txt` files in the `logs/` directory if redirected.
* These data files are the primary source for performance analysis.

-------------
## 12. Authors
-------------
* Shrey Patel (sp2675)
* Abhishek Jani (aj1121)
* Mustafa Adil (ma2398)
