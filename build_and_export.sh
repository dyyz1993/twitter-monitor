#!/bin/bash

# 设置变量
IMAGE_NAME="twitter-monitor"
IMAGE_TAG="latest"
PLATFORM="linux/amd64"
EXPORT_FILE="${IMAGE_NAME}_${IMAGE_TAG}_amd64.tar"

# 输出彩色信息的函数
print_info() {
    echo -e "\033[1;34m[INFO]\033[0m $1"
}

print_success() {
    echo -e "\033[1;32m[SUCCESS]\033[0m $1"
}

print_error() {
    echo -e "\033[1;31m[ERROR]\033[0m $1"
}

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    print_error "Docker 未安装！"
    exit 1
fi

# 开始构建
print_info "开始构建 ${IMAGE_NAME}:${IMAGE_TAG} (${PLATFORM})..."

# 使用 BuildKit 构建指定平台的镜像
if docker buildx build \
    --platform ${PLATFORM} \
    --load \
    -t ${IMAGE_NAME}:${IMAGE_TAG} \
    .; then
    print_success "镜像构建成功！"
else
    print_error "镜像构建失败！"
    exit 1
fi

# 导出镜像
print_info "正在导出镜像到 ${EXPORT_FILE}..."

if docker save -o ${EXPORT_FILE} ${IMAGE_NAME}:${IMAGE_TAG}; then
    print_success "镜像导出成功！"
    print_info "文件位置: $(pwd)/${EXPORT_FILE}"
    print_info "文件大小: $(ls -lh ${EXPORT_FILE} | awk '{print $5}')"
else
    print_error "镜像导出失败！"
    exit 1
fi

# 显示导出的镜像信息
print_info "镜像信息:"
docker images ${IMAGE_NAME}:${IMAGE_TAG} --format "ID: {{.ID}}\nSize: {{.Size}}\nCreated: {{.CreatedSince}}" 