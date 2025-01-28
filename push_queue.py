import os
import logging
import requests
import time
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
import pytz

class PushQueue:
    def __init__(self):
        # 加载推送配置
        self.push_channels = self._load_push_channels()
        # 失败重试配置
        self.max_retries = 3
        self.retry_delay = 5
        
        # 设置推送日志
        self.setup_push_logger()
        
        # 确保存档目录存在
        self.archive_dir = os.getenv('ARCHIVE_DIR', 'archives')
        os.makedirs(self.archive_dir, exist_ok=True)
        
        # 推送记录文件
        self.push_log_file = os.path.join(self.archive_dir, 'push_logs.jsonl')
        
        # 时区设置
        self.timezone = pytz.timezone(os.getenv('TIMEZONE', 'Asia/Shanghai'))
        
    def setup_push_logger(self):
        """设置专门的推送日志"""
        # 创建 logs 目录
        log_dir = os.getenv('LOG_DIR', 'logs')
        os.makedirs(log_dir, exist_ok=True)
        
        # 创建推送失败日志的处理器
        push_log_file = os.path.join(log_dir, 'push_failures.log')
        push_handler = logging.FileHandler(push_log_file, encoding='utf-8')
        push_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        ))
        
        # 创建推送日志记录器
        self.push_logger = logging.getLogger('push_queue')
        self.push_logger.setLevel(logging.INFO)
        self.push_logger.addHandler(push_handler)
        
    def log_push_failure(self, channel_type: str, key: str, title: str, error: str):
        """记录推送失败信息"""
        failure_info = {
            'timestamp': datetime.now().isoformat(),
            'channel': channel_type,
            'key': key[:8] + '...',  # 只记录前8位
            'title': title,
            'error': error
        }
        
        # 记录到日志文件
        self.push_logger.error(
            f"推送失败 - 渠道: {channel_type}, Key: {key[:8]}..., "
            f"标题: {title}, 错误: {error}"
        )
        
        # 同时记录到失败队列文件
        try:
            failures_file = os.path.join(
                os.getenv('LOG_DIR', 'logs'), 
                'push_failures.jsonl'
            )
            with open(failures_file, 'a', encoding='utf-8') as f:
                json.dump(failure_info, f, ensure_ascii=False)
                f.write('\n')
        except Exception as e:
            self.push_logger.error(f"记录失败信息时出错: {str(e)}")

    def _load_push_channels(self) -> Dict[str, List[Dict[str, Any]]]:
        """加载所有推送渠道的配置"""
        channels = {
            'serverchan': [],
            'pushdeer': []
        }
        
        try:
            # 强制重新加载 .env 文件
            load_dotenv(override=True)
            
            # 加载 ServerChan 配置
            sc_keys = os.getenv('SC_KEY', '').split(',')
            sc_enabled = os.getenv('SERVERCHAN_ENABLED', 'true').lower() == 'true'
            sc_tags = os.getenv('SERVERCHAN_TAGS', 'twitter|推特监控')
            
            logging.info(f"ServerChan 启用状态: {sc_enabled}")
            if sc_enabled:
                for key in sc_keys:
                    key = key.strip()
                    if key:
                        channels['serverchan'].append({
                            'key': key,
                            'url': "https://3233.push.ft07.com/send/{}.send",
                            'tags': sc_tags,
                            'enabled': True
                        })
                logging.info(f"已加载 {len(channels['serverchan'])} 个 ServerChan 配置")
            
            # 加载 PushDeer 配置
            pd_enabled = str(os.getenv('PUSHDEER_ENABLED', 'false')).lower() == 'true'
            pd_keys = os.getenv('PUSH_KEY', '').split(',')
            
            logging.info(f"PushDeer 启用状态: {pd_enabled}")
            if pd_enabled:
                for key in pd_keys:
                    key = key.strip()
                    if key:
                        channels['pushdeer'].append({
                            'key': key,
                            'url': "https://api2.pushdeer.com/message/push",
                            'enabled': True
                        })
                logging.info(f"已加载 {len(channels['pushdeer'])} 个 PushDeer 配置")
            
            # 验证配置
            total_channels = len(channels['serverchan']) + len(channels['pushdeer'])
            if total_channels == 0:
                logging.warning("未找到任何有效的推送渠道配置！")
            else:
                logging.info(f"总共加载了 {total_channels} 个推送渠道")
                
        except Exception as e:
            logging.error(f"加载推送渠道配置时出错: {str(e)}")
            
        return channels
    
    def archive_push(self, title: str, content: str, success: bool, error: Optional[str] = None):
        """记录推送内容"""
        try:
            now = datetime.now(self.timezone)
            push_data = {
                'title': title,
                'content': content,
                'success': success,
                'error': error,
                'pushed_at': now.isoformat(),
                'timestamp': int(now.timestamp())
            }
            
            with open(self.push_log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(push_data, ensure_ascii=False) + '\n')
                
            logging.debug(f"已记录推送内容: {title}")
            
        except Exception as e:
            logging.error(f"记录推送内容时出错: {str(e)}")

    def push(self, title: str, content: str) -> bool:
        """推送消息到所有启用的渠道"""
        success = False
        error = None
        
        try:
            # 推送到所有 ServerChan 渠道
            for channel in self.push_channels['serverchan']:
                if channel['enabled']:
                    if self._push_to_serverchan(channel, title, content):
                        success = True
            
            # 推送到所有 PushDeer 渠道
            for channel in self.push_channels['pushdeer']:
                if channel['enabled']:
                    if self._push_to_pushdeer(channel, title, content):
                        success = True
        except Exception as e:
            error = str(e)
            logging.error(f"推送消息失败: {error}")
            success = False
        finally:
            # 无论推送成功与否都记录
            self.archive_push(title, content, success, error)
            
        return success
    
    def _push_to_serverchan(self, channel: Dict[str, Any], title: str, content: str) -> bool:
        """推送到 ServerChan"""
        for attempt in range(self.max_retries):
            try:
                url = channel['url'].format(channel['key'])
                
                # 添加标签
                if channel['tags']:
                    title = f"{title} #{channel['tags'].replace('|', '#')}"
                
                response = requests.post(url, json={
                    "text": title,
                    "desp": content,
                    "type": "markdown"
                })
                
                if response.status_code == 200:
                    logging.info(f"ServerChan推送成功 (key: {channel['key'][:8]}...)")
                    return True
                else:
                    error_msg = f"HTTP {response.status_code}: {response.text}"
                    self.log_push_failure('ServerChan', channel['key'], title, error_msg)
                    
            except Exception as e:
                self.log_push_failure('ServerChan', channel['key'], title, str(e))
                
            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay)
                
        return False
    
    def _push_to_pushdeer(self, channel: Dict[str, Any], title: str, content: str) -> bool:
        """推送到 PushDeer"""
        for attempt in range(self.max_retries):
            try:
                response = requests.post(channel['url'], json={
                    "pushkey": channel['key'],
                    "text": title,
                    "desp": content,
                    "type": "markdown"
                })
                
                if response.status_code == 200:
                    logging.info(f"PushDeer推送成功 (key: {channel['key'][:8]}...)")
                    return True
                else:
                    error_msg = f"HTTP {response.status_code}: {response.text}"
                    self.log_push_failure('PushDeer', channel['key'], title, error_msg)
                    
            except Exception as e:
                self.log_push_failure('PushDeer', channel['key'], title, str(e))
                
            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay)
                
        return False 