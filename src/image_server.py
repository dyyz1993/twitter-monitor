from flask import Flask, send_file, Response
import os
import logging
import socket
from threading import Thread
from werkzeug.serving import make_server

class ImageServer:
    def __init__(self, screenshots_dir: str, port: int = 3005, host: str = None):
        self.screenshots_dir = screenshots_dir
        self.port = port
        self._thread = None
        self.server = None
        
        # 获取本机IP
        self.host = host or self._get_local_ip()
        
        # 创建 Flask 应用
        self.app = Flask(__name__)
        
        # 默认的 SVG 图片
        self.default_svg = '''
        <svg xmlns="http://www.w3.org/2000/svg" width="400" height="100">
            <rect width="100%" height="100%" fill="#f0f0f0"/>
            <text x="50%" y="50%" font-family="Arial" font-size="16" 
                  text-anchor="middle" dy=".3em" fill="#666">
                图片未找到 (╯°□°）╯︵ ┻━┻
            </text>
        </svg>
        '''
        
        # 注册路由
        @self.app.route('/')
        def home():
            files = os.listdir(self.screenshots_dir)
            links = [f'<li><a href="/images/{f}">{f}</a></li>' for f in files]
            return f'''
            <h1>图片服务器</h1>
            <ul>{''.join(links)}</ul>
            '''
            
        @self.app.route('/images/<path:filename>')
        def serve_image(filename):
            image_path = os.path.join(self.screenshots_dir, filename)
            if os.path.exists(image_path):
                try:
                    return send_file(image_path)
                except Exception as e:
                    logging.error(f"发送文件时出错: {str(e)}")
            
            return Response(
                self.default_svg,
                mimetype='image/svg+xml'
            )
        
        # 禁用 Flask 默认日志
        import logging as flask_logging
        flask_logging.getLogger('werkzeug').disabled = True

    def _get_local_ip(self):
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
    
    def _run_server(self):
        """运行服务器"""
        try:
            # 使用 werkzeug 服务器，总是监听 0.0.0.0
            self.server = make_server(
                '0.0.0.0',  # 始终使用 0.0.0.0 监听所有接口
                self.port, 
                self.app,
                threaded=True
            )
            logging.info(f"图片服务器线程已启动，监听地址: http://0.0.0.0:{self.port}")
            logging.info(f"可通过以下地址访问: http://{self.host}:{self.port}")
            self.server.serve_forever()
        except Exception as e:
            logging.error(f"运行图片服务器时出错: {str(e)}")
    
    def start(self):
        """启动服务器（非阻塞）"""
        if self._thread is None or not self._thread.is_alive():
            self._thread = Thread(target=self._run_server, daemon=True)
            self._thread.start()
            logging.info("图片服务器线程已启动")
    
    def stop(self):
        """停止服务器"""
        if self.server:
            self.server.shutdown()
            logging.info("图片服务器已停止")