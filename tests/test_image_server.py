import os
import sys
import logging
import asyncio
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = str(Path(__file__).parent.parent)
sys.path.insert(0, project_root)

from src.image_server import ImageServer

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def main():
    # 设置测试环境
    screenshots_dir = os.path.join(project_root, 'data', 'screenshots')
    os.makedirs(screenshots_dir, exist_ok=True)
    
    # 创建测试图片
    test_image_path = os.path.join(screenshots_dir, 'test.png')
    if not os.path.exists(test_image_path):
        # 创建一个简单的测试图片
        with open(test_image_path, 'wb') as f:
            f.write(b'PNG\r\n\x1a\n')  # 简单的 PNG 文件头
    
    # 创建并启动图片服务器
    server = ImageServer(
        screenshots_dir=screenshots_dir,
        port=3005
    )
    
    logging.info(f"测试环境准备完成:")
    logging.info(f"- 截图目录: {screenshots_dir}")
    logging.info(f"- 测试图片: {test_image_path}")
    
    try:
        # 启动服务器
        server.start()
        logging.info("图片服务器已启动，按 Ctrl+C 停止...")
        
        # 保持程序运行
        while True:
            try:
                asyncio.get_event_loop().run_forever()
            except KeyboardInterrupt:
                break
            
    except Exception as e:
        logging.error(f"运行图片服务器时出错: {str(e)}")
    finally:
        logging.info("图片服务器已停止")

if __name__ == '__main__':
    main() 