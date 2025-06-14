import logging
import time
import random
import json
import socket
import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

class K8sLogHandler(logging.Handler):
    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._socket = None

    def _connect(self):
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.connect((self.host, self.port))
            return True
        except Exception as e:
            print(f"Logstash connection failed: {e}")
            return False

    def emit(self, record):
        self.executor.submit(self._send_log, record)

    def _send_log(self, record):
        for attempt in range(3):
            try:
                if not self._socket and not self._connect():
                    continue
                
                self._socket.sendall((self.format(record) + '\n').encode('utf-8'))
                break
            except Exception as e:
                print(f"Log send failed (attempt {attempt+1}): {e}")
                self._socket = None
                time.sleep(1)

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "@timestamp": datetime.now(timezone.utc).isoformat(),
            "service": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
            "kubernetes": {
                "pod": os.getenv('POD_NAME', 'N/A'),
                "node": os.getenv('NODE_NAME', 'N/A')
            },
            **record.__dict__.get('extra', {})
        }
        return json.dumps(log_entry)

def setup_logger(service_name):
    logger = logging.getLogger(service_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    
    handler = K8sLogHandler(
        host=os.getenv('LOGSTASH_HOST'),
        port=int(os.getenv('LOGSTASH_PORT', 5044))
    )  # THIS WAS THE MISSING PARENTHESIS
    
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    return logger



def simulate_microservice(service_name):
    logger = setup_logger(service_name)
    actions = {
        "auth-service": ["login", "logout", "token_refresh"],
        "payment-service": ["process", "refund", "invoice"],
        "inventory-service": ["check", "update", "restock"],
        "user-service": ["create", "update", "delete"],
        "order-service": ["create", "cancel", "fulfill"]
    }
    status_codes = [200, 201, 400, 401, 403, 404, 500, 502, 503]

    while True:
        action = random.choice(actions[service_name])
        status = random.choice(status_codes)
        response_time = round(random.uniform(0.1, 2.5), 3)
        
        if status >= 500:
            log_level = logging.ERROR
            message = f"Server error in {action} - Status: {status}"
        elif status >= 400:
            log_level = logging.WARNING
            message = f"Client error in {action} - Status: {status}"
        else:
            log_level = logging.INFO
            message = f"Successful {action} - Status: {status}"

        extra = {
            'user_id': f"user_{random.randint(1000, 9999)}",
            'request_id': f"req_{random.randint(100000, 999999)}",
            'response_time': response_time,
            'status_code': status
        }

        logger.log(log_level, message, extra=extra)
        time.sleep(random.uniform(0.5, 2.0))

if __name__ == "__main__":
    import threading
    
    services = [
        "auth-service",
        "payment-service",
        "inventory-service",
        "user-service",
        "order-service"
    ]
    
    for service in services:
        t = threading.Thread(
            target=simulate_microservice,
            args=(service,),
            daemon=True
        )
        t.start()
    
    # Keep main thread alive
    while True:
        time.sleep(1)