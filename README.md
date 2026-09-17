# lighter-robinhood-arb

Lighter 主网 × Lighter on Robinhood Chain 的 BTC 永续套利机器人。

引擎、盘口、下单、对冲的实现来自 [entropy-arb](https://github.com/your-quantguy/entropy-arb)（MIT，见 `LICENSE.entropy-arb`）。本仓库做了两处改动：让两条腿都是 zkLighter 部署（上游的基准腿固定在 Hyperliquid 上），并移除了全部 Hyperliquid / Entropy 相关代码。

## 信号

```
premium_bps = (Lighter 价 / Robinhood 价 - 1) * 10000

卖 Lighter / 买 Robinhood   当可执行溢价 >= midline + upper
买 Lighter / 卖 Robinhood   当可执行溢价 <= midline - lower
```

三个阈值写死在 `config.yaml`，两个门槛都已扣除双边吃单手续费，所以一次完整往返扣费后净赚 >= `upper + lower` bps。

## 用法

```bash
pip install -r requirements.txt
cp .env.example .env          # 填两组密钥：主网 LIGHTER_*，Robinhood 链 RH_*

# 1. 先采集数据，不下单、不需要密钥
python3 main.py --record-only --symbol BTC

# 2. 用采集到的数据复核阈值，填进 config.yaml
python3 tools/analyze.py

# 3. 实盘（会下真单）。--cn 中文仪表盘
python3 main.py --symbol BTC --cn
```

两条腿默认是 `--base lighter`（主网）和 `--hedge lighter-rh`（Robinhood 链），对调这两个参数即可反转溢价方向。

没有模拟盘模式：要么 `--record-only` 采集，要么实盘。**先把 `config.yaml` 里的 `max_position_usd` 调到很小再开实盘。**

两条腿是两个独立账户，各自的 API key 必须分别注册。

## 它怎么工作

- **行情**：订阅两边的 `order_book` 全深度（快照 + 增量）。增量带 nonce，一旦跳号说明丢了更新，直接清空重订阅，绝不拿残缺盘口报价。静市不算行情过期，只有连接断了才算。
- **下单量**：先逐档算出当前价差下还能吃多少量，再吃其中 `take_fraction`，并受单笔名义上限和持仓上限裁剪。不是固定单量。
- **成交确认**：两腿同时发 IOC 单，通过认证的 `account_orders` 频道等每单终态，拿到精确成交量和均价。
- **两腿不平衡**：净敞口超过 `net_tolerance_base` 时，用 `reduce_only` 减掉多出来的那条腿（只减不加，保证金不足也不会被拒），而不是去补缺的腿。
- **持仓核对**：每 15 秒用 REST 核对真实持仓；刚成交过 5 秒内的交易所跳过，因为 Lighter 的 REST 持仓滞后于 ws 成交，否则会触发来回抽搐的假对冲。
- **停机保护**：连续 3 次执行异常就停机，等人工平仓后重启。

## 旧脚本

`monitor.py` / `analyze.py` / `alert.py` 是早期的顶档采集、回测和桌面提醒工具，读写 `data/premium_data.csv`，与新引擎无关，保留用于分析历史数据。新引擎自己的采集在 `logs/minutes.csv`，对应 `tools/analyze.py`。
