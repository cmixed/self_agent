// Vite+ 根配置。
//
// 本仓库不是 JS monorepo（后端是 Python），前端只在 `frontend/` 一个包。
// `defaultPackage` 让 `vp dev` / `vp build` 在仓库根也能直接作用于前端，
// 不需要先 cd（vp 读取此字段时不会执行配置，因此根目录无需安装 vite-plus）。
//
// 这里刻意只写一个纯对象：lint / fmt / test 等配置仍放在 `frontend/vite.config.ts`。
export default {
  defaultPackage: './frontend',
}
