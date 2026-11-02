// VS Code Vitest 扩展在 WSL 下的启动补丁。
//
// 由同目录的 node-localhost-ipv6.sh（settings.json 的 `vitest.nodeExecutable`）
// 用 `node --require` 注入到扩展拉起的 Node 进程（以及它 fork 的测试 worker），
// 不修改任何系统配置。
//
// 症状（扩展的「输出 → Vitest」里可以看到）：
//   There were errors during config load.
//   [Error Error] Vitest process exited with code 1
//   Error: The extension could not load any config.
//
// 原因（本机实测，缺一不可）：
//   1. 扩展在工作区进程里用 `http.createServer().listen(0)` 建 WebSocket 服务，
//      该端口监听的是 IPv6 通配地址 `::`；
//   2. WSL2 内核不接受连到 IPv6 socket 的 IPv4 连接（`bindv6only=0` 也一样）：
//      `::` 监听 + `127.0.0.1` 连接 = ECONNREFUSED，`::1` 连接正常；
//   3. /etc/hosts 只有 `127.0.0.1 localhost`（`::1` 只映射到 ip6-localhost），
//      所以 dns.lookup('localhost') 只返回 127.0.0.1，
//      worker 连 `ws://localhost:PORT` 被拒 → 进程退出码 1 → 扩展认为配置加载失败。
//
// 处理：给 localhost 的解析结果补一条 ::1。Node 20+ 默认开启 Happy Eyeballs
// （autoSelectFamily），拿到多个地址时会依次尝试，IPv4 失败后自动回退到 ::1。
//
// 永久方案（届时可删除本文件、包装器与 settings 里的 nodeExecutable）：让 localhost
// 同时映射到 ::1，即在 /etc/hosts 增加 `::1 localhost`。注意 WSL 每次启动会重写
// /etc/hosts，想持久需要配合 /etc/wsl.conf 的 `[network] generateHosts=false` 自行维护。
// 这不影响 `vp test`（终端里一直可用），只影响扩展拉起的那个 Node 子进程。

const dns = require('node:dns')

const IPV6_LOOPBACK = { address: '::1', family: 6 }
const originalLookup = dns.lookup

/** 只处理 `localhost`（含结尾点写法），其余主机名原样交给系统解析。 */
function isLocalhost(host) {
  return typeof host === 'string' && host.toLowerCase().replace(/\.$/, '') === 'localhost'
}

dns.lookup = function lookupWithIpv6Loopback(host, options, callback) {
  if (typeof options === 'function') {
    callback = options
    options = {}
  }
  if (!isLocalhost(host) || typeof callback !== 'function') {
    // 不传 callback 的 Promise 形式、非 localhost、非字符串主机：保持原行为
    return originalLookup.call(dns, host, options, callback)
  }

  // 先取系统的完整结果（不限定 family），再把缺失的 ::1 补进去
  originalLookup.call(dns, host, { all: true }, (error, addresses) => {
    if (error) return callback(error)
    const results = Array.isArray(addresses) ? addresses.slice() : []
    // 系统一条都没给时也要能连上（正常情况下 localhost 至少有 127.0.0.1）
    if (!results.length) results.push({ address: '127.0.0.1', family: 4 })
    if (!results.some((entry) => entry.family === 6)) results.push(IPV6_LOOPBACK)
    if (options && typeof options === 'object' && options.all) {
      return callback(null, results)
    }
    // 调用方只要单个地址时保持系统原有顺序（与打补丁前一致）
    return callback(null, results[0].address, results[0].family)
  })
}
