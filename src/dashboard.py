import time
import json
import asyncio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
import pynvml

app = FastAPI(title="AI Video VPS Control Plane")

PIPELINE_STATE = {
    "status": "Idle",
    "current_step": "None",
    "last_error": None,
    "model_load_latency": 0.0,
    "processed_scenes": 0,
    "total_scenes": 0
}

try:
    pynvml.nvmlInit()
    GPU_AVAILABLE = True
except Exception:
    GPU_AVAILABLE = False

def get_gpu_metrics():
    if not GPU_AVAILABLE:
        return {"used_mb": 0, "total_mb": 0, "utilization": 0}
    handle = pynvml.nvmlDeviceGetHandleByIndex(0)
    info = pynvml.nvmlDeviceGetMemoryInfo(handle)
    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
    return {
        "used_mb": round(info.used / (1024 ** 2), 2),
        "total_mb": round(info.total / (1024 ** 2), 2),
        "utilization": util.gpu
    }

@app.get("/metrics/stream")
async def sse_metrics():
    async def event_generator():
        while True:
            payload = {
                "gpu": get_gpu_metrics(),
                "state": PIPELINE_STATE,
                "timestamp": time.time()
            }
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(1.0)
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>VPS AI Video Control Plane</title>
        <style>
            body { font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; padding: 2rem; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.5rem; margin-top: 1.5rem; }
            .card { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 1.5rem; }
            .metric { font-size: 2rem; font-weight: bold; color: #38bdf8; margin: 0.5rem 0; }
            .progress-bar { background: #334155; border-radius: 4px; height: 12px; overflow: hidden; }
            .progress-fill { background: #38bdf8; height: 100%; width: 0%; transition: width 0.3s; }
            .badge { display: inline-block; padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.875rem; background: #0284c7; }
        </style>
    </head>
    <body>
        <h2>🚀 AI Video Generation VPS Telemetry</h2>
        <div class="grid">
            <div class="card">
                <h3>GPU Memory (VRAM)</h3>
                <div class="metric" id="vram-val">0 / 0 MB</div>
                <div class="progress-bar"><div class="progress-fill" id="vram-fill"></div></div>
            </div>
            <div class="card">
                <h3>GPU Utilization</h3>
                <div class="metric" id="gpu-util">0%</div>
            </div>
            <div class="card">
                <h3>Pipeline Status</h3>
                <div class="metric"><span class="badge" id="pipe-status">Idle</span></div>
                <p id="pipe-step" style="color: #94a3b8;">Waiting for jobs...</p>
            </div>
            <div class="card">
                <h3>Script Latency</h3>
                <div class="metric" id="pipe-latency">0.00s</div>
            </div>
        </div>
        <script>
            const evtSource = new EventSource("/metrics/stream");
            evtSource.onmessage = function(event) {
                const data = JSON.parse(event.data);
                document.getElementById('vram-val').innerText = `${data.gpu.used_mb} / ${data.gpu.total_mb} MB`;
                const vramPercent = (data.gpu.used_mb / data.gpu.total_mb) * 100 || 0;
                document.getElementById('vram-fill').style.width = `${vramPercent}%`;
                document.getElementById('gpu-util').innerText = `${data.gpu.utilization}%`;
                document.getElementById('pipe-status').innerText = data.state.status;
                document.getElementById('pipe-step').innerText = `Step: ${data.state.current_step} (${data.state.processed_scenes}/${data.state.total_scenes})`;
                document.getElementById('pipe-latency').innerText = `${data.state.model_load_latency.toFixed(2)}s`;
            };
        </script>
    </body>
    </html>
    """