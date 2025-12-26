# 🚀 快速启动指南

## 📦 启动服务

```bash
cd /Users/weitianyi/Desktop/xbuddy/langgraph/my_langgraph_app
./run_with_monitor.sh
```

'''powershell
langgraph dev --host 127.0.0.1 --port 2024
'''
---

## 🌐 访问地址

### 本地访问（在你的 Mac 上）
- **Gradio 前端**: http://127.0.0.1:7860
- **LangGraph 后台**: http://127.0.0.1:2024
- **监控面板**: http://127.0.0.1:8080

### 局域网访问（从手机/其他电脑）
- **Gradio 前端**: http://172.16.80.74:7860
- **LangGraph 后台**: http://172.16.80.74:2024
- **监控面板**: http://172.16.80.74:8080

> ⚠️ **重要**：不要使用 `0.0.0.0`！那只是服务器绑定地址，不是访问地址。

---

## 🎭 切换 AI 人设

### 使用"云朵"人设（默认）
```bash
export PERSONA_NAME=yunduo
./run_with_monitor.sh
```

### 使用"由此"人设
```bash
export PERSONA_NAME=youci
./run_with_monitor.sh
```

### 一次性指定
```bash
PERSONA_NAME=youci ./run_with_monitor.sh
```

---

## 🛑 停止服务

```bash
# 在启动脚本的终端按
Ctrl + C

# 或者手动停止
lsof -ti:2024 | xargs kill -9
lsof -ti:7860 | xargs kill -9
lsof -ti:8080 | xargs kill -9
```

---

## 📋 人设列表

| 人设 | 名称 | 风格 |
|------|------|------|
| `yunduo` | 云朵 | 表面傲娇的AI物种，爱猫 |
| `youci` | 由此 | 温和的拼图伙伴，倾听者 |

---

## ➕ 添加新人设

1. 在 `personas/` 目录创建 `.md` 文件
2. 编写人设内容（参考 `personas/yunduo.md` 或 `personas/youci.md`）
3. 使用新人设名启动

```bash
export PERSONA_NAME=my_persona
./run_with_monitor.sh
```

详细说明请查看：[PERSONA_CONFIG.md](./PERSONA_CONFIG.md)

---

## 🐛 常见问题

### Q: 502 错误？
**A**: 不要用 `0.0.0.0`，改用 `127.0.0.1` 或 `localhost`

### Q: 端口被占用？
**A**: 运行停止命令后再重启

### Q: 修改人设后没生效？
**A**: 需要重启服务（Ctrl+C 后重新运行启动脚本）

---

**🎉 现在可以开始使用了！** 访问 http://127.0.0.1:7860 开始对话！

