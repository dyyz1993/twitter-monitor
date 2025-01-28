import os
import json
import time
import logging
import asyncio
from pyppeteer import connect
from typing import Dict, Optional, Tuple, List
from datetime import datetime
import aiohttp

class ChromeFetcher:
    def __init__(self, config):
        self.config = config
        self.screenshots_dir = config.screenshots_dir  # 使用配置中的截图目录
        self.chrome_host = os.getenv('CHROME_HOST', '192.168.0.29')
        self.chrome_port = os.getenv('CHROME_PORT', '19223')
        self.browser = None
        self.page = None
        self._closed = False
        self._last_health_check = 0
        self._health_check_interval = 30  # 每30秒检查一次连接状态
        
        # 确保截图目录存在
        os.makedirs(self.screenshots_dir, exist_ok=True)
        logging.info(f"截图保存目录: {self.screenshots_dir}")
        
    async def _get_ws_endpoint(self) -> str:
        """获取 Chrome WebSocket 地址"""
        try:
            url = f'http://{self.chrome_host}:{self.chrome_port}/json/version'
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(url, timeout=5) as response:
                        if response.status != 200:
                            raise RuntimeError(f"Chrome 连接失败: HTTP {response.status}")
                        
                        content_type = response.headers.get('content-type', '')
                        if 'application/json' not in content_type:
                            raise RuntimeError(f"Chrome 返回类型错误: {content_type}")
                        
                        data = await response.json()
                        if not data.get('webSocketDebuggerUrl'):
                            raise RuntimeError("未找到 WebSocket URL")
                            
                        ws_url = data['webSocketDebuggerUrl']
                        return ws_url.replace(
                            f'ws://{self.chrome_host}/',
                            f'ws://{self.chrome_host}:{self.chrome_port}/'
                        )
                except asyncio.TimeoutError:
                    raise RuntimeError(f"连接超时: {url}")
                except aiohttp.ClientError as e:
                    raise RuntimeError(f"连接错误: {str(e)}")
        except Exception as e:
            logging.error(f"获取 Chrome WebSocket 地址失败: {str(e)}")
            raise RuntimeError(f"Chrome 连接失败: {str(e)}")
    
    async def connect(self):
        """连接到远程 Chrome"""
        if self._closed:
            raise RuntimeError("ChromeFetcher 已关闭")
            
        retries = 3
        last_error = None
        
        for i in range(retries):
            try:
                ws_endpoint = await self._get_ws_endpoint()
                logging.info(f"连接到远程 Chrome: {ws_endpoint}")
                
                self.browser = await connect(
                    browserWSEndpoint=ws_endpoint,
                    options={
                        'headless': True,
                        'args': ['--no-sandbox']
                    }
                )
                
                self.page = await self.browser.newPage()
                await self.page.setViewport({'width': 1920, 'height': 2160})
                await self.page.setCacheEnabled(True)
                
                # 添加到活跃连接列表
                if not hasattr(self.config, '_active_chrome_fetchers'):
                    self.config._active_chrome_fetchers = set()
                self.config._active_chrome_fetchers.add(self)
                
                logging.info("成功连接到远程 Chrome")
                return
                
            except Exception as e:
                last_error = e
                logging.warning(f"第 {i+1} 次连接失败: {str(e)}")
                await asyncio.sleep(1)
        
        raise RuntimeError(f"连接 Chrome 失败，已重试 {retries} 次: {str(last_error)}")
            
    async def is_connected(self) -> bool:
        """检查浏览器连接是否有效"""
        try:
            if not self.browser:
                return False
            if self._closed:
                return False
            # 尝试执行一个简单的操作来验证连接
            pages = await self.browser.pages()
            return True
        except Exception:
            return False
            
    async def check_connection(self) -> bool:
        """检查并尝试恢复连接"""
        now = time.time()
        # 避免过于频繁的检查
        if now - self._last_health_check < self._health_check_interval:
            return await self.is_connected()
            
        self._last_health_check = now
        
        try:
            if not await self.is_connected():
                logging.warning("检测到 Chrome 连接已断开，尝试重新连接")
                await self.reconnect()
                return await self.is_connected()
            return True
        except Exception as e:
            logging.error(f"连接检查失败: {str(e)}")
            return False
            
    async def reconnect(self):
        """重新建立连接"""
        try:
            # 先清理旧连接
            await self.close()
            # 重新连接
            await self.connect()
        except Exception as e:
            logging.error(f"重新连接失败: {str(e)}")
            raise

    async def fetch_tweets(self, instance: str, username: str) -> str:
        """获取推文内容，异步处理截图"""
        # 在执行操作前检查连接状态
        if not await self.check_connection():
            raise RuntimeError("Chrome 连接不可用")
            
        try:
            # 创建新页面
            self.page = await self.browser.newPage()
            
            # 设置页面参数
            await self.page.setViewport({'width': 1920, 'height': 2160})
            await self.page.setCacheEnabled(True)
            
            # 设置更真实的请求头
            await self.page.setExtraHTTPHeaders({
                'Accept-Language': 'en-US,en;q=0.9',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            })
            
            # 禁用某些可能触发检测的特性
            await self.page.evaluateOnNewDocument('''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            ''')
            
            url = f"{instance}/{username}"
            logging.info(f"访问页面: {url}")
            
            # 设置请求拦截
            await self.page.setRequestInterception(True)
            
            def handle_request(request):
                """同步的请求处理函数"""
                asyncio.create_task(async_handle_request(request))
            
            async def async_handle_request(request):
                """异步的请求处理函数"""
                try:
                    # 阻止加载某些资源以提高性能和降低检测风险
                    if request.resourceType in ['image', 'media', 'font']:
                        await request.abort()
                    elif 'check1.js' in request.url:
                        # 如果检测到 check1.js，返回空内容
                        await request.respond({
                            'status': 200,
                            'contentType': 'application/javascript',
                            'body': ''
                        })
                    else:
                        await request.continue_()
                except Exception as e:
                    logging.error(f"处理请求时出错: {str(e)}")
                    try:
                        await request.continue_()
                    except:
                        pass
            
            # 使用同步函数作为事件处理器
            self.page.on('request', handle_request)
            
            # 访问页面，使用更长的超时时间
            await self.page.goto(url, {
                'waitUntil': 'networkidle0',
                'timeout': 30000
            })
            
            # 模拟鼠标移动
            await self.page.mouse.move(100, 100)
            
            # 等待推文加载
            await self.page.waitForSelector('.timeline-item', {'timeout': 5000})
            
            # 获取页面 HTML
            html_content = await self.page.content()
            
            # 创建截图任务并等待
            await self._save_screenshots()
            
            return html_content
            
        except Exception as e:
            # 如果出现连接相关错误，标记连接状态
            if "Maximum call stack size exceeded" in str(e):
                logging.error(f"检测到反爬虫机制 ({url}): {str(e)}")
                self.instance_manager.update_health(instance, False)  # 标记实例不健康
            elif "Connection is closed" in str(e) or "Protocol error" in str(e):
                self._closed = True
            raise
            
        finally:
            # 清理资源
            if self.page:
                try:
                    # await self.page.removeAllListeners()  # 移除所有事件监听器
                    await asyncio.wait_for(self.page.close(), timeout=2.0)
                    self.page = None
                except Exception as e:
                    logging.error(f"关闭页面时出错: {str(e)}")
            
    async def _save_screenshots(self):
        """保存推文截图"""
        try:
            # 获取所有推文元素
            tweets = await self.page.querySelectorAll('.timeline-item')
            total_tweets = len(tweets)
            logging.info(f"找到 {total_tweets} 条推文需要截图")
            # 往代码里面插入 变量样式 --bg_panel: #fffdfd;
            await self.page.evaluate(
                'document.body.style.setProperty("--bg_panel", "#fff !important");'
                'document.body.style.setProperty("--fg_color", "#010101 !important");'
                'document.body.style.setProperty("--border_grey", "#ebeaea !important");'
            )
            
            if total_tweets == 0:
                logging.warning("没有找到任何推文元素")
                return
            
            # 为每条推文生成截图
            successful_screenshots = 0
            
            for i, tweet in enumerate(tweets):
                try:
                    # 获取推文ID
                    try:
                        raw_id = await self.page.evaluate(
                            '(element) => element.querySelector(".tweet-link").href.split("/").pop()',
                            tweet
                        )
                      

                        # 清理 ID
                        tweet_id = raw_id.split('#')[0].split('?')[0]
                        logging.debug(f"获取到第 {i} 条推文ID: {tweet_id} (原始ID: {raw_id})")
                    except Exception as e:
                        logging.error(f"获取第 {i} 条推文ID失败: {str(e)}")
                        continue
                    
                    # 检查是否已存在截图
                    screenshot_path = os.path.join(self.screenshots_dir, f'{tweet_id}.png')
                    if not os.path.exists(screenshot_path):
                        try:
                            # 直接截取推文元素
                            await tweet.screenshot({
                                'path': screenshot_path,
                                'type': 'png',
                                'omitBackground': True
                            })
                            
                            # 验证截图是否成功保存
                            if os.path.exists(screenshot_path):
                                size = os.path.getsize(screenshot_path)
                                logging.info(f"成功保存第 {i} 条推文截图: {screenshot_path} (大小: {size/1024:.1f}KB)")
                            else:
                                logging.error(f"截图保存失败: {screenshot_path}")
                                
                        except Exception as e:
                            logging.error(f"截取第 {i} 条推文时出错: {str(e)}")
                            continue
                    else:
                        logging.debug(f"第 {i} 条推文截图已存在: {screenshot_path}")
                        
                    # 更新进度
                    successful_screenshots += 1
                    if successful_screenshots % 5 == 0 or successful_screenshots == total_tweets:
                        logging.info(f"截图进度: {successful_screenshots}/{total_tweets}")
                
                except Exception as e:
                    logging.error(f"处理第 {i} 条推文截图时出错: {str(e)}")
                    continue
            
            logging.info(f"截图任务完成: 成功 {successful_screenshots}/{total_tweets}")
            
        except Exception as e:
            logging.error(f"保存推文截图时出错: {str(e)}")
            
    async def close(self):
        """关闭浏览器连接"""
        if self._closed:
            return
            
        self._closed = True
        try:
            # 先关闭页面
            if self.page:
                try:
                    await asyncio.wait_for(self.page.close(), timeout=2.0)
                except:
                    pass
                self.page = None
                
            # 再关闭浏览器
            if self.browser:
                try:
                    # 获取所有会话ID
                    sessions = await self.browser.pages()
                    for session in sessions:
                        try:
                            await session.close()
                        except:
                            pass
                    
                    # 关闭浏览器连接
                    await asyncio.wait_for(self.browser.close(), timeout=2.0)
                except:
                    pass
                finally:
                    # 调用清理脚本
                    try:
                        from scripts.cleanup_chrome import cleanup
                        cleanup()
                    except Exception as e:
                        logging.error(f"清理 Chrome 会话时出错: {str(e)}")
                    self.browser = None
                
            # 从活跃连接列表中移除
            if hasattr(self.config, '_active_chrome_fetchers'):
                self.config._active_chrome_fetchers.discard(self)
                
            logging.info("已关闭 Chrome 连接")
        except Exception as e:
            logging.error(f"关闭 Chrome 连接时出错: {str(e)}")
        finally:
            # 确保引用被清除
            self.browser = None
            self.page = None 

    async def cleanup_all_sessions(self):
        """清理所有 Chrome 会话并断开连接"""
        if self._closed:
            return
        
        try:
            # 先关闭所有页面
            if self.browser:
                try:
                    pages = await self.browser.pages()
                    for page in pages:
                        try:
                            await asyncio.wait_for(page.close(), timeout=1.0)
                        except:
                            pass
                
                    # 关闭浏览器连接
                    await asyncio.wait_for(self.browser.close(), timeout=2.0)
                    
                    # 调用清理脚本
                    try:
                        from scripts.cleanup_chrome import cleanup
                        cleanup()
                    except Exception as e:
                        logging.error(f"清理 Chrome 会话时出错: {str(e)}")
                except:
                    pass
                finally:
                    self.browser = None
                    self.page = None
                    self._closed = True
                
            logging.info("已清理所有 Chrome 会话")
        except Exception as e:
            logging.error(f"清理 Chrome 会话时出错: {str(e)}") 