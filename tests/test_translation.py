import pytest
import os
from src.config import Config
from src.translator import Translator
from typing import Dict
import logging
import time

# 设置日志配置
def setup_logging():
    # 创建logs目录（如果不存在）
    if not os.path.exists('logs'):
        os.makedirs('logs')
        
    # 配置日志格式
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    
    # 创建文件处理器
    file_handler = logging.FileHandler('logs/test_translation.log', encoding='utf-8')
    file_handler.setFormatter(logging.Formatter(log_format))
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))
    
    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

# 初始化日志
setup_logging()

@pytest.fixture
def config():
    """创建测试配置"""
    return Config()

@pytest.fixture
def translator(config):
    """创建翻译器实例"""
    return Translator(config)

def test_analyze_tweet_basic(translator):
    """测试基本的推文分析"""
    tweet = {
        'id': '1882135630182043738#m',
        'text': '𝕏 is the #1 app for over 140 countries.\n\nNo other media or platform has the reach of 𝕏.',
        'time': '1h',
        'is_retweet': False,
        'is_quote': False
    }
    
    # 打印配置信息
    logging.info("=== 配置信息 ===")
    logging.info(f"API URL: {translator.config.deepseek_url}")
    logging.info(f"Headers: {translator.headers}")
    logging.info(f"Proxies: {translator.config.proxies}")
    
    # 打印系统提示词
    logging.info("=== 提示词 ===")
    logging.info(f"System Prompt: {translator.config.system_prompt}")
    logging.info(f"User Prompt Template: {translator.config.user_prompt}")
    
    result = translator.analyze_tweet(tweet)
    assert result is not None, "分析结果不应该为空"
    
    # 验证必要的部分是否存在
    sections = ["中文翻译", "内容概要", "关键标签", "重点提示"]
    for section in sections:
        content = translator.extract_section(result, section)
        assert content, f"缺少【{section}】部分"
        logging.info(f"【{section}】: {content}")

def test_analyze_tweet_with_special_content(translator):
    """测试特殊内容的推文分析"""
    test_cases = [
        {
            'name': '加密货币相关',
            'text': 'Bitcoin price reaches $50,000!',
            'expected_mark': '💰'
        },
        {
            'name': '太空探索相关',
            'text': 'Starship successfully completed its orbital flight test',
            'expected_mark': '🚀'
        },
        {
            'name': 'AI相关',
            'text': 'Our new AI model achieves state-of-the-art performance',
            'expected_mark': '🤖'
        },
        {
            'name': '重要政策',
            'text': 'New policy announcement: major changes in regulation',
            'expected_mark': '💊'
        }
    ]
    
    for case in test_cases:
        tweet = {
            'id': f'test_{case["name"]}',
            'text': case['text'],
            'time': '1h',
            'is_retweet': False,
            'is_quote': False
        }
        
        result = translator.analyze_tweet(tweet)
        assert result is not None, f"{case['name']}分析失败"
        hints = translator.extract_section(result, "重点提示")
        assert case['expected_mark'] in hints, f"{case['name']}未能正确识别标记"
        logging.info(f"测试用例 {case['name']} 通过")
        logging.info(f"分析结果:\n{result}")
        
        # 避免API限流
        time.sleep(1)

def test_analyze_tweet_with_quote(translator):
    """测试带引用的推文分析"""
    tweet = {
        'id': 'test_quote',
        'text': 'Commenting on this',
        'quote_text': 'Original tweet content',
        'quote_author': 'original_author',
        'time': '2h',
        'is_retweet': False,
        'is_quote': True
    }
    
    result = translator.analyze_tweet(tweet)
    assert result is not None
    assert "引用" in translator.extract_section(result, "内容概要")
    logging.info(f"分析结果:\n{result}")

def test_error_handling(translator):
    """测试错误处理"""
    # 测试空文本
    empty_tweet = {
        'id': 'empty',
        'text': '',
        'time': '1h'
    }
    result = translator.analyze_tweet(empty_tweet)
    assert result is None or result.strip(), "空文本应该返回None或非空结果"
    
    # 测试缺少必要字段
    invalid_tweet = {'id': 'invalid'}
    result = translator.analyze_tweet(invalid_tweet)
    assert result is None, "无效推文应该返回None"

def test_extract_section(translator):
    """测试部分提取功能"""
    test_analysis = """
    【中文翻译】
    测试文本
    【内容概要】
    这是概要
    【关键标签】
    标签1, 标签2
    【重点提示】
    - 内容标记：🚀
    - 重要数据：无
    """
    
    sections = {
        "中文翻译": "测试文本",
        "内容概要": "这是概要",
        "关键标签": "标签1, 标签2",
        "重点提示": "- 内容标记：🚀\n- 重要数据：无"
    }
    
    for section, expected in sections.items():
        content = translator.extract_section(test_analysis, section)
        assert content.strip() == expected.strip(), f"{section}提取错误"

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"]) 