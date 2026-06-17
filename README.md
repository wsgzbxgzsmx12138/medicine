# NMPA 注册文件准备与审核 Agent

体外诊断试剂注册申报资料的自动化扫描、完整性核查、信息提取、模板填写与合规预警 Demo。

## 快速开始

```bash
cd d:\project\medicine
pip install -r requirements.txt

# Streamlit：自由上传文件夹 或 选内置示例
streamlit run app.py

# CLI：分析任意本地文件夹
python runner.py --input path/to/your/folder
python runner.py --input data/upload/normal --no-llm   # 禁用大模型
```

## 功能

1. **文件目录汇总**：扫描 upload 目录，统计页数，导出 CH1.2 Excel
2. **完整性核查**：对照 `config/nmpa_rules.json`
3. **信息提取**：从说明书规则提取（可选 LLM 增强）
4. **自动填写**：生成 CH1.4、CH1.11.1 已填写 docx
5. **一致性核查**：跨文档字段比对
6. **风险报告**：输出 `data/output/*/风险预警报告.md`

## 测试数据集

| 目录 | 说明 |
|------|------|
| `data/upload/normal` | 10 份原始样本 |
| `data/upload/missing` | 缺少 CH1.4 申请表 |
| `data/upload/conflict` | CH1.4 产品名称故意不一致 |

## LLM（可选）

**网页端**：进入审核工作台后，在侧边栏 **大模型设置** 中填写 DeepSeek API Key（仅保存在当前浏览器会话，适合在线部署）。

**命令行**：可复制 `.env.example` 为 `.env` 并配置 `LLM_API_KEY`。未配置时完全使用规则引擎，不影响 Demo 运行。

## 在线部署

本项目是 **Streamlit 应用**，需要长期运行的 Python 进程，**不能部署到 Vercel**（Vercel 仅支持静态站点与短时 Serverless 函数）。在 Vercel 上会出现克隆成功但构建失败，或找不到输出目录等错误。

推荐使用 **Streamlit Community Cloud**（免费，直接关联 GitHub）：

1. 打开 [share.streamlit.io](https://share.streamlit.io)，用 GitHub 登录
2. 点击 **New app**，选择仓库 `wsgzbxgzsmx12138/medicine`，分支 `main`
3. Main file path 填 `app.py`
4. 点击 **Deploy**（大模型：用户进入工作台后在侧边栏自行填写 DeepSeek API Key，无需在 Secrets 中配置）

备选：**Render**（仓库已含 `Dockerfile` 与 `render.yaml`，在 Render 控制台新建 Web Service 并关联 GitHub 即可）。

## 项目结构

```
app.py          Streamlit UI
runner.py       CLI
core/           五阶段流水线
config/         规则与字段映射
prompts/        LLM 提示词
data/upload/    输入样本
data/output/    运行结果
```
