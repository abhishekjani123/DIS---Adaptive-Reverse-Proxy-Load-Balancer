import asyncio
import itertools
import time
import csv
import datetime
import os
import collections
import statistics
import sys
import math
from aiohttp import web, ClientSession, TCPConnector

BACKEND_SERVERS = [
    "http://localhost:8081",
    "http://localhost:8082",
    "http://localhost:8083"
]
LATENCY_WINDOW_SIZE = 3
EWMA_ALPHA = 0.2

backend_server_cycler = itertools.cycle(BACKEND_SERVERS)
backend_performance_metrics = {
    url: {'ewma': None, 'raw_latencies': collections.deque(maxlen=LATENCY_WINDOW_SIZE)}
    for url in BACKEND_SERVERS
}
current_routing_mode = "round-robin"

LOG_FILE_PATH = 'proxy_log.csv'
LOG_HEADERS = ['timestamp', 'backend_url', 'latency_ms', 'status_code', 'routing_mode']

def initialize_log_file():
    if not os.path.exists(LOG_FILE_PATH) or os.path.getsize(LOG_FILE_PATH) == 0:
        with open(LOG_FILE_PATH, 'w', newline='') as f:
            csv.DictWriter(f, fieldnames=LOG_HEADERS).writeheader()

initialize_log_file()

def calculate_sma_latency(url):
    metrics = backend_performance_metrics[url]
    if not metrics['raw_latencies']:
        return float('inf')
    valid_latencies = [x for x in metrics['raw_latencies'] if x > 0]
    return statistics.mean(valid_latencies) if valid_latencies else float('inf')

def retrieve_ewma_latency(url):
    metrics = backend_performance_metrics[url]
    return metrics['ewma'] if metrics['ewma'] is not None else float('inf')

def record_backend_performance(url, latency_ms):
    data = backend_performance_metrics[url]
    if latency_ms > 0:
        data['raw_latencies'].append(latency_ms)
        previous_ewma = data['ewma']
        data['ewma'] = float(latency_ms) if previous_ewma is None \
            else (EWMA_ALPHA * latency_ms + (1 - EWMA_ALPHA) * previous_ewma)
        print(f"[Perf Update] {url} → {latency_ms}ms | EWMA={data['ewma']:.1f}ms", flush=True)
    else:
        print(f"[Perf Update] {url} → invalid latency {latency_ms}ms (skipped)", flush=True)

def select_backend_round_robin():
    return next(backend_server_cycler)

def select_backend_adaptive_sma():
    for url, metrics in backend_performance_metrics.items():
        if not metrics['raw_latencies']:
            print(f"[SMA] Probing unmeasured: {url}", flush=True)
            return url
    sma_values = {u: calculate_sma_latency(u) for u in BACKEND_SERVERS}
    chosen_backend = min(sma_values, key=sma_values.get)
    print("[SMA] SMAs: " + ", ".join(f"{u.split(':')[-1]}={sma_values[u]:.1f}ms" for u in sma_values), flush=True)
    print(f"[SMA] Chosen: {chosen_backend}", flush=True)
    return chosen_backend

def select_backend_adaptive_ewma():
    ewma_values = {u: retrieve_ewma_latency(u) for u in BACKEND_SERVERS}
    unmeasured_servers = [u for u, v in ewma_values.items() if math.isinf(v)]

    if unmeasured_servers:
        for server_url in BACKEND_SERVERS: # Iterate in a fixed order for deterministic probing
            if server_url in unmeasured_servers:
                print(f"[EWMA] Probing unmeasured: {server_url}", flush=True)
                return server_url
        return next(backend_server_cycler) # Fallback, though should be caught by unmeasured_servers check

    print("[EWMA] EWMAs: " + ", ".join(f"{u.split(':')[-1]}={ewma_values[u]:.1f}ms" for u in ewma_values), flush=True)
    chosen_backend = min(ewma_values, key=ewma_values.get)
    print(f"[EWMA] Chosen: {chosen_backend}", flush=True)
    return chosen_backend

def select_next_backend():
    if current_routing_mode == "round-robin":
        return select_backend_round_robin()
    if current_routing_mode == "adaptive_sma":
        return select_backend_adaptive_sma()
    if current_routing_mode == "adaptive_ewma":
        return select_backend_adaptive_ewma()
    return select_backend_round_robin()

def log_request_details(backend_url, latency_ms, status_code):
    log_entry = {
        'timestamp': datetime.datetime.now().isoformat(),
        'backend_url': backend_url,
        'latency_ms': latency_ms,
        'status_code': status_code,
        'routing_mode': current_routing_mode
    }
    try:
        with open(LOG_FILE_PATH, 'a', newline='') as f:
            csv.DictWriter(f, fieldnames=LOG_HEADERS).writerow(log_entry)
    except Exception as e:
        print(f"Log write failed: {e}", flush=True)

async def process_proxy_request(request):
    request_time = datetime.datetime.now().isoformat(timespec='milliseconds')
    peer_address = request.transport.get_extra_info('peername') if request.transport else None
    print(f"\n[{request_time}] {peer_address} → {request.method} {request.path_qs}", flush=True)

    chosen_backend_url = select_next_backend()
    target_url_path = f"{chosen_backend_url}{request.path_qs}"
    request_body = await request.read()

    outgoing_headers = dict(request.headers)
    outgoing_headers['Connection'] = 'close' # Ensure backend connection is not kept alive

    measured_latency_ms = -1
    response_status_code = None
    proxy_response = None

    # Create a new session for each request, ensuring it's closed
    async with ClientSession(connector=TCPConnector(force_close=True)) as client_session:
        request_start_time = time.monotonic()
        try:
            async with client_session.request(
                request.method,
                target_url_path,
                headers=outgoing_headers,
                data=request_body if request_body else None,
                allow_redirects=False,
                timeout=10
            ) as backend_response:
                response_content = await backend_response.read()
                measured_latency_ms = round((time.monotonic() - request_start_time) * 1000)
                response_status_code = backend_response.status
                
                proxy_response = web.Response(
                    status=backend_response.status,
                    reason=backend_response.reason,
                    headers=backend_response.headers, # Pass through backend headers
                    body=response_content
                )
        except asyncio.TimeoutError:
            measured_latency_ms = round((time.monotonic() - request_start_time) * 1000)
            response_status_code = 504
            proxy_response = web.HTTPGatewayTimeout(text="Backend timeout")
        except Exception as e: # Catch broader exceptions for robustness
            measured_latency_ms = round((time.monotonic() - request_start_time) * 1000)
            response_status_code = 502
            proxy_response = web.HTTPBadGateway(text=f"Backend error: {e}")
    
    # Ensure client connection is also closed after this response
    if proxy_response:
        proxy_response.force_close = True
        proxy_response.headers['Connection'] = 'close'

    record_backend_performance(chosen_backend_url, measured_latency_ms)
    log_request_details(chosen_backend_url, measured_latency_ms, response_status_code)
    
    return proxy_response

async def launch_proxy_server(host_address, server_port, mode_of_operation):
    global current_routing_mode
    current_routing_mode = mode_of_operation

    # keepalive_timeout=0 helps ensure connections are not held open by the server
    app_runner = web.AppRunner(web.Application(), keepalive_timeout=0)
    application = app_runner.app
    application.router.add_route('*', '/{path:.*}', process_proxy_request)

    await app_runner.setup()
    site_runner = web.TCPSite(app_runner, host=host_address, port=server_port, backlog=1000)
    await site_runner.start()
    print(f"Non-persistent proxy listening on http://{host_address}:{server_port} (mode={current_routing_mode})", flush=True)

    await asyncio.Event().wait()

if __name__ == '__main__':
    selected_mode = sys.argv[1] if len(sys.argv) > 1 else "round-robin"
    asyncio.run(launch_proxy_server('0.0.0.0', 9090, selected_mode))
