#!/usr/bin/env python3
import os
import sys

def main():
    # 确保能够导入 src 模块
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    
    # 直接从 __main__.py 导入
    from src.__main__ import main
    main()

if __name__ == "__main__":
    main() 