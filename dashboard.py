import pandas as pd
import json
from flask import Flask, render_template, jsonify, request
import os
import datetime
import logging

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

LOG_FILE = 'proxy_log.csv'
RECENT_ENTRIES_STATS_WINDOW = 200

def read_and_validate_log_df():
    if not os.path.exists(LOG_FILE):
        logging.warning(f"Log file not found: {LOG_FILE}")
        return None, f"Log file not found: {LOG_FILE}"

    try:
        with open(LOG_FILE, 'r') as f:
            first_line = f.readline()
        has_header = 'timestamp' in first_line.lower()

        if os.path.getsize(LOG_FILE) == 0 or \
           (has_header and len(pd.read_csv(LOG_FILE, nrows=0).columns) == 0):
            logging.info("Log file is empty.")
            return None, "Log file is empty."

        df = pd.read_csv(LOG_FILE, header=0 if has_header else None)
        if not has_header:
            expected_cols = ['timestamp', 'backend_url', 'latency_ms', 'status_code', 'routing_mode']
            df.columns = expected_cols + [f'extra_{i}' for i in range(len(df.columns) - len(expected_cols))]

        required_cols = ['timestamp', 'backend_url', 'latency_ms', 'status_code', 'routing_mode']
        if not all(col in df.columns for col in required_cols):
            logging.error(f"Log file missing required columns. Found: {list(df.columns)}")
            return None, "Log file format unexpected (missing columns)."

        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        df.dropna(subset=['timestamp'], inplace=True)
        df['latency_ms'] = pd.to_numeric(df['latency_ms'], errors='coerce')

        if df.empty:
            logging.info("Log file contains no valid timestamped entries.")
            return None, "No valid data in log file."
        
        df['backend_port'] = df['backend_url'].str.extract(r':(\d+)$').fillna('Unknown')
        return df, None

    except pd.errors.EmptyDataError:
        logging.warning(f"Attempted to read empty log file: {LOG_FILE}")
        return None, "Log file is currently empty."
    except Exception as e:
        logging.error(f"Error reading or initially processing log file: {e}", exc_info=True)
        return None, f"Error reading log file: {e}"

def prepare_plotly_latency_traces(df_valid_latency):
    plotly_traces = []
    if not df_valid_latency.empty:
        for port in sorted(df_valid_latency['backend_port'].unique()):
            port_data = df_valid_latency[df_valid_latency['backend_port'] == port]
            plotly_traces.append({
                'x': port_data['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S.%f').tolist(),
                'y': port_data['latency_ms'].tolist(),
                'mode': 'lines+markers',
                'type': 'scatter',
                'name': f'Backend {port} (ms)',
                'marker': {'size': 4}
            })
        logging.info(f"Prepared Plotly latency data with {len(plotly_traces)} traces.")
    else:
        logging.info("No valid positive latency data for Plotly chart.")
    return plotly_traces

def prepare_request_distribution_data(df_all_entries):
    distribution = {"labels": [], "data": []}
    if not df_all_entries.empty:
        dist_counts = df_all_entries['backend_port'].value_counts().sort_index()
        distribution['labels'] = dist_counts.index.tolist()
        distribution['data'] = dist_counts.values.tolist()
        logging.info(f"Prepared request distribution for ports: {distribution['labels']}")
    else:
        logging.info("No recent entries for distribution chart.")
    return distribution

def prepare_sma_table_entries(df_all_entries, df_valid_latency):
    table_entries = []
    latest_smas = {}
    if not df_valid_latency.empty:
        grouped_by_port = df_valid_latency.groupby('backend_port')['latency_ms']
        for port, group_data in grouped_by_port:
            rolling_sma = group_data.rolling(3, min_periods=1).mean()
            if not rolling_sma.empty:
                latest_smas[port] = rolling_sma.iloc[-1]

    for _, row in df_all_entries.iterrows():
        table_entries.append({
            'timestamp': row['timestamp'].strftime('%H:%M:%S.%f')[:-3],
            'chosen': row['backend_port'],
            'latency_ms': int(row['latency_ms']) if pd.notna(row['latency_ms']) else 'ERR',
            'smaA': round(latest_smas.get('8081', float('nan')), 1) if pd.notna(latest_smas.get('8081')) else 'N/A',
            'smaB': round(latest_smas.get('8082', float('nan')), 1) if pd.notna(latest_smas.get('8082')) else 'N/A',
            'smaC': round(latest_smas.get('8083', float('nan')), 1) if pd.notna(latest_smas.get('8083')) else 'N/A',
        })
    logging.info(f"Prepared SMA table with {len(table_entries)} rows.")
    return table_entries

def generate_explanation_text(df_all_entries):
    if not df_all_entries.empty:
        last_row = df_all_entries.iloc[-1]
        last_latency = last_row['latency_ms'] if pd.notna(last_row['latency_ms']) else 'ERR'
        last_chosen_port = last_row['backend_port']
        last_routing_mode = last_row['routing_mode']
        return f"Last: Mode '{last_routing_mode}' chose {last_chosen_port}, Latency: {last_latency}ms."
    return "No requests processed yet."

def calculate_overall_stats(df_all_entries):
    stats = {"current_mode": "Unknown", "avg_recent_latency": "N/A"}
    df_stats_window = df_all_entries.tail(RECENT_ENTRIES_STATS_WINDOW).copy()
    
    if not df_stats_window.empty:
        stats["current_mode"] = df_stats_window['routing_mode'].iloc[-1]
        df_valid_latency_in_window = df_stats_window[pd.to_numeric(df_stats_window['latency_ms'], errors='coerce') > 0]
        avg_latency = df_valid_latency_in_window['latency_ms'].mean()
        stats["avg_recent_latency"] = round(avg_latency, 1) if pd.notna(avg_latency) else 'N/A'
    return stats

@app.route('/')
def serve_dashboard_page():
    template_path = os.path.join(app.template_folder, 'dashboard.html')
    if not os.path.exists(template_path):
        logging.error(f"Template file not found at {template_path}")
        return "Error: Dashboard template not found.", 500
    return render_template('dashboard.html')

@app.route('/data')
def provide_dashboard_data():
    logging.info("Received request for /data")
    
    output_payload = {
        "plotly_latency_data": [],
        "request_distribution": {"labels": [], "data": []},
        "sma_table": [],
        "explanation": "Waiting for data...",
        "current_mode": "Unknown",
        "avg_recent_latency": "N/A"
    }

    df_all_logs, error_message = read_and_validate_log_df()

    if error_message and not df_all_logs: # Covers file not found, empty, format error before df creation
        if "Log file not found" in error_message:
             output_payload["error"] = error_message
             return jsonify(output_payload), 404
        output_payload["message"] = error_message # For empty or no valid data
        return jsonify(output_payload)
    
    if df_all_logs is None : # Should be caught by above, but as a safeguard
        output_payload["error"] = "Failed to process log data due to an unexpected issue."
        return jsonify(output_payload), 500

    df_valid_latency_logs = df_all_logs[df_all_logs['latency_ms'] > 0].copy()

    output_payload["plotly_latency_data"] = prepare_plotly_latency_traces(df_valid_latency_logs)
    output_payload["request_distribution"] = prepare_request_distribution_data(df_all_logs)
    output_payload["sma_table"] = prepare_sma_table_entries(df_all_logs, df_valid_latency_logs)
    output_payload["explanation"] = generate_explanation_text(df_all_logs)
    
    overall_stats = calculate_overall_stats(df_all_logs)
    output_payload["current_mode"] = overall_stats["current_mode"]
    output_payload["avg_recent_latency"] = overall_stats["avg_recent_latency"]

    logging.info(f"Sending data: Mode={output_payload['current_mode']}, AvgLat={output_payload['avg_recent_latency']}")
    return jsonify(output_payload)

if __name__ == '__main__':
    dashboard_port = int(os.environ.get('DASHBOARD_PORT', 5002))
    print(f"Starting Flask dashboard server on http://0.0.0.0:{dashboard_port}")
    print(f"Reading live data from: {os.path.abspath(LOG_FILE)}")
    print("Ensure the proxy server is running and generating logs.")
    app.run(debug=True, host='0.0.0.0', port=dashboard_port)
