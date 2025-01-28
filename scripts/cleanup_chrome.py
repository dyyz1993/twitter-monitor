#!/usr/bin/env python3
import os
import json
import requests
import logging
from typing import List

def get_chrome_sessions(host: str = '192.168.0.29', port: int = 19223) -> List[str]:
    """获取所有 Chrome 会话"""
    try:
        response = requests.get(f'http://{host}:{port}/json')
        if response.status_code == 200:
            return [session['id'] for session in response.json()]
        return []
    except Exception as e:
        logging.error(f"获取 Chrome 会话失败: {str(e)}")
        return []

def close_session(session_id: str, host: str = '192.168.0.29', port: int = 19223):
    """关闭指定会话"""
    try:
        response = requests.get(f'http://{host}:{port}/json/close/{session_id}')
        if response.status_code == 200:
            logging.info(f"成功关闭会话: {session_id}")
        else:
            logging.warning(f"关闭会话失败: {session_id}")
    except Exception as e:
        logging.error(f"关闭会话出错: {str(e)}")

def cleanup():
    """清理所有 Chrome 会话"""
    sessions = get_chrome_sessions()
    for session_id in sessions:
        close_session(session_id)
    
    if sessions:
        logging.info(f"已清理 {len(sessions)} 个 Chrome 会话")
    else:
        logging.info("没有需要清理的 Chrome 会话")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    cleanup() 