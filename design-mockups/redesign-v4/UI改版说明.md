# redesign-v4 · D 方向已落到生产代码，截图验收中（未部署未提交）

2026-09-22。用户批线上"挫、愣" → 定调 **大气、干净、简约** + **客户 40+** → 四方向样张挑了 **D** → 四页样张过审（"可以，干吧"）→ **已落进工作区生产代码**。

## 改了哪些文件

| 文件 | 是什么 |
|---|---|
| `videogen/renderer/src/tool/ui.css` | **首页 `/` 浏览器成片台**的令牌与组件（用户批"愣"的主页面） |
| `videogen/renderer/src/tool/index.tsx` | 主题名"紫玉描金"→"石墨金"（value 仍 ziyu） |
| `videogen/server_static/index.html` | `/studio` 工作台全套（同一套 D 令牌） |
| `videogen/server_static/poc/bundle.js` | 成片台构建产物（`cd renderer && npm run build:tool` 后拷贝） |

注意：**批"愣"的 UI 是 `/` 成片台，不是 `/studio`**；两个前端令牌各自内联，改主题两边都要动。

## 验收截图（shots/prod-*.png，本地起服务 + 真实 F35 素材包走流程）

- `prod-tool-import.png` / `prod-tool-confirm.png` — 成片台导入态、内容确认态（白「生成视频」按钮、金勾步骤）
- `prod-studio-home-2.png` / `prod-studio-confirm-2.png` / `prod-studio-export.png` — 工作台首页/确认/导出
- `prod-studio-generate.png` — 项目没跑过生成时路由守卫弹回确认页，生成页样式随组件生效
- 第一轮方向样张 sample-a/b/c/d 与 home-d/confirm-d/generate-d 保留在同目录

## 测试

`frontend.test.cjs` **37/37 全过**（含 WCAG AA 对比度测试，--ink-3 定 #85858D）。
⚠️ 测试护栏断言生成页不得出现 8 阶段清单（`#vg-stages/.vg-stage`）——样张里生成页右侧的清单因此没做，那是既定设计决策。

## 顺手修的老 bug

`body.vg-production` 里 `--bg:var(--bg)` 一类自引用别名会让变量失效（headless 下流程页白屏），已删。

## 未动

- 未 commit、未部署（等验收）。
- 落地页（营销页）、定价/权益页、作品库还没铺 D。
- `_diag/` 里的 shot_proxy.py / shot_cdp.cjs 是验收工具，可删。
