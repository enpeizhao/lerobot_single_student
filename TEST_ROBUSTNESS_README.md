# 主从臂数据传输稳定性测试工具

本脚本用于分别测试主臂（串口通信）和从臂（TCP通信）的数据传输稳定性，帮助定位遥操作约30秒后停止的问题。

使用与 `teleoperate.py` 完全相同的类和函数（`EnpeiLeader.get_action()`、`EnpeiFollower.get_observation()`、`EnpeiFollower.send_action()`），测试真实的重试逻辑、滤波器和故障模式。

## 问题背景

遥操作循环在 `observation` 为 `None` 时会立即退出。两个子系统都可能导致此问题：
- **主臂（Leader）**：串口读取舵机位置失败 → `get_action()` 返回 `None`
- **从臂（Follower）**：TCP通信或CAN总线故障 → `get_observation()` 返回 `None`

本工具将两侧独立测试，通过采集**基于时间的指标**（正常运行率、停机时间、MTBF）来确定故障来源。

## 使用方法

### 测试主臂（串口）

```bash
python -m lerobot.test_robustness --test leader --duration 120 --fps 30
```

### 测试从臂（TCP）

```bash
python -m lerobot.test_robustness --test follower --duration 120 --fps 30
```

### 同时测试两侧

```bash
python -m lerobot.test_robustness --test both --duration 120 --fps 30
```

### 导出CSV日志

```bash
python -m lerobot.test_robustness --test both --log-file results.csv
```

使用 `--test both` 时，CSV文件会自动拆分为 `results_leader.csv` 和 `results_follower.csv`。

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--test` | （必填） | 测试模式：`leader`、`follower` 或 `both` |
| `--duration` | 120 | 测试时长（秒） |
| `--fps` | 30 | 目标读取频率（Hz） |
| `--port` | `/dev/ttyACM0` | 主臂串口端口 |
| `--ip` | `localhost` | 从臂服务器IP |
| `--tcp-port` | 12345 | 从臂服务器TCP端口 |
| `--log-file` | 无 | CSV日志文件路径 |
| `--speed-mode` | `record` | 速度模式：`record`、`inference` 或 `teleop` |

## 输出说明

### 实时状态（每5秒）

```
[  15.0s] LEADER | 正常运行: 100.0% | 循环: 450 | 失败: 0 | 平均: 4.2ms | 最大: 18.7ms
[  35.2s] FOLLOWER | 正常运行: 71.4% | 循环: 753 | 失败: 3 | 停机: 10.1s | 平均: 5.4ms
```

颜色含义：绿色=正常运行率≥99.9%，黄色=≥95%，红色=<95%

### 最终报告

测试结束后会输出完整报告，包括：
- **正常运行时间 / 停机时间**：基于挂钟时间统计，失败循环的内部重试时间也计入停机
- **首次故障时间**：从测试开始到第一次失败的秒数
- **MTBF**：平均故障间隔时间
- 总循环数、失败循环数、最大连续失败次数
- 延迟统计：平均、最大、P95、P99（仅成功循环）
- 延迟分布直方图

## 为什么使用基于时间的指标

生产代码内部有重试机制（`get_observation` 重试3次，`send_command` 重试2次）。单次失败的循环可能阻塞约10秒。如果按循环次数统计，871次成功 + 1次失败 = 0.1% 失败率，但实际上系统已经停机了10秒。基于时间的指标能准确反映真实的停机影响。

## 注意事项

1. **测试主臂前**：确保没有其他进程占用串口（如正在运行的遥操作程序）
2. **测试从臂前**：确保机械臂控制器服务已启动（监听在对应IP和端口）
3. 从臂连接时会自动移动到默认位置（与生产环境一致）
4. 测试过程中遇到失败不会退出，会持续运行直到设定时长结束
5. 按 `Ctrl+C` 可提前终止，仍会输出已收集的统计报告
