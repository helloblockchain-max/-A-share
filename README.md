# A股指标检测网页看板

本项目把 A 股顶部风险研究框架落地为可每日访问的网页看板：综合估值 ERP、债券压制、股债相对强弱、市场宽度、两融拥挤度、趋势确认和数据源可靠性，形成“顶部概率评分 + 确认矩阵”。

## 每天访问的网页

- GitHub Pages 地址：<https://helloblockchain-max.github.io/-A-share/>
- 自动发布时间：北京时间每天 **08:45**、**09:15**。
- 发布方式：GitHub Actions 定时拉取公开数据源，生成 `dashboard.json` 静态快照，并推送到 `gh-pages` 分支供 GitHub Pages 发布。
- 可访问性兜底：仓库内保留 `web/dashboard.json` 最近快照；若 GitHub Actions 环境临时无法访问某个公开数据源，仍会发布该快照并在页面“风险提示”中标注降级原因，避免网页空白。

首次启用时，请在 GitHub 仓库页面进入 **Settings → Pages → Build and deployment → Source**，选择 **Deploy from a branch**，分支选择 **gh-pages**，目录选择 **/(root)**。之后等待 Pages 首次发布完成即可访问网页。

## 本地快速启动

```powershell
pip install -e .[test]
uvicorn ashare_indicator_monitor.app:app --reload --host 127.0.0.1 --port 8000
```

然后打开：

```text
http://127.0.0.1:8000
```

## 生成静态网页

```powershell
python scripts/build_static_site.py --output dist
python -m http.server 8765 -d dist
```

然后打开：

```text
http://127.0.0.1:8765/
```

静态网页会读取同目录下的 `dashboard.json`；在 GitHub Pages 上点击“重新读取快照”会重新拉取最新已发布快照，不会直接请求动态后端。

## 定时更新机制

`.github/workflows/scheduled-refresh.yml` 已配置：

- `push main`：代码更新后自动构建并部署网页；
- `workflow_dispatch`：可在 GitHub Actions 页面手动触发；
- `schedule`：UTC 00:45、01:15，对应北京时间 08:45、09:15。

工作流会执行测试、生成静态站点，并把产物发布到 `gh-pages` 分支；GitHub Pages 只需要绑定该分支根目录即可。

## 指标版本：v2.1 确认矩阵

- 顶部确认矩阵：热度/拥挤、债券压制、内部脆弱、趋势确认四段式展示；
- 阶段研判与风控动作提示：区分“健康上涨”“估值偏热”“顶部预警”“顶部确认”等状态；
- 市场宽度增强：加入全 A 涨跌幅中位数，避免少数极端股扭曲宽度判断；
- 趋势确认增强：加入沪深300 20 日收益、距 120 日高点回撤和 120 日均线；
- 数据置信度：按核心数据源状态折算为 0-100 分，并展示需要核对的来源。

## 数据源设计

- 行情与成交：东方财富公开行情接口，带本地缓存、超时与重试；
- 指数估值：中证指数官网估值文件；历史分位使用乐咕乐股长序列，并与中证指数近期估值交叉校验；
- 国债收益率与中债国债财富指数：中国债券信息网；
- 两融：金十聚合的沪深两市两融历史序列，网页会明确标注“第三方聚合”；生产部署建议替换为上交所/深交所或 Tushare Pro 官方链路；
- 宽度：东方财富全 A 实时快照计算上涨家数、下跌家数、60 日涨幅为正占比、成交额、流通市值等。

所有核心数据都带有 `as_of`、`fetched_at`、`status` 和风险提示；接口失败时会优先读取本地缓存并标注缓存/过期状态，不会伪造实时数据。

## 验证

```powershell
python -m pytest
python scripts/build_static_site.py --output dist-test
```

## 风险提示

本看板用于量化监控与风险提示，不构成投资建议。评分越高表示顶部风险越高，但不是交易指令，请结合仓位、组合约束和风控规则使用。
