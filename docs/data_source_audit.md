# 数据源审计与星耀数智 SDK 评估

## 本次发现

本地存在星耀数智 SDK 目录：

```text
D:\myfiles\投资公司\AI\本地数据\星耀数智
```

目录内包含：

- `AmazingData` 多 Python 版本 wheel；
- `tgw-1.0.8.7-py3-none-any.whl`；
- `star_downloader.py`；
- 已验证的 588000 历史分钟线样例输出；
- 开发手册和数据获取说明。

凭证类信息只保留在本地资料中，未写入本项目代码和 Git 提交。

## 适合替换的模块

星耀数智 SDK 更适合替换或增强以下数据：

1. 指数、ETF、个股历史 K 线；
2. 分钟线或日线行情；
3. 复权因子；
4. 本地批量行情仓库。

对当前看板而言，优先可接入：

- `fetch_index_history`：用 SDK 日线替代东方财富指数日线；
- 宽度计算：若 SDK 能批量返回全 A 当日行情，可替代东方财富全 A 快照；
- 趋势确认：用本地授权行情源提高稳定性。

## 不适合直接替换的模块

以下数据仍建议保留官方或专业源：

- 中证指数估值：中证指数、Wind、Choice、iFinD、Tushare Pro；
- 中债收益率曲线与中债财富指数：中国债券信息网或中债授权产品；
- 沪深两融：上交所、深交所官方披露或 Tushare Pro。

## 建议接入方案

新增一个可选 provider：

```text
ASHARE_DATA_PROVIDER=star
STAR_YAO_USERNAME=...
STAR_YAO_PASSWORD=...
STAR_YAO_SDK_DIR=D:\myfiles\投资公司\AI\本地数据\星耀数智
```

接口层保持当前规范化输出 schema 不变，只替换底层数据获取函数。这样前端、评分模型和测试无需大改。

