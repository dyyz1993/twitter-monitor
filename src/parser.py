from bs4 import BeautifulSoup
from datetime import datetime
import logging
from typing import List, Dict, Optional

class TweetParser:
    def __init__(self, config):
        self.config = config
        
    def parse_tweets(self, html_content: str) -> List[Dict]:
        """解析推文内容"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            timeline_items = soup.select('.timeline-item')
            tweets = []
            
            for item in timeline_items:
                try:
                    # 获取推文链接和ID
                    tweet_link = item.select_one('.tweet-link')
                    if not tweet_link:
                        continue
                        
                    tweet_url = tweet_link.get('href', '')
                    # 从URL中提取ID并清理特殊字符
                    raw_id = tweet_url.split('/')[-1]
                    tweet_id = raw_id.split('#')[0].split('?')[0]  # 移除#和?后的内容
                    
                    # 构造完整的推文URL
                    tweet_url = f"https://twitter.com{tweet_url}"  # 添加域名
                    
                    logging.debug(f"解析到推文ID: {tweet_id} (原始ID: {raw_id})")
                    
                    # 解析基本信息
                    content = item.select_one('.tweet-content')
                    tweet_text = content.get_text(strip=True) if content else ""
                    time_elem = item.select_one('.tweet-date')
                    tweet_time = time_elem.get_text(strip=True) if time_elem else ""
                    formatted_time = time_elem.get('href', '') if time_elem else ""
                    url = formatted_time if formatted_time else ""
                    
                    # 检查推文类型
                    retweet_header = item.select_one('.retweet-header')
                    quote = item.select_one('.quote')
                    
                    is_retweet = bool(retweet_header)
                    is_quote = bool(quote)
                    
                    # 解析引用内容
                    quote_text = None
                    quote_author = None
                    if is_quote and quote:
                        quote_text_elem = quote.select_one('.quote-text')
                        quote_text = quote_text_elem.get_text(strip=True) if quote_text_elem else None
                        
                        quote_author_elem = quote.select_one('.fullname')
                        quote_author = quote_author_elem.get_text(strip=True) if quote_author_elem else None
                    
                    # 获取用户名
                    username = ''
                    username_element = item.find('a', class_='username')
                    if username_element:
                        username = username_element.get_text().strip('@')
                    
                    # 获取媒体和链接
                    media_items = []
                    links = []
                    
                    # 解析媒体
                    for media in item.select('.tweet-media'):
                        media_url = media.get('src', '')
                        if media_url:
                            media_items.append({
                                'type': 'image',  # 或根据实际情况判断类型
                                'url': media_url
                            })
                    
                    # 解析链接
                    for link in item.select('.tweet-link'):
                        link_url = link.get('href', '')
                        if link_url:
                            links.append({
                                'url': link_url,
                                'title': link.get_text(strip=True) or link_url
                            })
                    
                    # 获取推文作者
                    name = ''
                    name_element = item.find('a', class_='name')
                    if name_element:
                        name = name_element.get_text(strip=True)
                    
                    # 获取推文作者
                    retweet_author = ''
                    retweet_author_element = item.select_one('.retweet-author')
                    if retweet_author_element:
                        retweet_author = retweet_author_element.get_text(strip=True)
                    
                    # 返回解析结果
                    tweet_data = {
                        'id': tweet_id,
                        'url': tweet_url,  # 使用构造的完整URL
                        'name': name,
                        'username': username,
                        'time': tweet_time,
                        'formatted_time': formatted_time,
                        'text': tweet_text,
                        'media': media_items,
                        'links': links,
                        'is_retweet': is_retweet,
                        'retweet_author': retweet_author,
                        'is_quote': is_quote,
                        'quote_text': quote_text,
                        'quote_author': quote_author
                    }
                    tweets.append(tweet_data)
                    
                except Exception as e:
                    logging.error(f"解析单条推文时出错: {str(e)}")
                    continue
                
            return tweets
            
        except Exception as e:
            logging.error(f"解析推文内容时出错: {str(e)}")
            return []
        
    def _parse_tweet(self, tweet_element) -> Optional[Dict]:
        """解析单条推文"""
        try:
            # 获取推文ID
            tweet_link = tweet_element.select_one('.tweet-link')
            if not tweet_link:
                logging.warning("未找到推文链接元素")
                return None
            
            tweet_url = tweet_link.get('href', '')
            # 从URL中提取ID并清理特殊字符
            raw_id = tweet_url.split('/')[-1]
            tweet_id = raw_id.split('#')[0].split('?')[0]  # 移除#和?后的内容
            if not tweet_id:
                logging.warning("无法从URL中提取推文ID")
                return None
            
            logging.debug(f"解析到推文ID: {tweet_id} (原始ID: {raw_id})")
            
            # 解析基本信息
            content = tweet_element.select_one('.tweet-content')
            text = content.get_text(strip=True) if content else ""
            time_elem = tweet_element.select_one('.tweet-date')
            time_str = time_elem.get_text(strip=True) if time_elem else ""
            url = time_elem.get('href', '') if time_elem else ""
            
            # 检查推文类型
            retweet_header = tweet_element.select_one('.retweet-header')
            quote = tweet_element.select_one('.quote')
            
            is_retweet = bool(retweet_header)
            is_quote = bool(quote)
            
            # 解析引用内容
            quote_text = None
            quote_author = None
            if is_quote and quote:
                quote_text_elem = quote.select_one('.quote-text')
                quote_text = quote_text_elem.get_text(strip=True) if quote_text_elem else None
                
                quote_author_elem = quote.select_one('.fullname')
                quote_author = quote_author_elem.get_text(strip=True) if quote_author_elem else None
            
            # 获取用户名
            username = ''
            username_element = tweet_element.find('a', class_='username')
            if username_element:
                username = username_element.get_text().strip('@')
            
            # 返回解析结果
            return {
                'id': tweet_id,
                'username': username,  # 添加用户名字段
                'text': text,
                'time': time_str,
                'url': url,
                'is_retweet': is_retweet,
                'is_quote': is_quote,
                'quote_text': quote_text,
                'quote_author': quote_author
            }
            
        except Exception as e:
            logging.error(f"解析单条推文时出错: {str(e)}")
            return None 