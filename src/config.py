import os
from dotenv import load_dotenv, dotenv_values
import pytz
import logging

class Config:
    def __init__(self):
        # 优先使用环境变量，如果没有则从 .env 文件读取
        self.env_vars = {
            **dotenv_values(".env"),  # 先读取 .env 文件
            **os.environ  # 环境变量优先级更高
        }
        
        # 基础配置
        self.max_tweets = int(self.env_vars.get('MAX_TWEETS', 3))
        self.check_interval = int(self.env_vars.get('CHECK_INTERVAL', 300))
        self.timezone = pytz.timezone(self.env_vars.get('TIMEZONE', 'Asia/Shanghai'))
        
        # 代理配置
        self.proxy_enabled = self.env_vars.get('PROXY_ENABLED', 'false').lower() == 'true'
        self.proxies = self._setup_proxies()
        
        # 存档配置
        self.archive_dir = self.env_vars.get('ARCHIVE_DIR', 'archives')
        
        # 截图配置
        self.screenshots_dir = self.env_vars.get('SCREENSHOTS_DIR', 'data/screenshots')
        # 确保使用绝对路径
        self.screenshots_dir = os.path.abspath(self.screenshots_dir)
        # 确保目录存在
        os.makedirs(self.screenshots_dir, exist_ok=True)
        logging.info(f"截图目录: {self.screenshots_dir}")
        
        # API配置
        self.deepseek_key = self.env_vars.get('DEEPSEEK_KEY')
        self.deepseek_url = self.env_vars.get('DEEPSEEK_URL', 'https://api.deepseek.com/chat/completions')
        
        # 提示词配置
        self.system_prompt = self.env_vars.get('SYSTEM_PROMPT', '')
        self.user_prompt = self.env_vars.get('USER_PROMPT', '')
        
        # 验证必要的配置
        if not self.deepseek_key:
            raise ValueError("Missing DEEPSEEK_KEY in environment variables")
        if not self.system_prompt:
            raise ValueError("Missing SYSTEM_PROMPT in environment variables")
        if not self.user_prompt:
            raise ValueError("Missing USER_PROMPT in environment variables")
        
        # 用户配置
        self.users = self._load_users()
        
        # 请求头配置
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Cache-Control': 'max-age=0',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1'
        }
        
        # Chrome 配置
        self.chrome_host = self.env_vars.get('CHROME_HOST', '192.168.0.29')
        self.chrome_port = int(self.env_vars.get('CHROME_PORT', '19223'))
        self.chrome_screenshot_dir = os.path.join(self.archive_dir, 'screenshots')
        
        # 主机配置
        self.host = self.env_vars.get('HOST', '192.168.0.29')
        self.image_port = int(self.env_vars.get('IMAGE_PORT', '3005'))
        # 添加域名配置
        self.domain = self.env_vars.get('DOMAIN', '')  # 如果设置了域名，则使用域名
        
        # 构建图片服务器基础URL
        self.image_base_url = (
            f"http://{self.domain}" if self.domain else
            f"http://{self.host}:{self.image_port}"
        )
        
        # 确保必要的目录存在
        self.setup_directories()
        
    def _setup_proxies(self):
        if self.proxy_enabled:
            return {
                'http': self.env_vars.get('HTTP_PROXY'),
                'https': self.env_vars.get('HTTPS_PROXY')
            }
        return None
        
    def setup_directories(self):
        """创建必要的目录"""
        os.makedirs(self.archive_dir, exist_ok=True)
        os.makedirs(self.screenshots_dir, exist_ok=True)
        
    def _load_users(self):
        users = {}
        try:
            with open('.env', 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip().startswith('TWITTER_USERS='):
                        user_list = line.strip().split('=', 1)[1].strip()
                        for user in user_list.split(','):
                            if ':' in user:
                                name, username = user.split(':')
                                users[name.strip()] = username.strip()
        except Exception as e:
            logging.error(f"读取用户配置出错: {str(e)}")
        return users 

    def check_env_variables(self):
        """检查必要的环境变量"""
        required_vars = {
            'TWITTER_USERS': '用户配置',
            'DEEPSEEK_KEY': 'DeepSeek API密钥',
            'PUSH_KEY': '推送密钥'
        }
        
        env_vars = {}
        for var, desc in required_vars.items():
            value = os.getenv(var)
            if not value:
                logging.warning(f"缺少{desc}: {var}")
            env_vars[var] = value
            
        return env_vars 