import logging
import time
import random
import json
import socket
import os
import sys
from datetime import datetime, timezone
from threading import Thread, Event
from concurrent.futures import ThreadPoolExecutor

class ResilientLogstashHandler(logging.Handler):
    def __init__(self, host, port, max_retries=5, timeout=10):
        super().__init__()
        self.host = host
        self.port = port
        self.max_retries = max_retries
        self.timeout = timeout
        self._socket = None
        self._connection_lock = Event()
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._shutdown_flag = False

    def _establish_connection(self):
        """Establish connection with exponential backoff"""
        for attempt in range(self.max_retries):
            try:
                if self._shutdown_flag:
                    return False
                    
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.timeout)
                sock.connect((self.host, self.port))
                self._socket = sock
                print(f"✅ Connected to Logstash at {self.host}:{self.port}")
                return True
            except Exception as e:
                if attempt == self.max_retries - 1:
                    print(f"❌ Failed to connect after {attempt+1} attempts: {str(e)}")
                    return False
                wait_time = min(2 ** attempt, 10)  # Exponential backoff, max 10s
                print(f"⏳ Connection attempt {attempt+1} failed, retrying in {wait_time}s...")
                time.sleep(wait_time)
        return False

    def emit(self, record):
        """Asynchronously send log with retry logic"""
        if self._shutdown_flag:
            return
            
        self._executor.submit(self._send_with_retry, record)

    def _send_with_retry(self, record):
        """Thread-safe log sending with retries"""
        for attempt in range(self.max_retries):
            try:
                if not self._socket and not self._establish_connection():
                    continue
                    
                log_message = self.format(record)
                if not isinstance(log_message, (str, bytes, bytearray)):
                    log_message = json.dumps({"message": str(log_message)})
                
                self._socket.sendall((log_message + '\n').encode('utf-8'))
                return  # Success
                
            except Exception as e:
                print(f"⚠️ Send failed (attempt {attempt+1}): {str(e)}")
                self._socket = None
                if attempt < self.max_retries - 1:
                    time.sleep(1)
                continue

    def close(self):
        """Graceful shutdown"""
        self._shutdown_flag = True
        self._executor.shutdown(wait=True)
        if self._socket:
            try:
                self._socket.close()
            except:
                pass
        super().close()

class CloudJSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "@timestamp": datetime.now(timezone.utc).isoformat(),
            "service": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
            "kubernetes": {
                "pod": os.getenv('POD_NAME', 'N/A'),
                "node": os.getenv('NODE_NAME', 'N/A'),
                "namespace": os.getenv('NAMESPACE', 'N/A')
            },
            "cloud": {
                "provider": os.getenv('CLOUD_PROVIDER', 'local'),
                "region": os.getenv('CLOUD_REGION', 'local')
            }
        }
        # Add all extra fields
        if hasattr(record, 'extra'):
            log_entry.update(record.extra)
        return json.dumps(log_entry)

def configure_logger(service_name):
    """Configure a cloud-native ready logger"""
    logger = logging.getLogger(service_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    
    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Add Logstash handler if configured
    if os.getenv('LOGSTASH_ENABLED', 'false').lower() == 'true':
        handler = ResilientLogstashHandler(
            host=os.getenv('LOGSTASH_HOST', 'logstash.logging.svc.cluster.local'),
            port=int(os.getenv('LOGSTASH_PORT', '5044'))
        )
        handler.setFormatter(CloudJSONFormatter())
        logger.addHandler(handler)
    
    # Always log to stdout (for Kubernetes)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(CloudJSONFormatter())
    logger.addHandler(stdout_handler)
    
    return logger

def simulate_microservice(service_name, stop_event):
    """Simulate a microservice with realistic logging"""
    logger = configure_logger(service_name)
    
    actions = {
        "auth": ["login", "logout", "token_refresh"],
        "payment": ["process", "refund", "invoice"],
        "inventory": ["check", "update", "restock"],
        "user": ["create", "update", "delete"],
        "order": ["create", "cancel", "fulfill"]
    }
    
    status_codes = {
        "success": [200, 201],
        "client_error": [400, 401, 403, 404],
        "server_error": [500, 502, 503]
    }
    
    while not stop_event.is_set():
        try:
            action = random.choice(actions[service_name.split('-')[0]])
            status = random.choice(
                status_codes["success"] * 8 +  # 80% success
                status_codes["client_error"] +  # 15% client errors
                status_codes["server_error"]    # 5% server errors
            )
            latency = round(random.uniform(0.1, 2.5), 3)
            
            log_data = {
                "user_id": f"user_{random.randint(1000, 9999)}",
                "request_id": f"req_{random.randint(100000, 999999)}",
                "response_time": latency,
                "status_code": status,
                "action": action
            }
            
            if status in status_codes["server_error"]:
                logger.error(f"Server error during {action}", extra=log_data)
            elif status in status_codes["client_error"]:
                logger.warning(f"Client error during {action}", extra=log_data)
            else:
                logger.info(f"Completed {action}", extra=log_data)
                
            time.sleep(random.uniform(0.5, 2.0))
            
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", extra={
                "error_type": type(e).__name__,
                "stack_trace": str(e)
            })
            time.sleep(5)  # Prevent tight error loops

def main():
    """Entry point with graceful shutdown handling"""
    stop_event = Event()
    
    services = [
        "auth-service",
        "payment-service",
        "inventory-service",
        "user-service",
        "order-service"
    ]
    
    threads = []
    for service in services:
        t = Thread(
            target=simulate_microservice,
            args=(service, stop_event),
            daemon=True
        )
        t.start()
        threads.append(t)
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down gracefully...")
        stop_event.set()
        for t in threads:
            t.join(timeout=5)
        print("✅ Clean shutdown complete")

if __name__ == "__main__":
    main()