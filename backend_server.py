import os
import asyncio
import itertools
from aiohttp import web

CONFIG_KEY = 'server_config'

LATENCY_CONFIG = {
    'A': [
        10, 15, 20,
        400, 400, 400,
        10, 15, 20,
    ] * 5,
    'B': [
        200, 200, 200,
        200, 200, 200,
        200, 200, 200,
    ] * 5,
    'C': [
        250, 250, 250,
        250, 250, 250,
        250, 250, 250,
    ] * 5,
}

async def handle_request(request):
    config = request.app[CONFIG_KEY]
    server_id = config['server_id']
    latency_ms = next(config['latency_cycle'])
    await asyncio.sleep(latency_ms / 1000.0)
    return web.Response(text=f"Hello from {server_id} – simulated {latency_ms}ms\n")

async def initialize_server_config(app):
    server_id = os.environ.get('SERVER_ID', 'A')
    port = int(os.environ.get('PORT', 8080))
    latencies = LATENCY_CONFIG.get(server_id, LATENCY_CONFIG['A'])
    app[CONFIG_KEY] = {
        'server_id': server_id,
        'port': port,
        'latency_cycle': itertools.cycle(latencies)
    }
    print(f"● Server {server_id} starting on port {port}")

def setup_app_routes():
    app = web.Application()
    app.on_startup.append(initialize_server_config)
    app.router.add_get('/', handle_request)
    return app

if __name__ == '__main__':
    app_port = int(os.environ.get('PORT', 8080))
    application = setup_app_routes()
    web.run_app(application, host='0.0.0.0', port=app_port)
