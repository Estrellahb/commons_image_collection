# 显式选择的本地 Docker 工具运行层（可选保留）

> **当前 Linux 默认工作流说明**：`scripts/local_runtime.py` 与 `assets/docker/` 在本工作区**仅作可选保留**（代码保持未改动）。当前默认评测流程直接通过 `python3 skills/zerobench-visual-benchmark/scripts/eval_trials.py` 调用 `.env` 中的 OpenAI 兼容接口进行纯模型直答 4 次（不挂载本地代码工具），**无需启动 Colima 或 Docker 容器**。

`scripts/local_runtime.py` 提供 `start/exec/stop/status` CLI 和可 import 的 `DockerPythonAdapter`。它只负责 Python 工具执行与试次文件，不接 API、不带密钥、不负责出题或判分。只有明确需要工具开放隔离环境并显式调用这个 adapter 时才生效。

## 已选择的环境

- Docker context 默认明确指定 `colima-harbor-parity`，不会依赖当前全局 context，也不切换全局 context。
- 基础镜像为本地 `zerobench/tools:20261126-v1`，Python 3.12 / Linux arm64。包清单以镜像的 `requirements.lock.txt` 和每次启动记录的实际安装版本为准，不自动拉镜像、构建、装包或下载模型。
- 该 Colima 的数据盘是 `~/.colima/_lima/_disks/colima-harbor-parity/datadisk`；启动及后续操作会同时核对 context 的 Unix socket、数据盘真实路径和本地文件系统。Docker Desktop 的 raw 文件指向 PortSSD，因此不用于此运行层。
- 默认试次根目录为 `~/.local/share/zerobench-runtime/trials`。拒绝 `/Volumes`、解析后转向外盘的符号链接、与本地 home 不同文件系统的路径，以及没有本 adapter 标记的非空目录。不会扫描或修改其他现有容器，尤其不碰已有 `r20`/`env-world` 服务。

这些是当前选定环境，不是任意机器通用路径。若换 Colima 配置，先核对该 profile 的 socket 与实际磁盘，不把一个本地空文件当作 Docker 存储位置的证明。

## 文件与容器范围

每个逻辑试次只创建一个容器和专属目录：

```text
trials/
  .zerobench-runtime-root.json
  task-v1-r1/
    runtime.json          # 作者/harness 元数据，不挂入模型容器
    exec.lock
    logs/                 # 代码、限长 stdout、工具回执，不挂入模型容器
    work/                 # 容器 /workspace，读写
      image.png           # 公开图片字节副本，再单独只读挂载
      ...                 # 模型生成的文件，可跨 exec 保留
```

只复制调用方明确提供的一张公开图片，不复制 case 目录、作者答案、事实表、oracle、仓库或 API 配置。图片按原字节复制到 `image.png`，不做渲染、改色、重采样或哈希；实际编码由图像内容决定，不应仅凭扩展名判断。

挂载仅为专属 `work/` → `/workspace` 读写和其 `image.png` → `/workspace/image.png` 只读。不挂 Docker socket。`runtime.json` 和日志在挂载外。通过 `artifact_path()` 读取工具产物时检查实际解析路径，拒绝绝对路径或符号链接越出试次工作目录。

`start` 不覆盖已有非空试次目录；复用已有容器用 `exec`，不要再次 `start`。容器停止后文件保留，需要重新运行时选新试次 ID，避免覆盖旧轨迹。每次 Python exec 是新进程，变量、import 状态不跨次保留，文件会保留。

## 资源和网络

默认每容器 CPU 1、内存 1 GiB、swap 总量与内存同额、PID 上限 128；`start --cpus/--memory/--pids-limit` 可显式调整。根文件系统只读，额外 `/tmp` 为 256 MiB tmpfs；drop 全部 Linux capabilities，设置 no-new-privileges，按当前宿主 UID/GID 执行。实际限制、Python 版本和包版本写入 `runtime.json`。

40 个 API 请求并发不等于同时启动 40 个 CPU 工具。建议 harness 用全局信号量把**正在执行的本地工具调用限制为 4**，同一逻辑试次的工具串行执行。该 helper 只防止同一试次重叠 exec，不在脚本内部替整个评测调度器分配 40 路资源。

网络使用 Docker bridge，允许直接访问公开网站。清除 Docker 客户端进程的代理环境，并显式给容器设置大小写 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY/FTP_PROXY` 为空，覆盖 `~/.docker/config.json` 自动注入的代理。当前通道曾被 `host.docker.internal:7890` 的坏解析影响；不要仅清 shell 代理却忘记客户端自动代理。启动检查发现非空代理或 credential-like 环境变量名称会拒绝继续，不打印凭据值。

Docker bridge **不等于仅允许公网的防火墙**；本 helper 没有改动宿主网络/iptables，也不宣称阻断所有私网地址。若评测另有公网出口白名单，须由 harness/现有网络方案显式提供并记录，不改现有服务网络来临时实现。

## CLI 使用

在本项目中从 skill 目录或项目根目录直接使用 Linux `python3` 运行下面命令（无需 `uv`，默认直调评测也无需启动或重建 Docker 镜像）。需要按锁定包版本重建时：

```bash
docker --context colima-harbor-parity build \
  --build-arg HTTP_PROXY= --build-arg HTTPS_PROXY= --build-arg ALL_PROXY= \
  --build-arg http_proxy= --build-arg https_proxy= --build-arg all_proxy= \
  -t zerobench/tools:20261126-v1 assets/docker
```

该命令使用 `requirements.lock.txt`；基础系统包仍由基础镜像与 Debian 仓库决定，不能将它说成逐字节可重现构建。`requirements.in` 仅保留依赖意图，更新依赖需要另记镜像版本和实际包清单。

```bash
python3 skills/zerobench-visual-benchmark/scripts/local_runtime.py start \
  --context colima-harbor-parity --trial task-v1-r1 \
  --public-image /absolute/path/to/main.png \
  --image zerobench/tools:20261126-v1 --cpus 1 --memory 1g

python3 skills/zerobench-visual-benchmark/scripts/local_runtime.py exec \
  --context colima-harbor-parity --trial task-v1-r1 \
  --remaining-seconds 120 --timeout 60 --code-file /path/to/public-tool-code.py

python3 skills/zerobench-visual-benchmark/scripts/local_runtime.py status --context colima-harbor-parity --trial task-v1-r1
python3 skills/zerobench-visual-benchmark/scripts/local_runtime.py stop --context colima-harbor-parity --trial task-v1-r1
```

也可 `exec --stdin` 从标准输入传 Python 代码。只有明确 `start` 才创建试次容器；`status` 是只读查看。`stop` 每次检查本脚本标签、试次 ID 和私有 ownership token 匹配，仅移除该容器，保留全部产物；不会按模糊名称批量删除容器。

## 在 harness 中接入

把脚本目录加入你自己的工具模块导入路径，显式创建 adapter。调用方负责保存原始模型响应、工具返回和预算；API key 始终留在 harness，绝不传入容器环境或工作目录。

`start/status` 的环境与路径元数据留在 harness 侧。向模型返回 Python 工具结果时只选所需的 `status/exit_code/output/error` 等公开字段，完整日志位置和控制元数据保留为作者证据，不把整个控制对象塞进模型上下文。

```python
import time
from local_runtime import DockerPythonAdapter

trial_deadline = time.monotonic() + 1800  # 来自本逻辑试次的剩余总预算约定
adapter = DockerPythonAdapter(
    "task-v1-r1",
    context="colima-harbor-parity",
    image="zerobench/tools:20261126-v1",
    cpus=1,
    memory="1g",
)
try:
    adapter.start(public_image_path, remaining_seconds=trial_deadline - time.monotonic())
    result = adapter.run_python(
        model_supplied_python,
        remaining_seconds=trial_deadline - time.monotonic(),
        timeout_seconds=60,
    )
    # 后续调用复用 adapter/容器；每次重新传实际剩余预算。
    # 图像裁剪、view_local_image 使用 adapter.artifact_path("image.png"/"result.png")。
finally:
    adapter.stop()
```

不要给每次工具调用重新发一份 1800 秒总预算。`run_python` 的控制准备、容器执行与输出等待共同消耗 `min(调用方剩余时间, 单次工具上限)`。工具回执包含实际秒数、限长输出、日志位置及退出状态；没有在 helper 中引入模型、判分或“首错停”的逻辑。

## 超时、中断与清理证据

若 caller 预算或工具上限到达，helper 先通过 Docker daemon 强制移除**已核对所有权的容器**，再确认容器不存在，最后清理本地 docker 客户端。不会仅杀客户端却把 Python 留在后台继续运行。此次容器不能再 exec，产物保留；harness 应把它记作工具/预算中断，而不是完整错答。

清理另有最多 20 秒的控制预算，用于停掉已超时的执行；这不是给模型延长的推理预算，返回耗时会包含清理时间。若 daemon 失联导致无法确认容器停止，状态为 `cleanup_failed` 并抛 `CleanupFailed`，不能声称已停止，也不能继续在此试次调度工具。恢复 Docker 可用后针对同一试次运行 `stop`，仍保留原超时与清理失败记录。

stdout 日志默认最多保留 1 MiB、工具回复最多 24,000 字符，超出会标记截断；模型需要完整中间数据时应写工作文件。容器 CPU/内存/时间受限不等于题目很难。harness 仍应把服务、工具、资源限制与科学/视觉失败分别归因。

2026-11-26 主流程已用公开货架图实际执行图像处理、连续调用文件读取、SymPy/NetworkX/RDKit、OCR、PDF/视频工具版本及公开 HTTPS 访问，并核对只读图片挂载和超时后的容器移除。工作文件保留，临时执行容器已移除。详细回执在交付包的 execution_records 中；这些只是运行层验证，未调用模型，也不意味着历史 runner 已接入。首次部署到其他环境仍须核对实际存储、依赖和执行条件。
