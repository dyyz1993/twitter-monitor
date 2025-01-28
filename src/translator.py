import logging
import json
import requests
from typing import Dict, Optional

class Translator:
    def __init__(self, config):
        self.config = config
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.config.deepseek_key}'
        }

    def analyze_tweet(self, tweet: Dict) -> Optional[str]:
        """分析推文内容"""
        try:
            # 验证输入
            text = tweet.get('text', '').strip()
            if not text:
                logging.info("推文没有文字内容，跳过翻译")
                return None
            
            # 检查是否只包含媒体链接
            cleaned_text = text
            
            # 处理媒体链接
            for media in tweet.get('media', []):
                if isinstance(media, dict):  # 确保 media 是字典类型
                    media_url = media.get('url', '')
                    if media_url:
                        cleaned_text = cleaned_text.replace(media_url, '').strip()
            
            # 处理普通链接
            for link in tweet.get('links', []):
                if isinstance(link, dict):  # 确保 link 是字典类型
                    link_url = link.get('url', '')
                    if link_url:
                        cleaned_text = cleaned_text.replace(link_url, '').strip()
                elif isinstance(link, str):  # 如果 link 直接是字符串
                    cleaned_text = cleaned_text.replace(link, '').strip()
            
            if not cleaned_text:
                logging.info("推文仅包含媒体/链接，跳过翻译")
                return None
            
            # 构建完整的文本
            full_text = cleaned_text
            if tweet.get('is_quote') and tweet.get('quote_text'):
                full_text += f"\n\n引用内容：\n{tweet['quote_text']}"
                if tweet.get('quote_author'):
                    full_text += f"\n作者：{tweet['quote_author']}"
            
            # 构建请求数据
            data = {
                'model': 'deepseek-chat',
                'messages': [
                    {'role': 'system', 'content': self.config.system_prompt},
                    {'role': 'user', 'content': self.config.user_prompt.format(text=full_text)}
                ],
                'temperature': 0.7,
                'max_tokens': 2000
            }
            
            logging.debug(f"API请求数据: {json.dumps(data, ensure_ascii=False)}")
            
            # 发送请求
            response = requests.post(
                self.config.deepseek_url,
                headers=self.headers,
                json=data,
                timeout=30,
                proxies=self.config.proxies
            )
            
            # 详细记录响应信息
            logging.debug(f"API响应状态码: {response.status_code}")
            logging.debug(f"API响应头: {dict(response.headers)}")
            logging.debug(f"API响应内容: {response.text}")
            
            response.raise_for_status()
            result = response.json()
            
            if not result.get('choices') or not result['choices'][0].get('message', {}).get('content'):
                logging.error(f"API返回格式异常: {json.dumps(result, ensure_ascii=False, indent=2)}")
                return None
            
            analysis = result['choices'][0]['message']['content']
            logging.info(f"API返回分析结果: {analysis}")
            
            # 验证返回结果格式
            required_sections = ["中文翻译", "内容概要", "关键标签", "重点提示"]
            for section in required_sections:
                if f"【{section}】" not in analysis:
                    logging.error(f"API返回结果缺少必要部分【{section}】，完整返回：{analysis}")
                    return None
            
            return analysis
            
        except requests.exceptions.RequestException as e:
            logging.error(f"API请求异常: {str(e)}")
            logging.error(f"请求URL: {self.config.deepseek_url}")
            logging.error(f"请求头: {self.headers}")
            logging.error(f"请求数据: {json.dumps(data, ensure_ascii=False)}")
            return None
        except Exception as e:
            logging.error(f"分析推文时出错: {str(e)}", exc_info=True)
            return None

    def extract_section(self, analysis: str, section: str) -> str:
        """从分析结果中提取指定部分"""
        try:
            if not analysis:
                return ""
            
            start = analysis.find(f"【{section}】")
            if start == -1:
                return ""
            
            start += len(f"【{section}】")
            end = analysis.find("【", start)
            
            if end == -1:
                text = analysis[start:].strip()
            else:
                text = analysis[start:end].strip()
            
            # 规范化文本格式
            lines = text.split('\n')
            return '\n'.join(line.strip() for line in lines if line.strip())
            
        except Exception as e:
            logging.error(f"提取{section}时出错: {str(e)}")
            return "" 