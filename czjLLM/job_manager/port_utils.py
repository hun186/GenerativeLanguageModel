# utils/port_utils.py
from urllib.parse import urlparse
import time
import random
import multiprocessing

class PortManager:
    def __init__(self, ports, max_tasks_per_port=1):
        self.manager = multiprocessing.Manager()
        self.lock = multiprocessing.Lock()
        self.port_map = {}
        self.max_tasks = max_tasks_per_port

        for p in ports:
            parsed = urlparse(p["base_url"])
            port_id = f"{parsed.hostname}:{parsed.port}"
            self.port_map[port_id] = p["base_url"]

        self.port_status = self.manager.dict({port_id: 0 for port_id in self.port_map})

    def acquire_port(self, timeout=10):
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self.lock:
                sorted_ports = sorted(self.port_status.items(), key=lambda x: x[1])
                for port_id, count in sorted_ports:
                    if count < self.max_tasks:
                        self.port_status[port_id] += 1
                        return self.port_map[port_id]
            time.sleep(random.uniform(0.2, 0.5))
        raise RuntimeError("❌ 等待端口超時")

    def release_port(self, base_url):
        parsed = urlparse(base_url)
        port_id = f"{parsed.hostname}:{parsed.port}"
        with self.lock:
            if port_id in self.port_status:
                self.port_status[port_id] = max(0, self.port_status[port_id] - 1)
