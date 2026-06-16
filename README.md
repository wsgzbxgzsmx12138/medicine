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

复制 `.env.example` 为 `.env` 并配置 `LLM_API_KEY`。未配置时完全使用规则引擎，不影响 Demo 运行。

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
