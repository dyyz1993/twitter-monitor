import os
import logging
from .monitor import TwitterMonitor

def setup_logging():
    """配置日志系统"""
    log_dir = os.getenv('LOG_DIR', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'twitter_monitor.log')
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

def main():
    setup_logging()
    monitor = TwitterMonitor()
    monitor.run()

if __name__ == "__main__":
    main() 