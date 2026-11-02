#!/bin/sh
# VS Code Vitest 扩展的 Node 启动包装器（由 .vscode/settings.json 的
# vitest.nodeExecutable 指定，路径用 ${workspaceFolder} 展开）。
#
# 为什么不直接把 preload 写进 vitest.nodeExecArgs：扩展拉起 worker 时的 cwd
# 是**配置文件所在目录**（这里是 frontend/），nodeExecArgs 里的相对路径只能按
# 该 cwd 解析，配置一旦挪位置就会静默失效。用包装器 + `dirname "$0"` 定位，
# 与 cwd 无关。
#
# 作用：给 localhost 补一条 ::1 解析，修复 WSL 下扩展加载配置失败，
# 详见同目录 vitest-localhost-ipv6.cjs 的说明。
# 用 PATH 上的 node（与扩展默认行为一致），只额外插入 preload。
exec node --require "$(dirname "$0")/vitest-localhost-ipv6.cjs" "$@"
