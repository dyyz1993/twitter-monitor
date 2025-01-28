import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Set, List

class Archiver:
    def __init__(self, config):
        self.config = config
        self.sent_ids: Set[str] = set()
        self.max_cache_size = int(self.config.env_vars.get('MAX_CACHE_SIZE', 1000))
        self.raw_tweets_file = os.path.join(self.config.archive_dir, "raw_tweets.jsonl")
        self.translated_tweets_file = os.path.join(self.config.archive_dir, "translated_tweets.jsonl")
        self.load_sent_tweets()

    def load_sent_tweets(self) -> List[str]:
        """加载已发送的推文ID列表"""
        try:
            cache_file = os.path.join(self.config.archive_dir, 'sent_tweets.json')
            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    sent_tweets = json.load(f)
                    # 确保返回列表
                    if not isinstance(sent_tweets, list):
                        logging.warning(f"sent_tweets.json 格式错误，重置为空列表")
                        return []
                    return sent_tweets
            else:
                logging.info("未找到已发送推文记录，创建新文件")
                return []
        except Exception as e:
            logging.error(f"加载已发送推文记录失败: {str(e)}")
            return []  # 出错时返回空列表而不是 None

    def save_sent_tweets(self):
        """保存已发送的推文ID"""
        try:
            cache_file = os.path.join(self.config.archive_dir, 'sent_tweets.json')
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(list(self.sent_ids), f)
        except Exception as e:
            logging.error(f"保存已发送推文记录失败: {str(e)}")

    def is_tweet_sent(self, tweet_id: str) -> bool:
        """检查推文是否已发送"""
        if not tweet_id:
            logging.error("传入的推文ID为空")
            return False
        return tweet_id in self.sent_ids

    def archive_tweet(self, tweet: Dict):
        """存档推文"""
        try:
            if not tweet.get('id'):
                logging.error("无法存档缺少ID的推文")
                return
            
            # 添加存档时间
            tweet['archived_at'] = datetime.now(self.config.timezone).isoformat()
            
            # 存档原始推文
            raw_file = os.path.join(self.config.archive_dir, 'raw_tweets.jsonl')
            with open(raw_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(tweet, ensure_ascii=False) + '\n')
            
            # 记录已发送
            self.sent_ids.add(tweet['id'])
            if len(self.sent_ids) > self.max_cache_size:
                self.sent_ids.pop()
            
            # 保存缓存
            self.save_sent_tweets()
            
        except Exception as e:
            logging.error(f"存档推文失败: {str(e)}")

    def archive_translation(self, tweet_data: Dict, analysis_result: str):
        """存档翻译结果"""
        try:
            translation_data = {
                'tweet_id': tweet_data['id'],
                'username': tweet_data['username'],
                'name': tweet_data['name'],
                'original_text': tweet_data['text'],
                'translation': self.extract_section(analysis_result, "中文翻译"),
                'summary': self.extract_section(analysis_result, "内容概要"),
                'tags': self.extract_section(analysis_result, "关键标签"),
                'hints': self.extract_section(analysis_result, "重点提示"),
                'full_analysis': analysis_result,
                'time': tweet_data['time'],
                'parsed_time': tweet_data.get('parsed_time'),
                'url': tweet_data['url'],
                'is_retweet': tweet_data.get('is_retweet', False),
                'is_quote': tweet_data.get('is_quote', False),
                'archived_at': datetime.now(self.config.timezone).isoformat()
            }
            
            with open(self.translated_tweets_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(translation_data, ensure_ascii=False) + '\n')
                
            logging.info(f"已存档翻译到 {self.translated_tweets_file}")
            return translation_data['summary'] or tweet_data['text'][:50] + "..."
            
        except Exception as e:
            logging.error(f"存档翻译时出错: {str(e)}")
            return tweet_data['text'][:50] + "..."

    def extract_section(self, text: str, section_name: str) -> str:
        """提取指定部分的内容"""
        try:
            if not text:
                return ""
                
            start_marker = f"【{section_name}】"
            start_idx = text.find(start_marker)
            if start_idx == -1:
                return ""
            
            content_start = start_idx + len(start_marker)
            next_marker = text.find("【", content_start)
            
            if next_marker == -1:
                content = text[content_start:].strip()
            else:
                content = text[content_start:next_marker].strip()
            
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            return '\n'.join(lines)
            
        except Exception as e:
            logging.error(f"提取{section_name}时出错: {str(e)}")
            return ""

    def get_recent_tweets(self, minutes: int = 30) -> List[Dict]:
        """获取最近的推文记录"""
        try:
            recent_tweets = []
            now = datetime.now(self.config.timezone)
            cutoff_time = now - timedelta(minutes=minutes)
            
            with open(self.raw_tweets_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        tweet = json.loads(line)
                        archived_time = datetime.fromisoformat(tweet['archived_at'])
                        if archived_time > cutoff_time:
                            recent_tweets.append(tweet)
                    except Exception as e:
                        logging.error(f"解析推文记录时出错: {str(e)}")
                        continue
                    
            return recent_tweets
            
        except FileNotFoundError:
            logging.warning(f"推文记录文件不存在: {self.raw_tweets_file}")
            return []
        except Exception as e:
            logging.error(f"获取最近推文记录时出错: {str(e)}")
            return []

    def archive_raw_tweet(self, tweet: Dict):
        """存档原始推文（不标记为已发送）"""
        try:
            if not tweet.get('id'):
                logging.error("无法存档缺少ID的推文")
                return
            
            # 添加存档时间
            tweet['archived_at'] = datetime.now(self.config.timezone).isoformat()
            
            # 存档原始推文
            with open(self.raw_tweets_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(tweet, ensure_ascii=False) + '\n')
            
        except Exception as e:
            logging.error(f"存档原始推文失败: {str(e)}")

    def mark_as_sent(self, tweet_id: str) -> None:
        """标记推文为已发送"""
        if not tweet_id:
            return
        
        try:
            sent_tweets = self.load_sent_tweets()
            if tweet_id not in sent_tweets:
                sent_tweets.append(tweet_id)
                # 保存到文件
                cache_file = os.path.join(self.config.archive_dir, 'sent_tweets.json')
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(sent_tweets, f, indent=2)
                logging.debug(f"已标记推文为已发送: {tweet_id}")
        except Exception as e:
            logging.error(f"标记推文为已发送时出错: {str(e)}")

    def is_sent(self, tweet_id: str) -> bool:
        """检查推文是否已发送"""
        if not tweet_id:
            return False
        
        try:
            sent_tweets = self.load_sent_tweets()
            # 确保 sent_tweets 是列表
            if not isinstance(sent_tweets, list):
                logging.error("已发送推文记录格式错误")
                return False
            return tweet_id in sent_tweets
        except Exception as e:
            logging.error(f"检查推文发送状态时出错: {str(e)}")
            return False