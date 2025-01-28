import os
import json
import time
import logging
import requests
import random
from typing import List, Dict, Set, Optional
import re
import asyncio
from src.chrome_fetcher import ChromeFetcher

class InstanceManager:
    def __init__(self, archive_dir: str, proxies: Dict = None):
        self.archive_dir = archive_dir
        self.proxies = proxies
        self.instance_health_file = os.path.join(archive_dir, 'instance_health.json')
        self.last_used = {}  # 记录每个实例的最后使用时间
        self.cooldown_time = 10  # 冷却时间（秒）
        self.last_update = 0  # 记录上次更新实例列表的时间
        self.update_interval = 24 * 3600  # 更新间隔（24小时）
        self.instance_reuse_interval = 20  # 同一实例重用的最小间隔（秒）
        
        # 默认实例列表
        self.default_instances = [
            'https://xcancel.com',
            'https://nitter.poast.org',
            'https://lightbrd.com',
            'https://nitter.poast.org',
            'https://nitter.kavin.rocks',
        ]
        
        # 初始化实例集合和状态
        self.instances: Set[str] = set(self.default_instances)
        self.instance_status: Dict = {}
        
        # 加载实例健康状态
        self.load_instance_health()
        # 更新实例列表
        self.update_instances()
        
    def update_instances(self) -> None:
        """更新 Nitter 实例列表"""
        self.instances = set(self.default_instances)  # 使用集合去重
        
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'user-agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15'
        }
        
        try:
            response = requests.get(
                'https://raw.githubusercontent.com/wiki/zedeus/nitter/Instances.md',
                headers=headers,
                timeout=200,
                proxies=self.proxies
            )
            
            if response.status_code == 200:
                content = response.text
                
                # 使用正则表达式匹配有效实例
                # 匹配格式: [...](https://...) | :white_check_mark: | ✅
                pattern = r'\[(.*?)\]\((https?://[^)]+)\)[^\n]*\|\s*:white_check_mark:\s*\|\s*✅'
                matches = re.finditer(pattern, content)
                
                online_instances = []
                for match in matches:
                    instance_url = match.group(2)
                    if instance_url.startswith(('http://', 'https://')):
                        # 如果尾部 /，则去掉
                        instance_url = instance_url.rstrip('/')
                        
                        online_instances.append(instance_url)
                        logging.debug(f"找到可用实例: {instance_url}")
                
                if online_instances:
                    old_count = len(self.instances)
                    self.instances.update(online_instances)
                    new_count = len(self.instances)
                    logging.info(
                        f"实例列表更新完成: "
                        f"原有 {old_count} 个, "
                        f"新增 {new_count - old_count} 个, "
                        f"总计 {new_count} 个\n"
                        f"新增实例: {set(online_instances) - set(self.default_instances)}"
                    )
                else:
                    logging.warning("未找到可用实例，保持使用现有实例")
                    logging.debug(f"原始内容:\n{content[:500]}")
            else:
                logging.warning(f"获取实例列表失败 ({response.status_code})，保持使用现有实例")
                
        except Exception as e:
            logging.error(f"更新 Nitter 实例失败: {str(e)}，保持使用现有实例")
            logging.debug("错误详情:", exc_info=True)
        
        # 初始化新实例的健康状态
        self._init_new_instances()
        self._log_instance_status()
    
    def _init_new_instances(self) -> None:
        """初始化新实例的健康状态"""
        now = time.time()
        for instance in self.instances:
            if instance not in self.instance_status:
                self.instance_status[instance] = {
                    'success_count': 0,
                    'fail_count': 0,
                    'last_success': None,
                    'last_failure': None,
                    'health_score': 100,
                    'cooldown_until': 0,
                    'last_update': now
                }
    
    def _log_instance_status(self) -> None:
        """记录实例池状态"""
        logging.info(f"实例池状态:")
        logging.info(f"- 默认实例: {len(self.default_instances)} 个")
        logging.info(f"- 总实例数: {len(self.instances)} 个")
        logging.info("- 健康度TOP5:")
        
        for instance in self.get_top_instances(5):
            score = self.instance_status[instance]['health_score']
            logging.info(f"  - {instance}: {score}")
    
    def get_top_instances(self, limit: int = 5) -> List[str]:
        """获取健康度最高的实例"""
        return sorted(
            self.instances,
            key=lambda x: self.instance_status.get(x, {}).get('health_score', 0),
            reverse=True
        )[:limit]
    
    def select_instance(self) -> Optional[str]:
        """选择一个可用的实例"""
        try:
            now = time.time()
            
            # 获取所有可用实例
            available_instances = []
            for instance in self.default_instances:
                status = self.instance_status.get(instance, {})
                
                # 跳过冷却中的实例
                if status.get('cooldown_until', 0) > now:
                    logging.debug(f"实例 {instance} 在冷却中，剩余 {(status['cooldown_until'] - now)/60:.1f} 分钟")
                    continue
                    
                # 跳过健康度为0的实例
                if status.get('health_score', 100) <= 0:
                    logging.debug(f"实例 {instance} 健康度为 0")
                    continue
                    
                # 检查重用时间间隔
                last_used = self.last_used.get(instance, 0)
                if now - last_used < self.instance_reuse_interval:
                    logging.debug(f"实例 {instance} 重用间隔不足，还需等待 {self.instance_reuse_interval - (now - last_used):.1f} 秒")
                    continue
                    
                available_instances.append(instance)
            
            if not available_instances:
                # 添加更详细的日志
                for instance in self.default_instances:
                    status = self.instance_status.get(instance, {})
                    logging.info(
                        f"实例 {instance} 状态:\n"
                        f"- 健康度: {status.get('health_score', 100)}\n"
                        f"- 冷却时间: {(status.get('cooldown_until', 0) - now)/60:.1f} 分钟\n"
                        f"- 上次使用: {(now - self.last_used.get(instance, 0)):.1f} 秒前\n"
                        f"- 成功次数: {status.get('success_count', 0)}\n"
                        f"- 失败次数: {status.get('fail_count', 0)}"
                    )
                logging.error("没有可用的实例")
                return None
                
            # 使用评分算法选择最佳实例
            selected = self._get_best_instance(available_instances, now)
            if selected is None:
                logging.warning("无法选择合适的实例，等待重用冷却")
                return None
                
            return selected
            
        except Exception as e:
            logging.error(f"选择实例时出错: {str(e)}")
            return None
    
    def _update_instance_status(self, now: float) -> None:
        """更新实例状态"""
        for status in self.instance_status.values():
            if status['cooldown_until'] <= now:
                status['cooldown_until'] = 0
                status['fail_count'] = 0
                if now - status.get('last_update', 0) > 3600:
                    status['health_score'] = min(100, status['health_score'] + 2)
                    status['last_update'] = now
                    self.save_instance_health()
    
    def _get_best_instance(self, available_instances: List[str], now: float) -> str:
        """获取最佳实例"""
        def get_instance_score(instance: str) -> float:
            status = self.instance_status[instance]
            health_score = status['health_score']
            
            # 检查实例重用时间间隔
            last_used = self.last_used.get(instance, 0)
            time_since_last_use = now - last_used
            
            # 如果距离上次使用不足20秒，显著降低评分
            if time_since_last_use < self.instance_reuse_interval:
                return -1  # 返回负分，确保不会被选中
            
            # 原有评分逻辑
            time_factor = min(100, (time_since_last_use / 300))
            success_rate = (status['success_count'] / (status['success_count'] + status['fail_count'])) * 100 if (status['success_count'] + status['fail_count']) > 0 else 50
            return (health_score * 0.5) + (time_factor * 0.3) + (success_rate * 0.2)
        
        sorted_instances = sorted(
            available_instances,
            key=get_instance_score,
            reverse=True
        )
        
        # 如果最高分是负数，说明所有实例都在冷却中
        if get_instance_score(sorted_instances[0]) < 0:
            logging.warning("所有可用实例都在重用冷却期内")
            return None
            
        selected = sorted_instances[0]
        self.last_used[selected] = now
        
        logging.info(
            f"选择实例 {selected} "
            f"(健康度: {self.instance_status[selected]['health_score']}, "
            f"距上次使用: {now - self.last_used.get(selected, 0):.1f}秒)"
        )
        
        return selected
    
    def _log_selected_instance(self, instance: str, now: float) -> None:
        """记录选中的实例信息"""
        status = self.instance_status[instance]
        health_score = status['health_score']
        time_since_last_use = now - status.get('last_update', now)
        
        logging.info(
            f"选择实例: {instance} "
            f"(健康度: {health_score:.1f}, "
            f"距上次使用: {time_since_last_use/60:.1f}分钟)"
        )
        
        top5_info = [
            (i, self.instance_status[i]['health_score'],
             (now - self.instance_status[i].get('last_update', now)) / 60)
            for i in self.get_top_instances(5)
        ]
        logging.debug(
            "当前可用实例TOP5: " + 
            ", ".join([
                f"{i}({score:.1f}, {last_use:.1f}min)"
                for i, score, last_use in top5_info
            ])
        )
    
    def update_health(self, instance: str, success: bool) -> None:
        """更新实例健康状态"""
        now = time.time()
        status = self.instance_status.get(instance, {
            'success_count': 0,
            'fail_count': 0,
            'last_success': None,
            'last_failure': None,
            'health_score': 100,
            'cooldown_until': 0,
            'last_update': now
        })
        
        if success:
            status['success_count'] += 1
            status['last_success'] = now
            status['health_score'] = min(100, status['health_score'] + 5)
            status['fail_count'] = 0  # 重置失败计数
            status['cooldown_until'] = 0  # 成功时清除冷却时间
            logging.info(f"实例 {instance} 成功，健康度提升到 {status['health_score']}")
        else:
            status['fail_count'] += 1
            status['last_failure'] = now
            
            # 检查24小时内是否有成功记录
            had_recent_success = (
                status['last_success'] is not None and 
                now - status['last_success'] < 24 * 3600
            )
            
            # 调整健康度惩罚
            if had_recent_success:
                # 24小时内有成功记录，健康度降低更温和
                status['health_score'] = max(50, status['health_score'] - 10)
                cooldown_time = min(60, 10 * status['fail_count'])
            else:
                # 24小时内无成功记录，健康度降低更严重
                status['health_score'] = max(20, status['health_score'] - 20)
                cooldown_time = min(3600, 60 * (2 ** (status['fail_count'] - 1)))
            
            status['cooldown_until'] = now + cooldown_time
            logging.warning(
                f"实例 {instance} 失败 (连续 {status['fail_count']} 次)，"
                f"健康度降至 {status['health_score']}，"
                f"进入冷却 {cooldown_time/60:.1f} 分钟"
            )
        
        self.instance_status[instance] = status
        self.save_instance_health()
    
    def load_instance_health(self) -> None:
        """加载实例健康度记录"""
        try:
            if os.path.exists(self.instance_health_file):
                with open(self.instance_health_file, 'r', encoding='utf-8') as f:
                    self.instance_status = json.load(f)
                logging.info(f"已加载 {len(self.instance_status)} 个实例的健康度记录")
        except Exception as e:
            logging.error(f"加载实例健康度记录失败: {str(e)}")
            self.instance_status = {}
    
    def save_instance_health(self) -> None:
        """保存实例健康度记录"""
        try:
            os.makedirs(os.path.dirname(self.instance_health_file), exist_ok=True)
            temp_file = f"{self.instance_health_file}.tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.instance_status, f, indent=2)
            os.replace(temp_file, self.instance_health_file)
        except Exception as e:
            logging.error(f"保存实例健康度记录失败: {str(e)}")
    
    def cleanup_expired(self, days: int = 7) -> None:
        """清理过期的实例状态"""
        now = time.time()
        expired_time = now - (days * 24 * 3600)
        
        for instance in list(self.instance_status.keys()):
            status = self.instance_status[instance]
            # 获取最后使用时间，使用 0 作为默认值而不是 None
            last_used = max(
                status.get('last_update', 0),
                status.get('last_success', 0),
                status.get('last_failure', 0),
                status.get('last_used', 0)  # 添加 last_used 字段
            )
            
            # 添加调试日志
            logging.debug(
                f"实例 {instance} 状态:\n"
                f"- last_update: {status.get('last_update')}\n"
                f"- last_success: {status.get('last_success')}\n"
                f"- last_failure: {status.get('last_failure')}\n"
                f"- last_used: {status.get('last_used')}\n"
                f"- 最终使用时间: {last_used}"
            )
            
            if last_used < expired_time:
                del self.instance_status[instance]
                logging.info(f"清理长期未使用的实例: {instance} (最后使用: {last_used})")