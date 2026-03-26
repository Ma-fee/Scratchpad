#!/bin/bash

# 脚本名称
SCRIPT_NAME="arena-serve"

# 默认参数
DEFAULT_CPU=8
DEFAULT_MEMORY="32Gi"
DEFAULT_GPUS=1
DEFAULT_PPU_IMAGE="acs-registry-vpc.cn-shanghai.cr.aliyuncs.com/egslingjun/inference-xpu-pytorch:25.05-v1.5.1-vllm0.8.5-torch2.6-cu126-20250604"
DEFAULT_GPU_IMAGE="irootechimages-registry-vpc.cn-shanghai.cr.aliyuncs.com/llm/vllm-openai:v0.9.0.1"
DEFAULT_GPU_MODEL="PPU810E"
DEFAULT_SERVE_MODE="kserve"

# 初始化全局变量
cpu=$DEFAULT_CPU
memory=$DEFAULT_MEMORY
# gpus=$DEFAULT_GPUS
# image=$DEFAULT_IMAGE
gpu_model=$DEFAULT_GPU_MODEL
serve_mode=$DEFAULT_SERVE_MODE
plain_mode=0
config_file=""
other_args=()
vllm_extra_args=()
name=""  # 新增：任务名

# 打印帮助信息
show_help() {
    cat << EOF
使用说明: $SCRIPT_NAME {MODEL} [选项] [-- vLLM参数...]

启动vLLM服务的Arena部署脚本。

模型路径:
  必须提供的第一个参数为模型路径

选项:
  -c, --cpu CPU               指定CPU核心数量 (默认: $DEFAULT_CPU)
  -m, --memory MEMORY         指定内存大小 (默认: $DEFAULT_MEMORY)
  -g, --gpus GPUS             指定GPU数量 
  -i, --image IMAGE           指定Docker镜像 (默认: $DEFAULT_IMAGE)
  -gm,--gpu-model MODEL       指定GPU型号 (默认: $DEFAULT_GPU_MODEL)
  -s, --serve-mode SERVE_MODE 指定部署任务名称 (默认: $DEFAULT_SERVE_MODE)
  -n, --name NAME             指定任务名称 (必选)
      --config FILE           指定配置文件路径, 文件将挂载到容器的/app/config.yaml 并通过 --config 参数传递给vLLM服务
      --*                     其他arena参数直接传递, 参考 arena serve kserve --help
  -h, --help                  显示帮助信息

vLLM参数:
  所有在 '--' 后的参数将直接传递给vLLM服务命令

示例:
  $SCRIPT_NAME Qwen/Qwen3-4B \\
    -n my-task-name -c 16 -m 64 -g 4 --gpu-model A100 \\
    --config config.yaml \\
    --port=8080 --host=0.0.0.0 \\
    -- --host 0.0.0.0 --port 8080 --max-model-len 8192
EOF
}

# 解析命令行参数
parse_args() {
    while [[ "$1" != "" ]]; do
        case $1 in
            -c | --cpu )
                cpu=$2
                shift 2
                ;;
            -m | --memory )
                memory="${2%Gi}Gi"
                shift 2
                ;;
            -g | --gpus )
                gpus=$2
                shift 2
                ;;
            -i | --image )
                image=$2
                shift 2
                ;;
            -gm | --gpu-model )
                gpu_model=$2
                shift 2
                ;;
            -s | --serve-mode )
                serve_mode=$2
                shift 2
                ;;
            -p | --plain )
                plain_mode=1
                shift
                ;;
            -n | --name )
                name=$2
                shift 2
                ;;
            --config )
                config_file=$2
                shift 2
                ;;
            -h | --help )
                show_help
                exit 0
                ;;
            "--" )
                shift
                while [[ "$1" != "" ]]; do
                    vllm_extra_args+=("$1")
                    shift
                done
                ;;
            --* )
                if [[ "$1" == *"="* ]]; then
                    # 处理 --key=value 格式
                    other_args+=("$1")
                    shift
                else
                    # 处理 --key value 格式
                    other_args+=("$1")
                    shift
                    if [[ $# -gt 0 && "$1" != "--"* ]]; then
                        other_args+=("$1")
                        shift
                    fi
                fi
                ;;
            * )
                echo "错误: 未知参数 '$1'"
                echo "使用 '$SCRIPT_NAME --help' 查看帮助信息"
                exit 1
                ;;
        esac
    done
}

# 验证必填参数
validate_required_args() {
    if [[ -z "$name" ]]; then
        echo "错误: 必须提供任务名称 (--name)"
        echo "使用 '$SCRIPT_NAME --help' 查看帮助信息"
        exit 1
    fi
}

# 构建arena命令
build_arena_command() {
    local arena_cmd=("arena serve $serve_mode")

    # 固定参数
    arena_cmd+=("--loglevel debug")
    arena_cmd+=("--name=$name")  # 使用用户提供的任务名
    arena_cmd+=("--cpu=$cpu")
    arena_cmd+=("--memory=$memory")
    # arena_cmd+=("--enable-prometheus=true")
    # arena_cmd+=("--scale-metric=DCGM_CUSTOM_PROCESS_SM_UTIL")
    # arena_cmd+=("--scale-target=60")
    # arena_cmd+=("--min-replicas=1")
    # arena_cmd+=("--max-replicas=1")

    if [[ "$serve_mode" == "kserve" ]]; then
        arena_cmd+=("--port=8000")  # vllm 默认端口
    # elif [[ "$serve_mode" == "triton" ]]; then
        # do nothing
    fi
    # GPU类型条件判断
    if [[ "$gpu_model" == "PPU810E" ]]; then
        # PPU810E专用参数
        if [[ -z "$image" ]]; then
          image="$DEFAULT_PPU_IMAGE"
        fi
        # arena_cmd+=("-l alibabacloud.com/acs=true")                     # 调度 ACS 算力, 仅在 acs 集群有效；ack
        # 不生效
        arena_cmd+=("-l alibabacloud.com/compute-class=gpu-hpn")        # 调度高网算力
        arena_cmd+=("-l alibabacloud.com/gpu-driver-version=1.5.1")     # 最新的驱动版本
        arena_cmd+=("-l alibabacloud.com/compute-qos=default")          # 默认QoS
        arena_cmd+=("-l alibabacloud.com/gpu-model-series=$gpu_model")  # 指定GPU型号
        arena_cmd+=("--device alibabacloud.com/ppu=$gpus")              # 指定PPU数量
        # ack 集群需要使用以下内容调度 acs 资源
        arena_cmd+=("--selector type=virtual-kubelet")
        arena_cmd+=("--toleration virtual-kubelet.io/provider=:NoSchedule,Exists")
    else
        # 其他GPU类型参数（如NVIDIA）
        if [[ -z "$image" ]]; then
          image="$DEFAULT_GPU_IMAGE"
        fi
        if [[ -n "$gpus" ]]; then
          arena_cmd+=("--gpus=$gpus")
        fi
        arena_cmd+=("-l aliyun.accelerator/nvidia_name=$gpu_model")
    fi
    # 配置文件处理
    if [[ -n "$config_file" ]]; then
        arena_cmd+=("--config-file $config_file:/app/config.yaml")
        vllm_config=(--config /app/config.yaml)
    fi

    # 其他参数
    arena_cmd+=("--image=$image")
    arena_cmd+=("${other_args[@]}")
    local vllm_args
    
    # 构造vLLM命令（使用printf %q安全转义）
    if [[ "$plain_mode" -eq 0 ]]; then
        vllm_args=(vllm serve "$model_path" --tensor-parallel-size "$gpus")
        if [[ -n "$vllm_config" ]]; then
            vllm_args+=("${vllm_config[@]}")
        fi
    fi
    
    vllm_args+=("${vllm_extra_args[@]}")

    # 仅当vllm_args非空时进行处理
    if [ ${#vllm_args[@]} -ne 0 ]; then
        # 使用printf %q生成安全的命令字符串
        local vllm_cmd
        printf -v vllm_cmd '%q ' "${vllm_args[@]}"
        vllm_cmd="\"$vllm_cmd\""

        # 添加到arena命令
        arena_cmd+=("$vllm_cmd")

        # 输出最终命令（供eval执行）
    fi
    echo "${arena_cmd[@]}"
}

# 主函数
main() {
    if [[ -z "$1" ]]; then
        echo "错误: 必须提供模型路径作为第一个参数"
        show_help
        exit 1
    fi

    model_path="$1"
    shift

    parse_args "$@"
    validate_required_args
    echo "执行命令: $(build_arena_command)"
    eval "$(build_arena_command)"
}

# 执行主程序
main "$@"
