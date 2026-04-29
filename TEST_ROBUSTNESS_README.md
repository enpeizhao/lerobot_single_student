# 主从臂数据传输稳定性测试工具

本脚本用于分别测试主臂（串口通信）和从臂（TCP通信）的数据传输稳定性，帮助定位遥操作约30秒后停止的问题。

## 问题背景

遥操作循环在 `observation` 为 `None` 时会立即退出。两个子系统都可能导致此问题：
- **主臂（Leader）**：串口读取舵机位置失败 → `get_action()` 返回 `None`
- **从臂（Follower）**：TCP通信或CAN总线故障 → `get_motor_angles()` 返回 `None`

本工具将两侧独立测试，通过采集延迟和失败率数据来确定故障来源。

## 使用方法

### 测试主臂（串口）

```bash
conda run -n lerobot python test_robustness.py --test leader --duration 120 --fps 30
```

### 测试从臂（TCP）

```bash
conda run -n lerobot python test_robustness.py --test follower --duration 120 --fps 30
```

### 同时测试两侧

```bash
conda run -n lerobot python test_robustness.py --test both --duration 120 --fps 30
```

### 导出CSV日志

```bash
conda run -n lerobot python test_robustness.py --test both --duration 120 --fps 30 --log-file results.csv
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

## 输出说明

### 实时状态（每5秒）

```
[  15.0s] LEADER | cycles: 450 | fail: 2 (0.4%) | consec: 0 | avg: 4.2ms | max: 18.7ms | p95: 6.1ms
```

- **cycles**：总读取次数
- **fail**：失败次数及百分比
- **consec**：当前连续失败次数
- **avg/max/p95**：延迟统计（毫秒）

颜色含义：绿色=无失败，黄色=失败率<5%，红色=失败率≥5%

### 最终报告

测试结束后会输出完整报告，包括：
- 总周期数、失败率、最大连续失败次数
- 延迟统计：平均、最大、P95、P99
- 延迟分布直方图
- 前10条失败记录（含时间戳和错误信息）

## 注意事项

1. **测试主臂前**：确保没有其他进程占用串口（如正在运行的遥操作程序）
2. **测试从臂前**：确保机械臂控制器服务已启动（监听在对应IP和端口）
3. 测试过程中遇到失败不会退出，会持续运行直到设定时长结束
4. 按 `Ctrl+C` 可提前终止，仍会输出已收集的统计报告
