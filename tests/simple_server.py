from flask import Flask, send_from_directory
import os
import logging
import socket
from pathlib import Path
from werkzeug.serving import run_simple

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def get_local_ip():
    """获取本机局域网IP"""
    try:
        # 创建一个UDP socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 连接一个外部地址（不需要真实可达）
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

def create_app(directory):
    app = Flask(__name__)
    
    # 禁用 Flask 默认日志
    import logging as flask_logging
    flask_logging.getLogger('werkzeug').disabled = True

    @app.route('/')
    def index():
        """显示目录内容"""
        files = os.listdir(directory)
        links = [f'<li><a href="/images/{f}">{f}</a></li>' for f in files]
        return f'''
        <h1>图片服务器</h1>
        <ul>
            {''.join(links)}
        </ul>
        '''

    @app.route('/images/<path:filename>')
    def serve_image(filename):
        """提供图片文件"""
        try:
            return send_from_directory(directory, filename)
        except Exception as e:
            logging.error(f"提供文件出错: {filename}, {str(e)}")
            return "文件未找到", 404

    @app.after_request
    def after_request(response):
        """请求后处理"""
        logging.info(f"{response.status}")
        return response

    return app

def start_server(port=8000):
    """启动服务器"""
    try:
        # 设置服务目录
        directory = str(Path(__file__).parent.parent / 'data' / 'screenshots')
        os.makedirs(directory, exist_ok=True)
        
        # 获取本机IP
        local_ip = get_local_ip()
        
        # 创建应用
        app = create_app(directory)
        
        logging.info(f"服务目录: {directory}")
        logging.info(f"本机IP: {local_ip}")
        logging.info(f"可通过以下地址访问:")
        logging.info(f"- 本机: http://localhost:{port}")
        logging.info(f"- 局域网: http://{local_ip}:{port}")
        
        # 启动服务器
        run_simple(
            '0.0.0.0',
            port,
            app,
            use_reloader=False,
            threaded=True
        )
        
    except Exception as e:
        logging.error(f"服务器错误: {e}", exc_info=True)

if __name__ == "__main__":
    start_server() 