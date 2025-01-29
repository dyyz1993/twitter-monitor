from .config import Config
from .parser import TweetParser
from .translator import Translator
from .archiver import Archiver
from push_queue import PushQueue
import time
import logging
import requests
import random
from typing import List, Dict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta
import os
import json
from .instance_manager import InstanceManager
import asyncio
from .chrome_fetcher import ChromeFetcher
import signal
from .image_server import ImageServer

class TwitterMonitor:
    def __init__(self):
        self.config = Config()
        self.parser = TweetParser(self.config)
        self.translator = Translator(self.config)
        self.archiver = Archiver(self.config)
        self.push_queue = PushQueue()
        
        # 添加时区配置
        self.timezone = self.config.timezone
        
        # 实例管理器
        self.instance_manager = InstanceManager(self.config.archive_dir, self.config.proxies)
        
        # 初始化会话
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.5)
        self.session.mount('http://', HTTPAdapter(max_retries=retry))
        self.session.mount('https://', HTTPAdapter(max_retries=retry))
        
        # 每天清理一次实例状态
        self.last_cleanup = time.time()  # 初始化为当前时间
        self.cleanup_interval = 24 * 3600  # 24小时
        
        # 添加信号处理
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        
        self._shutdown = False
        self._loop = None  # 保存事件循环的引用
        
        # 创建并启动图片服务器
        self.image_server = ImageServer(
            screenshots_dir=self.config.screenshots_dir,
            port=self.config.image_port,
            host=self.config.host
        )
        self.image_server.start()  # 非阻塞启动
        
        self._chrome_fetcher = None  # 只保持一个 Chrome 实例
        
    def _handle_shutdown(self, signum, frame):
        """处理关闭信号"""
        if self._shutdown:  # 如果已经在关闭中，直接返回
            return
            
        logging.info("接收到关闭信号,开始清理...")
        self._shutdown = True
        
        try:
            # 先关闭所有 Chrome 连接
            if hasattr(self, '_active_chrome_fetchers'):
                for fetcher in list(self._active_chrome_fetchers):
                    try:
                        # 强制同步关闭
                        if self._loop and self._loop.is_running():
                            self._loop.run_until_complete(fetcher.close())
                    except:
                        pass
            
            # 运行清理脚本
            try:
                from scripts.cleanup_chrome import cleanup
                cleanup()
            except:
                pass
            
            # 强制退出进程
            logging.info("Chrome 实例已清理，正在退出...")
            os._exit(0)
            
        except Exception as e:
            logging.error(f"关闭时出错: {str(e)}")
            os._exit(1)

    async def _get_chrome_fetcher(self):
        """获取或创建 Chrome 连接"""
        try:
            if not self._chrome_fetcher:
                self._chrome_fetcher = ChromeFetcher(self.config)
                await self._chrome_fetcher.connect()
                logging.info("创建新的 Chrome 连接")
            elif not await self._chrome_fetcher.check_connection():
                # 如果连接检查失败，创建新连接
                logging.warning("Chrome 连接已断开，创建新连接")
                self._chrome_fetcher = ChromeFetcher(self.config)
                await self._chrome_fetcher.connect()
            return self._chrome_fetcher
        except Exception as e:
            logging.error(f"获取 Chrome 连接失败: {str(e)}")
            raise

    async def _fetch_tweets_async(self, instance: str, username: str):
        """异步获取推文"""
        fetcher = await self._get_chrome_fetcher()
        return await fetcher.fetch_tweets(instance, username)

    def get_tweets_with_retry(self, username: str, max_retries: int = 5) -> List[Dict]:
        """带重试机制的推文获取"""
        retries = 0
        while retries < max_retries:
            instance = self.instance_manager.select_instance()
            if not instance:
                logging.error("无可用实例")
                time.sleep(5)
                retries += 1
                continue
            
            try:
                # 使用异步方式获取推文
                loop = asyncio.get_event_loop()
                html_content = loop.run_until_complete(
                    self._fetch_tweets_async(instance, username)
                )
                
                # 解析推文
                tweets = self.parser.parse_tweets(html_content)
                if tweets:
                    # 添加截图路径（推文ID.png）
                    for tweet in tweets:
                        tweet['screenshot'] = os.path.join(
                            self.config.screenshots_dir,
                            f"{tweet['id']}.png"
                        )
                    
                    self.instance_manager.update_health(instance, True)
                    logging.info(f"从 {instance} 成功获取到 {len(tweets)} 条推文")
                    return tweets
                else:
                    logging.warning(f"从 {instance} 获取到空的推文列表")
                    self.instance_manager.update_health(instance, False)
                    
            except Exception as e:
                logging.error(f"获取推文失败 ({instance}): {str(e)}")
                self.instance_manager.update_health(instance, False)
            
            retries += 1
            if retries < max_retries:
                time.sleep(2 * (retries + 1))
        
        logging.error(f"在尝试 {max_retries} 次后仍未能获取推文")
        return []

    def check_updates(self):
        """检查所有用户的更新"""
        try:
            # 添加更详细的日志
            logging.info("=" * 50)
            logging.info("开始检查以下用户的更新:")
            for name, username in self.config.users.items():
                logging.info(f"- {name}: @{username}")
            logging.info("=" * 50)
            
            for name, username in self.config.users.items():
                self._process_user_updates(name, username)
                
        except Exception as e:
            logging.error(f"检查更新过程中发生严重错误: {str(e)}", exc_info=True)
            self.push_queue.push(
                "🚨 Twitter监控发生错误",
                f"### ⚠️ 错误信息\n\n{str(e)}\n\n请检查日志获取详细信息。"
            )

    def run(self):
        """运行监控程序"""
        logging.info("Starting Twitter monitor...")
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        
        try:
            # 直接启动图片服务器（非阻塞）
            self.image_server.start()
            
            while not self._shutdown:
                try:
                    # 定期检查 Chrome 连接状态
                    if self._chrome_fetcher:
                        # 使用 run_until_complete 而不是 create_task
                        self._loop.run_until_complete(self._chrome_fetcher.check_connection())
                    
                    now = time.time()
                    if now - self.last_cleanup >= self.cleanup_interval:
                        self.instance_manager.cleanup_expired()
                        self.last_cleanup = now
                    
                    # 执行主要的检查更新任务
                    self.check_updates()
                    
                    # 检查是否需要关闭
                    if self._shutdown:
                        break
                    
                    logging.info(f"等待 {self.config.check_interval} 秒")
            
                   
                    
                    # 使用事件循环等待
                    self._loop.run_until_complete(asyncio.sleep(self.config.check_interval))
                    
                except asyncio.CancelledError:
                    logging.info("任务被取消")
                    break
                except Exception as e:
                    logging.error(f"Unexpected error: {str(e)}", exc_info=True)
                    if not self._shutdown:
                        # 出错后等待一分钟再重试
                        self._loop.run_until_complete(asyncio.sleep(60))
                    
        finally:
            # 清理资源
            try:
                self._cleanup()
            finally:
                # 确保事件循环被关闭
                try:
                    if not self._loop.is_closed():
                        self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                        self._loop.close()
                except Exception as e:
                    logging.error(f"关闭事件循环时出错: {str(e)}")
                logging.info("Twitter monitor stopped.")

    async def _cleanup(self):
        """清理资源"""
        try:
            # 关闭 Chrome 连接
            if self._chrome_fetcher:
                await self._chrome_fetcher.close()
                self._chrome_fetcher = None
            
            # 停止图片服务器
            if hasattr(self, 'image_server'):
                self.image_server.stop()
            
        except Exception as e:
            logging.error(f"清理资源时出错: {str(e)}")

    def push_tweet(self, tweet: Dict, analysis: str) -> bool:
        """推送推文"""
        try:
            logging.debug(f"开始处理推文: {tweet.get('id')}")
            logging.debug(f"analysis 类型: {type(analysis)}")
            logging.debug(f"analysis 内容: {analysis}")
            
            # 构建标题部分
            title_parts = []
            
            # 1. 从 hints 中提取特殊标记
            hints = self.translator.extract_section(analysis, "重点提示")
            if hints:
                logging.debug(f"处理 hints 中的 emoji: {hints}")  # 调试日志
                # 按优先级顺序检查表情符号
                for emoji in ['💰', '🚀', '🤖', '💊', '🀄']:
                    if emoji in hints:
                        title_parts.append(emoji)
                        logging.debug(f"找到并添加 emoji: {emoji}")  # 调试日志
                        break
            
            # 2. 添加转发/引用标记
            if tweet.get('is_retweet'):
                title_parts.append("🔄 [转发]")
            elif tweet.get('is_quote'):
                title_parts.append("💬 [引用]")
            
            # 3. 添加作者标记
            title_parts.append(f"【{tweet['name']}】")
            
            # 4. 添加内容概要
            summary = self.translator.extract_section(analysis, "内容概要")
            if summary:
                title_parts.append(summary)
            
            # 组合标题
            title = " ".join(title_parts)
            
            # 标题增加颜色
            
            # 添加媒体信息
            media_section = ""
            if tweet.get('media'):
                media_section = "\n### 📷 媒体\n\n"
                for media in tweet['media']:
                    media_type = media.get('type', 'unknown')
                    if media_type == 'image':
                        media_section += f"![图片]({media.get('url')})\n"
                    elif media_type == 'video':
                        media_section += f"🎬 [视频链接]({media.get('url')})\n"
                    elif media_type == 'gif':
                        media_section += f"🎞️ [GIF]({media.get('url')})\n"

           

            # 添加转发/引用信息
            reference_section = ""
            if tweet.get('is_retweet') and tweet.get('retweet_author'):
                reference_section = (
                    f"\n### 🔄 转发自\n\n"
                    f"**@{tweet['retweet_author']}**\n\n"
                )
            elif tweet.get('is_quote') and tweet.get('quote_text'):
                reference_section = (
                    f"\n### 💬 引用推文\n\n"
                    f"**@{tweet.get('quote_author', '未知用户')}**：\n"
                    f"{tweet['quote_text']}\n\n"
                )

            # 确保 tweet_id 是清理过的
            tweet_id = tweet['id'].split('#')[0].split('?')[0]
            image_url = f"{self.config.image_base_url}/images/{tweet_id}.png"
            screenshot_section = (
                f"\n### 📸 截图\n\n"
                f"![推文截图]({image_url})\n"
            )

            # 组合完整内容
            content = (
                f"### 📊 AI分析\n\n"
                f"{analysis}\n\n"
                f"### ℹ️ 详细信息\n\n"
                f"- **📅 发布时间**: {tweet.get('time','未知')}\n"
                f"- **📅 发布日期**: {tweet.get('formatted_time','-')}\n"
                f"- **🔗 原文链接**: [点击查看]({tweet.get('url', '#')})\n"
                f"- **📌 推文ID**: `{tweet.get('id', 'unknown')}`\n"
                f"{reference_section}"
                f"\n### 📝 原文\n\n"
                f"{tweet.get('text', '无内容')}"
                f"{media_section}"
                f"{screenshot_section}"
            )
            
            # 推送消息
            success = self.push_queue.push(title, content)
            if success:
                logging.info(f"成功推送推文: {tweet.get('id', 'unknown')}")
            else:
                logging.error(f"推送失败: {tweet.get('id', 'unknown')}")
                
            return success
            
        except Exception as e:
            logging.error(f"推送推文时出错: {str(e)}")
            return False

    def parse_tweet_time(self, time_str: str) -> tuple:
        """解析推文时间"""
        try:
            now = datetime.now(self.timezone)
            logging.debug(f"开始解析时间: {time_str}")
            
            # 处理相对时间格式 (例如: "1h", "2h", "3m")
            if any(unit in time_str.lower() for unit in ['h', 'm', 's']):
                value = int(''.join(filter(str.isdigit, time_str)))
                unit = ''.join(filter(str.isalpha, time_str.lower()))
                logging.debug(f"检测到相对时间格式: 值={value}, 单位={unit}")
                
                if unit == 'h':
                    delta = timedelta(hours=value)
                elif unit == 'm':
                    delta = timedelta(minutes=value)
                elif unit == 's':
                    delta = timedelta(seconds=value)
                else:
                    logging.warning(f"未知的时间单位: {unit} in {time_str}")
                    return now, "未知时间"
                    
                parsed_time = now - delta
                logging.debug(f"相对时间解析结果: {parsed_time}")
                
            else:
                # 处理绝对时间格式
                formats = [
                    '%d %b %Y',                    # 25 Dec 2024
                    '%d %b %Y · %H:%M',            # 25 Dec 2024 · 15:30
                    '%d %b %Y · %I:%M %p',         # 25 Dec 2024 · 3:30 PM
                    '%b %d, %Y · %I:%M %p %Z',     # Jan 23, 2024 · 10:30 AM UTC
                    '%b %d, %Y · %H:%M %Z',        # Jan 23, 2024 · 22:30 UTC
                    '%Y-%m-%d %H:%M:%S %Z',        # 2024-01-23 22:30:00 UTC
                    '%b %d, %Y',                   # Jan 23, 2024
                    '%b %d'                        # Jan 23
                ]
                
                logging.debug(f"尝试解析绝对时间格式: {time_str}")
                parsed_time = None
                current_year = now.year
                
                for fmt in formats:
                    try:
                        if fmt == '%b %d':
                            # 处理只有月日的情况
                            naive_time = datetime.strptime(f"{time_str}, {current_year}", '%b %d, %Y')
                            temp_time = self.timezone.localize(naive_time)
                            if temp_time > now:
                                naive_time = datetime.strptime(f"{time_str}, {current_year-1}", '%b %d, %Y')
                                temp_time = self.timezone.localize(naive_time)
                            parsed_time = temp_time
                            logging.debug(f"使用格式 {fmt} 成功解析时间: {parsed_time}")
                            break
                        else:
                            naive_time = datetime.strptime(time_str, fmt)
                            parsed_time = self.timezone.localize(naive_time)
                            logging.debug(f"使用格式 {fmt} 成功解析时间: {parsed_time}")
                            break
                    except ValueError:
                        logging.debug(f"格式 {fmt} 解析失败，尝试下一个格式")
                        continue
                
                if not parsed_time:
                    logging.warning(f"无法解析时间格式: {time_str} (尝试的格式: {formats})")
                    return now, "未知时间"
            
            # 格式化为易读的字符串
            formatted_time = parsed_time.strftime('%Y-%m-%d %H:%M:%S')
            logging.info(f"时间解析成功: {time_str} -> {formatted_time}")
            
            return parsed_time, formatted_time
            
        except Exception as e:
            logging.error(f"解析时间出错 ({time_str}): {str(e)}", exc_info=True)
            return now, "未知时间"

    def is_duplicate_tweet(self, tweet: Dict, window_minutes: int = 30) -> bool:
        """检查是否是重复推文（短时间内相同内容）"""
        now = time.time()
        tweet_text = tweet.get('text', '')
        
        # 获取最近的推文记录
        recent_tweets = self.archiver.get_recent_tweets(minutes=window_minutes)
        
        for old_tweet in recent_tweets:
            # 跳过自己
            if old_tweet['id'] == tweet['id']:
                continue
            
            # 检查内容相似度
            old_text = old_tweet.get('text', '')
            if self._calculate_similarity(tweet_text, old_text) > 0.85:  # 85%相似度
                logging.warning(
                    f"检测到可能的重复推文:\n"
                    f"新推文 ({tweet['id']}): {tweet_text[:100]}...\n"
                    f"旧推文 ({old_tweet['id']}): {old_text[:100]}..."
                )
                return True
        
        return False

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算两段文本的相似度（简单实现）"""
        # 这里使用简单的字符匹配，实际可以使用更复杂的算法
        s1 = set(text1.split())
        s2 = set(text2.split())
        
        if not s1 or not s2:
            return 0.0
        
        intersection = len(s1.intersection(s2))
        union = len(s1.union(s2))
        
        return intersection / union if union > 0 else 0.0

    def _process_user_updates(self, name: str, username: str) -> None:
        """处理单个用户的更新"""
        try:
            logging.info(f"正在检查 {name} (@{username}) 的更新...")
            tweets = self.get_tweets_with_retry(username)
            
            if not tweets:
                logging.warning(f"未获取到 {name} 的推文")
                return
            
            # 添加统计信息，区分不同类型的推文
            pinned_count = sum(1 for t in tweets if t.get('is_pinned', False))
            retweet_count = sum(1 for t in tweets if t.get('is_retweet', False))
            quote_count = sum(1 for t in tweets if t.get('is_quote', False))
            normal_count = len(tweets) - pinned_count - retweet_count - quote_count + (
                sum(1 for t in tweets if t.get('is_retweet', False) and t.get('is_quote', False))
                )  # 修正重复计算
            
            logging.info(
                f"获取到 {len(tweets)} 条推文 "
                f"(置顶: {pinned_count}, "
                f"转发: {retweet_count}, "
                f"引用: {quote_count}, "
                f"普通: {normal_count})"
            )
            
            # 修改时间检查逻辑
            now = datetime.now(self.timezone)
            three_days_ago = now - timedelta(days=3)
            valid_tweets = []
            old_tweets = []
            new_tweets = []
            exist_tweets = []
            
            logging.info(f"开始处理 {len(tweets)} 条推文...")
            for tweet in tweets:
                can_send = True
                # 检查推文ID
                if not tweet.get('id'):
                    logging.error("推文缺少ID，跳过处理")
                    continue
                
                # 解析推文时间
                parsed_time, formatted_time = self.parse_tweet_time(tweet['time'])
                tweet['formatted_time'] = formatted_time
                
                # 检查是否已发送过
                if self.archiver.is_sent(tweet['id']):
                    exist_tweets.append(tweet['id'])
                    logging.info(f"已存在的推文: {tweet['id']} ({formatted_time})")
                    can_send = False
                    
                
                # 检查时间是否在3天内
                if parsed_time > three_days_ago:
                    # 检查是否是重复推文
                    if self.is_duplicate_tweet(tweet):
                        logging.info(f"跳过可能的重复推文: {tweet['id']}")
                        can_send = False
                    new_tweets.append(tweet)
                    logging.debug(f"发现3天内的推文: {tweet['id']} ({formatted_time})")
                else:
                    old_tweets.append(tweet)
                    logging.debug(f"超过3天的推文: {tweet['id']} ({formatted_time})")
                    can_send = False
                if can_send:
                    valid_tweets.append(tweet)
                    logging.debug(f"发现新推文: {tweet['id']} ({formatted_time})")
            
            logging.info(
                f"推文统计:\n"
                f"- 总数: {len(tweets)} 条\n"
                f"- 3天内: {len(new_tweets)} 条\n"
                f"- 3天外: {len(old_tweets)} 条\n"
                f"- 新推文: {len(valid_tweets)} 条\n"
                f"- 已存在: {len(exist_tweets)} 条"
            )
            
            # 处理新推文
            for tweet in valid_tweets:
                try:
                    logging.info(
                    f"开始处理新推文: {tweet['id']} "
                    f"{'[置顶]' if tweet.get('is_pinned') else ''}"
                    f"{'[转发]' if tweet.get('is_retweet') else ''}"
                    f"{'[引用]' if tweet.get('is_quote') else ''}"
                    f" ({tweet['formatted_time']})"
                    )

                    # 构建完整的推文数据
                    tweet_data = {
                        'id': tweet['id'],
                        'username': username,
                        'name': name,
                        'text': tweet['text'],
                        'time': tweet['time'],
                        'formatted_time': tweet['formatted_time'],
                        'url': tweet['url'],  # 使用构建的 URL
                        'is_pinned': tweet.get('is_pinned', False),
                        'is_retweet': tweet.get('is_retweet', False),
                        'is_quote': tweet.get('is_quote', False),
                        'retweet_author': tweet.get('retweet_author'),
                        'quote_text': tweet.get('quote_text'),
                        'quote_author': tweet.get('quote_author'),
                        'media': tweet.get('media', []),
                        'links': tweet.get('links', [])
                    }
                    
                    # 存档原始推文（但不记录为已发送）
                    self.archiver.archive_raw_tweet(tweet_data)
                    
                    # 翻译和分析
                    analysis = self.translator.analyze_tweet(tweet_data)
                    if not analysis:
                        # 翻译失败或无需翻译时的处理
                        logging.warning(f"推文无需翻译或翻译失败: {tweet['id']}")
                        # 确保 tweet_id 是清理过的
                        tweet_id = tweet['id'].split('#')[0].split('?')[0]
                        image_url = f"{self.config.image_base_url}/images/{tweet_id}.png"
                        screenshot_section = (
                            f"\n### 📸 截图\n\n"
                            f"![推文截图]({image_url})\n"
                        )
                        # 构建媒体部分
                        media_section = ""
                        if tweet_data.get('media'):
                            media_section = "\n### 📷 媒体\n\n"
                            for media in tweet_data['media']:
                                media_type = media.get('type', 'unknown')
                                if media_type == 'image':
                                    media_section += f"![图片]({media.get('url')})\n"
                                elif media_type == 'video':
                                    media_section += f"🎬 [视频链接]({media.get('url')})\n"
                                elif media_type == 'gif':
                                    media_section += f"🎞️ [GIF]({media.get('url')})\n"
                        
                        # 构建推送内容
                        title = f"【{name}】{'[仅媒体]' if not tweet_data.get('text') else tweet_data['text'][:50]}"
                        content = (
                            "###  ⚠️ 翻译失败\n\n"
                            "### ℹ️ 详细信息\n\n"
                            f"- **📅 发布时间**: {tweet_data.get('time','未知')}\n"
                            f"- **📅 发布日期**: {tweet_data.get('formatted_time','-')}\n"
                            f"- **🔗 原文链接**: [点击查看]({tweet_data.get('url', '#')})\n"
                            f"- **📌 推文ID**: `{tweet_data.get('id', 'unknown')}`\n\n"
                            f"### 📝 原文\n\n"
                            f"{tweet_data.get('text', '无文字内容')}"
                            f"{media_section}"
                            f"{screenshot_section}"
                        )
                        
                        # 推送消息并标记为已发送
                        if self.push_queue.push(title, content):
                            self.archiver.mark_as_sent(tweet_data['id'])
                            logging.info(f"无需翻译的推文处理完成: {tweet_data['id']}")
                        return
                    
                    # 存档翻译结果
                    self.archiver.archive_translation(tweet_data, analysis)
                    
                    # 推送消息并记录状态
                    push_success = self.push_tweet(tweet_data, analysis)
                    # 无论推送成功与否，都记录为已处理
                    self.archiver.mark_as_sent(tweet_data['id'])
                    
                    if push_success:
                        logging.info(f"推文处理完成: {tweet['id']}")
                    else:
                        logging.error(f"推文推送失败: {tweet['id']}")
                    
                except requests.exceptions.RequestException as e:
                    logging.error(f"请求 {name} 的推文时网络错误: {str(e)}")
                    continue
                except ValueError as e:
                    logging.error(f"解析 {name} 的推文时出错: {str(e)}")
                    continue
                except Exception as e:
                    logging.error(f"处理 {name} 的推文时出现未知错误: {str(e)}", exc_info=True)
                    continue
                finally:
                    # 无论是否成功，都等待一段随机时间再处理下一个用户
                    time.sleep(random.uniform(1, 3))
            
        except Exception as e:
            logging.error(f"处理 {name} 的推文时出现错误: {str(e)}", exc_info=True)
        finally:
            time.sleep(random.uniform(1, 3)) 